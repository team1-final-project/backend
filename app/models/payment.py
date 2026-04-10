from sqlalchemy import Column, DateTime, Enum as SqlEnum, ForeignKey, Integer, JSON, String
from app.core.enums import PaymentProvider
from app.models.base import BaseModel


class Payment(BaseModel):
    __tablename__ = "payment"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, unique=True, index=True)

    provider = Column(
        SqlEnum(PaymentProvider, name="payment_provider_enum"),
        nullable=False,
        default=PaymentProvider.TOSS,
    )
    payment_key = Column(String(200), nullable=True, unique=True)
    provider_order_id = Column(String(100), nullable=True)
    method = Column(String(50), nullable=True)

    amount = Column(Integer, nullable=False)
    status = Column(String(50), nullable=False)
    approved_at = Column(DateTime, nullable=True)
    canceled_at = Column(DateTime, nullable=True)

    raw_response = Column(JSON, nullable=True)