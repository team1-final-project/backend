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

class AdminSalesSummaryResponse(BaseModel):
    compare_label: str

    gmv: int
    gmv_change_rate: float

    sales_volume: int
    sales_volume_change_rate: float

    contribution_profit: int
    contribution_profit_change_rate: float

    avg_contribution_margin: float
    avg_contribution_margin_change_rate: float


class AdminSalesCategoryTrendItemResponse(BaseModel):
    label: str
    sales: int
    profit: int


class AdminSalesCategoryShareItemResponse(BaseModel):
    name: str
    value: float


class AdminSalesHourlyItemResponse(BaseModel):
    time: str
    lowest_price: int
    my_price: int
    sales: int
    profit: int


class AdminSalesHourlyResponse(BaseModel):
    product_code: str | None = None
    product_name: str | None = None
    items: list[AdminSalesHourlyItemResponse] = Field(default_factory=list)


class AdminBadInventoryItemResponse(BaseModel):
    product_code: str
    product_name: str
    sale_price: int
    stock_days: int
    category: str | None = None


class AdminSalesProductMixItemResponse(BaseModel):
    label: str
    sales: int
    profit: int
    discount: int


class AdminSalesRankingItemResponse(BaseModel):
    rank: int
    product_code: str
    product_name: str
    category: str | None = None

    sales: int | None = None
    avg_sales: int | None = None

    revenue: int | None = None
    avg_revenue: int | None = None

    contribution_profit: int | None = None
    avg_contribution_profit: int | None = None

    compare_rate: float | None = None

    avg_price: int | None = None
    avg_profit: int | None = None
    avg_margin: float | None = None

    original_price: int | None = None
    changed_price: int | None = None
    drop_amount: int | None = None


class AdminSalesRankingResponse(BaseModel):
    compare_label: str
    items: list[AdminSalesRankingItemResponse] = Field(default_factory=list)


class AdminSalesStatResponse(BaseModel):
    mode: str
    period: str

    category_options: list[str] = Field(default_factory=list)

    summary: AdminSalesSummaryResponse
    category_trend: list[AdminSalesCategoryTrendItemResponse] = Field(default_factory=list)
    category_share: list[AdminSalesCategoryShareItemResponse] = Field(default_factory=list)
    hourly: AdminSalesHourlyResponse
    bad_inventory: list[AdminBadInventoryItemResponse] = Field(default_factory=list)
    product_mix: list[AdminSalesProductMixItemResponse] = Field(default_factory=list)
    ranking: AdminSalesRankingResponse