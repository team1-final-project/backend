from datetime import date, datetime

from pydantic import BaseModel, Field


class AdminAiPriceHistoryProductResponse(BaseModel):
    product_id: int
    product_code: str
    product_name: str
    sale_price: int
    pack_count: int
    unit_sale_price: int


class AdminAiPriceHistoryCatalogResponse(BaseModel):
    catalog_product_id: int | None = None
    external_catalog_id: str | None = None
    catalog_name: str | None = None
    market_lowest_price: int | None = None
    pack_count: int | None = None
    unit_sale_price: int | None = None


class AdminAiPriceHistoryItemResponse(BaseModel):
    logged_at: datetime

    previous_sale_price: int | None = None
    applied_sale_price: int

    sales_qty: int
    sales_per_hour: float

    is_lowest_price: bool
    market_lowest_price: int | None = None

    # 화면용 계산값: 1개당 기준 차이
    market_gap_amount: int | None = None
    market_gap_rate: float | None = None

    min_price_limit: int | None = None
    max_price_limit: int | None = None
    remaining_stock: int

    my_pack_count: int | None = None
    my_unit_sale_price: int | None = None
    market_pack_count: int | None = None
    market_unit_sale_price: int | None = None


class AdminAiPriceHistoryDetailResponse(BaseModel):
    keyword: str
    start_date: date | None = None
    end_date: date | None = None

    product: AdminAiPriceHistoryProductResponse
    catalog: AdminAiPriceHistoryCatalogResponse
    histories: list[AdminAiPriceHistoryItemResponse] = Field(default_factory=list)
    history_count: int