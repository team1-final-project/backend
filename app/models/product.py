from sqlalchemy import Column, Integer, String
from app.models.base import BaseModel


class Product(BaseModel):
    __tablename__ = "products"   # 실제 DB 테이블명에 맞게 수정

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    stock = Column(Integer, nullable=False, default=0)