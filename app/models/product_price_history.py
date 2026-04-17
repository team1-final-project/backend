from sqlalchemy import Boolean, Column, DateTime, Enum as SqlEnum, ForeignKey, Integer, Numeric, String
from app.core.enums import PriceChangeSource
from app.models.base import BaseModel


class ProductPriceHistory(BaseModel):
    __tablename__ = "product_price_history"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("product.id"), nullable=False, index=True)
    catalog_product_id = Column(Integer, ForeignKey("catalog_product.id"), nullable=True, index=True)

    logged_at = Column(DateTime, nullable=False)

    previous_sale_price = Column(Integer, nullable=True)
    applied_sale_price = Column(Integer, nullable=False)

    sales_qty = Column(Integer, nullable=False, default=0)
    sales_per_hour = Column(Numeric(10, 2), nullable=False, default=0)

    is_lowest_price = Column(Boolean, nullable=False, default=False)
    market_lowest_price = Column(Integer, nullable=True)
    price_gap = Column(Integer, nullable=True)
    price_gap_rate = Column(Numeric(8, 2), nullable=True)

    min_price_limit = Column(Integer, nullable=True)
    max_price_limit = Column(Integer, nullable=True)

    remaining_stock = Column(Integer, nullable=False, default=0)

    my_pack_count = Column(Integer, nullable=True)
    my_unit_sale_price = Column(Integer, nullable=True)

    market_pack_count = Column(Integer, nullable=True)
    market_unit_sale_price = Column(Integer, nullable=True)

    change_source = Column(
        SqlEnum(PriceChangeSource, name="price_change_source_enum"),
        nullable=False,
        default=PriceChangeSource.AI,
    )
    changed_by = Column(Integer, ForeignKey("member.id"), nullable=True)
    note = Column(String(255), nullable=True)