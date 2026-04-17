from sqlalchemy import Boolean, Column, Date, DateTime, Enum as SqlEnum, ForeignKey, Integer, String, Text
from app.core.enums import ProductSaleStatus
from app.models.base import BaseModel


class Product(BaseModel):
    __tablename__ = "product"

    id = Column(Integer, primary_key=True, index=True)
    product_code = Column(String(50), nullable=False, unique=True, index=True)
    product_name = Column(String(255), nullable=False)

    category_id = Column(Integer, ForeignKey("category.id"), nullable=False, index=True)
    brand_id = Column(Integer, ForeignKey("brand.id"), nullable=True, index=True)
    catalog_product_id = Column(Integer, ForeignKey("catalog_product.id"), nullable=True, index=True)

    origin_country = Column(String(100), nullable=True)
    description_html = Column(Text, nullable=True)

    cost_price = Column(Integer, nullable=False, default=0)
    sale_price = Column(Integer, nullable=False)
    unit_sale_price = Column(Integer, nullable=False, default=0)
    pack_count = Column(Integer, nullable=False, default=1)

    sale_status = Column(
        SqlEnum(ProductSaleStatus, name="product_sale_status_enum"),
        nullable=False,
        default=ProductSaleStatus.READY,
    )
    

    ai_pricing_enabled = Column(Boolean, nullable=False, default=False)
    min_price_limit = Column(Integer, nullable=True)
    max_price_limit = Column(Integer, nullable=True)

    stock_qty = Column(Integer, nullable=False, default=0)
    safety_stock_qty = Column(Integer, nullable=False, default=0)
    expiration_date = Column(Date, nullable=True)

    shipping_fee = Column(Integer, nullable=False, default=0)

    brand_name_snapshot = Column(String(100), nullable=True)
    catalog_name_snapshot = Column(String(255), nullable=True)
    is_catalog_matched = Column(Boolean, nullable=False, default=False)

    ship_from_zipcode = Column(String(10), nullable=True)
    ship_from_address1 = Column(String(255), nullable=True)
    ship_from_address2 = Column(String(255), nullable=True)

    deleted_at = Column(DateTime, nullable=True)