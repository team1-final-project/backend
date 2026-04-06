from sqlalchemy import Column, Integer, String, DateTime
from app.models.base import BaseModel


class Order(BaseModel):
    __tablename__ = "orders"   # 실제 DB 테이블명에 맞게 수정

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(String(100), unique=True, nullable=False, index=True)
    status = Column(String(20), nullable=False, default="PENDING")
    total_price = Column(Integer, nullable=False)

    payment_type = Column(String(20), nullable=True)
    payment_key = Column(String(255), nullable=True)
    paid_at = Column(DateTime, nullable=True)