from sqlalchemy import Column, ForeignKey, Integer, String
from app.models.base import BaseModel


class OrderShipping(BaseModel):
    __tablename__ = "order_shipping"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, unique=True, index=True)

    recipient_name = Column(String(100), nullable=False)
    recipient_phone = Column(String(20), nullable=False)
    zipcode = Column(String(10), nullable=False)
    address1 = Column(String(255), nullable=False)
    address2 = Column(String(255), nullable=True)
    delivery_request = Column(String(255), nullable=True)