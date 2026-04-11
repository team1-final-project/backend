import base64
import os

import requests
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.enums import InventoryChangeType, OrderStatus, PaymentProvider, PaymentStatus
from app.core.timezone import now_kst
from app.models.cart_item import CartItem
from app.models.inventory_log import InventoryLog
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.payment import Payment
from app.models.product import Product
from app.schemas.payment import TossConfirmRequest

TOSS_CONFIRM_URL = "https://api.tosspayments.com/v1/payments/confirm"


class PaymentService:
    @staticmethod
    def _build_toss_auth(secret_key: str) -> str:
        raw = f"{secret_key}:".encode("utf-8")
        encoded = base64.b64encode(raw).decode("utf-8")
        return f"Basic {encoded}"

    @staticmethod
    def _decrease_stock_after_payment(db: Session, order: Order) -> list[OrderItem]:
        items = db.query(OrderItem).filter(OrderItem.order_id == order.id).all()

        for item in items:
            product = db.query(Product).filter(Product.id == item.product_id).first()

            if not product:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="상품이 없습니다.",
                )

            if product.stock_qty < item.quantity:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"{product.product_name} 상품의 재고가 부족합니다.",
                )

            qty_before = product.stock_qty
            qty_after = qty_before - item.quantity
            product.stock_qty = qty_after

            inventory_log = InventoryLog(
                product_id=product.id,
                change_type=InventoryChangeType.ORDER_OUT,
                qty_before=qty_before,
                change_qty=-item.quantity,
                qty_after=qty_after,
                related_order_item_id=item.id,
                note=f"토스 결제 완료로 인한 재고 차감 (order_no={order.order_no})",
                created_by=order.member_id,
                occurred_at=now_kst(),
            )
            db.add(inventory_log)

        return items

    @staticmethod
    def _clear_paid_cart_items(db: Session, order_items: list[OrderItem]) -> None:
        target_order_items = [
            item for item in order_items
            if item.cart_item_id is not None
        ]

        if not target_order_items:
            return

        cart_item_ids = [item.cart_item_id for item in target_order_items]

        for item in target_order_items:
            item.cart_item_id = None
            db.add(item)

        db.flush()

        db.query(CartItem).filter(CartItem.id.in_(cart_item_ids)).delete(
            synchronize_session=False
        )

    @staticmethod
    def confirm_toss_payment(db: Session, request: TossConfirmRequest):
        order = db.query(Order).filter(Order.order_no == request.orderId).first()

        if not order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="주문이 없습니다.",
            )

        if order.payment_status == PaymentStatus.APPROVED:
            existing_items = db.query(OrderItem).filter(OrderItem.order_id == order.id).all()

            return {
                "message": "이미 결제 완료된 주문입니다.",
                "order_id": order.id,
                "order_no": order.order_no,
                "payment_status": order.payment_status,
                "paid_at": order.paid_at,
                "order_name": PaymentService._build_order_name(existing_items),
            }

        if int(order.total_payment_amount) != int(request.amount):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="결제 금액이 주문 금액과 일치하지 않습니다.",
            )

        toss_secret_key = os.getenv("TOSS_SECRET_KEY")
        if not toss_secret_key:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="TOSS_SECRET_KEY가 설정되지 않았습니다.",
            )

        headers = {
            "Authorization": PaymentService._build_toss_auth(toss_secret_key),
            "Content-Type": "application/json",
            "Idempotency-Key": f"toss-confirm-{request.orderId}",
        }

        payload = {
            "paymentKey": request.paymentKey,
            "orderId": request.orderId,
            "amount": request.amount,
        }

        try:
            response = requests.post(
                TOSS_CONFIRM_URL,
                headers=headers,
                json=payload,
                timeout=15,
            )
        except requests.exceptions.Timeout:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="토스 결제 승인 요청 시간이 초과되었습니다.",
            )
        except requests.RequestException as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"토스 결제 승인 요청에 실패했습니다. {str(exc)}",
            )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=response.text,
            )

        toss_data = response.json()

        payment = db.query(Payment).filter(Payment.order_id == order.id).first()
        if payment is None:
            payment = Payment(order_id=order.id)
            db.add(payment)

        payment.provider = PaymentProvider.TOSS
        payment.payment_key = toss_data.get("paymentKey")
        payment.provider_order_id = toss_data.get("orderId")
        payment.method = toss_data.get("method")
        payment.amount = toss_data.get("totalAmount", request.amount)
        payment.status = toss_data.get("status", "DONE")
        payment.approved_at = now_kst()
        payment.canceled_at = None
        payment.raw_response = toss_data

        order.payment_status = PaymentStatus.APPROVED
        order.order_status = OrderStatus.PAID
        order.paid_at = now_kst()

        try:
            order_items = PaymentService._decrease_stock_after_payment(db, order)
            PaymentService._clear_paid_cart_items(db, order_items)
            db.commit()
            db.refresh(order)
        except Exception:
            db.rollback()
            raise

        return {
            "message": "토스 결제 승인 완료",
            "order_id": order.id,
            "order_no": order.order_no,
            "payment_status": order.payment_status,
            "paid_at": order.paid_at,
            "order_name": PaymentService._build_order_name(order_items),
        }
    
    @staticmethod
    def _build_order_name(order_items: list[OrderItem]) -> str:
        if not order_items:
            return "주문 상품"

        first_item_name = order_items[0].product_name
        if len(order_items) == 1:
            return first_item_name

        return f"{first_item_name} 외 {len(order_items) - 1}건"