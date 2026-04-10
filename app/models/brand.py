from sqlalchemy import Boolean, Column, Integer, String
from app.models.base import BaseModel


class Brand(BaseModel):
    __tablename__ = "brand"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True, index=True)
    is_active = Column(Boolean, nullable=False, default=True)