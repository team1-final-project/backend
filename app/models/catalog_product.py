from sqlalchemy import Column, DateTime, Integer, String
from app.models.base import BaseModel


class CatalogProduct(BaseModel):
    __tablename__ = "catalog_product"

    id = Column(Integer, primary_key=True, index=True)
    external_catalog_id = Column(String(50), nullable=False, unique=True, index=True)
    catalog_name = Column(String(255), nullable=False)
    source = Column(String(50), nullable=True)
    category_text = Column(String(255), nullable=True)
    pack_count = Column(Integer, nullable=False, default=1)
    unit_sale_price = Column(Integer, nullable=False, default=0)

    current_lowest_price = Column(Integer, nullable=True)
    current_lowest_price_at = Column(DateTime, nullable=True)