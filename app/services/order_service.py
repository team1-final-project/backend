from secrets import token_hex

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.enums import CartStatus, OrderStatus, PaymentStatus, ProductSaleStatus
from app.core.timezone import now_kst
from app.models.cart import Cart
from app.models.cart_item import CartItem
from app.models.member import Member
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.order_shipping import OrderShipping
from app.models.product import Product
from app.schemas.order import OrderCreateRequest


class OrderService:
    @staticmethod
    def _generate_order_no() -> str:
        return f"ORD{now_kst().strftime('%Y%m%d%H%M%S')}{token_hex(3).upper()}"

    @staticmethod
    def create_order(
        db: Session,
        current_user: Member,
        payload: OrderCreateRequest,
    ) -> dict:
        if not payload.items:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="주문할 상품이 없습니다.",
            )

        active_cart = (
            db.query(Cart)
            .filter(
                Cart.member_id == current_user.id,
                Cart.status == CartStatus.ACTIVE,
            )
            .first()
        )

        total_product_amount = 0
        order_items_to_create: list[OrderItem] = []

        for request_item in payload.items:
            cart_item = None
            quantity = request_item.quantity

            if request_item.cart_item_id is not None:
                if active_cart is None:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="활성 장바구니가 없습니다.",
                    )

                cart_item = (
                    db.query(CartItem)
                    .filter(
                        CartItem.id == request_item.cart_item_id,
                        CartItem.cart_id == active_cart.id,
                    )
                    .first()
                )

                if cart_item is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"장바구니 항목이 없습니다. cart_item_id={request_item.cart_item_id}",
                    )

                if cart_item.product_id != request_item.product_id:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="장바구니 상품 정보가 올바르지 않습니다.",
                    )

                quantity = cart_item.quantity

            product = (
                db.query(Product)
                .filter(Product.id == request_item.product_id)
                .first()
            )

            if product is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"상품이 없습니다. product_id={request_item.product_id}",
                )

            if product.sale_status != ProductSaleStatus.ON_SALE:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"{product.product_name} 상품은 현재 주문할 수 없습니다.",
                )

            if product.stock_qty < quantity:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"{product.product_name} 상품의 재고가 부족합니다.",
                )

            line_amount = int(product.sale_price) * int(quantity)
            total_product_amount += line_amount

            order_items_to_create.append(
                OrderItem(
                    product_id=product.id,
                    cart_item_id=request_item.cart_item_id,
                    product_code=product.product_code,
                    product_name=product.product_name,
                    unit_price=product.sale_price,
                    quantity=quantity,
                    line_amount=line_amount,
                )
            )

        total_shipping_fee = 0
        total_payment_amount = total_product_amount + total_shipping_fee
        order_no = OrderService._generate_order_no()

        first_item_name = order_items_to_create[0].product_name
        if len(order_items_to_create) == 1:
            order_name = first_item_name
        else:
            order_name = f"{first_item_name} 외 {len(order_items_to_create) - 1}건"

        order = Order(
            order_no=order_no,
            member_id=current_user.id,
            order_status=OrderStatus.PAYMENT_PENDING,
            payment_status=PaymentStatus.READY,
            total_product_amount=total_product_amount,
            total_shipping_fee=total_shipping_fee,
            total_payment_amount=total_payment_amount,
            ordered_at=now_kst(),
            paid_at=None,
            canceled_at=None,
        )

        db.add(order)
        db.flush()

        for order_item in order_items_to_create:
            order_item.order_id = order.id
            db.add(order_item)

        shipping = OrderShipping(
            order_id=order.id,
            recipient_name=payload.shipping.recipient_name,
            recipient_phone=payload.shipping.recipient_phone,
            zipcode=payload.shipping.zipcode,
            address1=payload.shipping.address1,
            address2=payload.shipping.address2,
            delivery_request=payload.shipping.delivery_request,
        )
        db.add(shipping)

        db.commit()
        db.refresh(order)

        return {
            "order_id": order.id,
            "order_no": order.order_no,
            "amount": order.total_payment_amount,
            "order_name": order_name,
        }