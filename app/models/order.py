from sqlalchemy import Column, DateTime, Enum as SqlEnum, ForeignKey, Integer, String
from app.core.enums import OrderStatus, PaymentStatus
from app.models.base import BaseModel


class Order(BaseModel):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    order_no = Column(String(50), nullable=False, unique=True, index=True)
    member_id = Column(Integer, ForeignKey("member.id"), nullable=False, index=True)

    order_status = Column(
        SqlEnum(OrderStatus, name="order_status_enum"),
        nullable=False,
        default=OrderStatus.CREATED,
    )
    payment_status = Column(
        SqlEnum(PaymentStatus, name="payment_status_enum"),
        nullable=False,
        default=PaymentStatus.READY,
    )

    total_product_amount = Column(Integer, nullable=False, default=0)
    total_shipping_fee = Column(Integer, nullable=False, default=0)
    total_payment_amount = Column(Integer, nullable=False, default=0)

    ordered_at = Column(DateTime, nullable=False)
    paid_at = Column(DateTime, nullable=True)
    canceled_at = Column(DateTime, nullable=True)