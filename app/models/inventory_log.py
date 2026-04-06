from sqlalchemy import Column, Integer, String
from app.models.base import BaseModel


class InventoryLog(BaseModel):
    __tablename__ = "inventory_logs"   # 실제 DB 테이블명에 맞게 수정

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, nullable=False, index=True)
    quantity = Column(Integer, nullable=False)
    type = Column(String(20), nullable=False)   # IN / OUT
    reason = Column(String(255), nullable=True)