import os
import base64
from datetime import datetime

import requests
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.product import Product
from app.models.inventory_log import InventoryLog
from app.schemas.payment import TossConfirmRequest

TOSS_CONFIRM_URL = "https://api.tosspayments.com/v1/payments/confirm"


class PaymentService:
    @staticmethod
    def _build_toss_auth(secret_key: str) -> str:
        raw = f"{secret_key}:".encode("utf-8")
        encoded = base64.b64encode(raw).decode("utf-8")
        return f"Basic {encoded}"

    @staticmethod
    def _decrease_stock_after_payment(db: Session, order: Order) -> None:
        
        items = db.query(OrderItem).filter(OrderItem.order_id == order.id).all()
        

        for item in items:
           
            product = db.query(Product).filter(Product.id == item.product_id).first()

            if not product:
                raise HTTPException(status_code=404, detail="상품이 없습니다.")

            if product.stock < item.quantity:
                raise HTTPException(status_code=400, detail="재고가 부족합니다.")

            product.stock -= item.quantity
            

            log = InventoryLog(
                product_id=product.id,
                quantity=item.quantity,
                type="OUT",
                reason=f"결제 완료 출고(order_id={order.order_id})"
            )
            db.add(log)
            

    @staticmethod
    def confirm_toss_payment(db: Session, request: TossConfirmRequest):
        
        
        order = db.query(Order).filter(Order.order_id == request.orderId).first()
       
        
        if not order:
            raise HTTPException(status_code=404, detail="주문이 없습니다.")

        

        if order.status == "PAID":
            return {
                "message": "이미 결제 완료된 주문입니다.",
                "order_id": order.order_id,
                "status": order.status,
            }

        if order.status not in ["PENDING", "READY"]:
            raise HTTPException(status_code=400, detail="결제 가능한 주문 상태가 아닙니다.")

        if int(order.total_price) != int(request.amount):
            raise HTTPException(status_code=400, detail="금액이 일치하지 않습니다.")

        toss_secret_key = os.getenv("TOSS_SECRET_KEY")
        

        if not toss_secret_key:
            raise HTTPException(status_code=500, detail="TOSS_SECRET_KEY가 없습니다.")

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
            
            raise HTTPException(status_code=504, detail="토스 승인 요청 시간 초과")
        except requests.RequestException as e:
            
            raise HTTPException(status_code=502, detail=f"Toss 호출 실패: {str(e)}")

        if response.status_code != 200:
            raise HTTPException(status_code=502, detail=response.text)

        toss_data = response.json()
        

        try:
            order.status = "PAID"
            order.payment_type = "TOSS"
            order.paid_at = datetime.utcnow()

            if hasattr(order, "payment_key"):
                order.payment_key = toss_data.get("paymentKey")
               

            PaymentService._decrease_stock_after_payment(db, order)

            db.commit()
            db.refresh(order)
            

        except Exception:
            db.rollback()
            
            raise

        return {
            "message": "토스 결제 승인 완료",
            "order_id": order.order_id,
            "status": order.status,
            "paid_at": order.paid_at,
        }