from sqlalchemy import Column, Enum as SqlEnum, ForeignKey, Integer
from app.core.enums import CartStatus
from app.models.base import BaseModel


class Cart(BaseModel):
    __tablename__ = "cart"

    id = Column(Integer, primary_key=True, index=True)
    member_id = Column(Integer, ForeignKey("member.id"), nullable=False, index=True)
    status = Column(
        SqlEnum(CartStatus, name="cart_status_enum"),
        nullable=False,
        default=CartStatus.ACTIVE,
    )