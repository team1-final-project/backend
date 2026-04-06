from sqlalchemy import Column, Integer
from app.models.base import BaseModel


class OrderItem(BaseModel):
    __tablename__ = "order_items"   # 실제 DB 테이블명에 맞게 수정

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, nullable=False, index=True)
    product_id = Column(Integer, nullable=False, index=True)
    quantity = Column(Integer, nullable=False, default=1)