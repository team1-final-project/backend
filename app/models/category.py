from sqlalchemy import Boolean, Column, ForeignKey, Integer, String
from app.models.base import BaseModel


class Category(BaseModel):
    __tablename__ = "category"

    id = Column(Integer, primary_key=True, index=True)
    parent_id = Column(Integer, ForeignKey("category.id"), nullable=True)
    name = Column(String(100), nullable=False)
    level = Column(Integer, nullable=False, default=1)
    full_path = Column(String(255), nullable=True)
    sort_order = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)