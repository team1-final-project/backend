from sqlalchemy import Column, DateTime, Enum as SqlEnum, ForeignKey, Integer, String
from app.core.enums import InventoryChangeType
from app.models.base import BaseModel


class InventoryLog(BaseModel):
    __tablename__ = "inventory_log"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("product.id"), nullable=False, index=True)
    change_type = Column(
        SqlEnum(InventoryChangeType, name="inventory_change_type_enum"),
        nullable=False,
    )

    qty_before = Column(Integer, nullable=False)
    change_qty = Column(Integer, nullable=False)
    qty_after = Column(Integer, nullable=False)

    related_order_item_id = Column(Integer, ForeignKey("order_item.id"), nullable=True)
    note = Column(String(255), nullable=True)
    created_by = Column(Integer, ForeignKey("member.id"), nullable=True)

    occurred_at = Column(DateTime, nullable=False)