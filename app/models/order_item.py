from sqlalchemy import Column, ForeignKey, Integer, String
from app.models.base import BaseModel


class OrderItem(BaseModel):
    __tablename__ = "order_item"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("product.id"), nullable=False, index=True)

    product_code = Column(String(50), nullable=False)
    product_name = Column(String(255), nullable=False)

    unit_price = Column(Integer, nullable=False)
    quantity = Column(Integer, nullable=False)
    line_amount = Column(Integer, nullable=False)