from sqlalchemy import Boolean, Column, ForeignKey, Integer
from app.models.base import BaseModel


class CartItem(BaseModel):
    __tablename__ = "cart_item"

    id = Column(Integer, primary_key=True, index=True)
    cart_id = Column(Integer, ForeignKey("cart.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("product.id"), nullable=False, index=True)

    quantity = Column(Integer, nullable=False)
    unit_price_snapshot = Column(Integer, nullable=False)
    is_selected = Column(Boolean, nullable=False, default=True)