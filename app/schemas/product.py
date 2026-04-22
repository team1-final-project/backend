from pydantic import BaseModel, Field


class ProductListCategoryResponse(BaseModel):
    id: int
    name: str


class ProductListItemResponse(BaseModel):
    id: int
    product_code: str
    category_id: int
    name: str
    brand: str | None = None

    price: int
    original_price: int | None = None
    thumbnail_image_url: str | None = None

    badge_label: str | None = None
    badge_tone: str | None = None

    market_lowest_price: int | None = None
    is_lowest_price: bool = False
    is_price_dropped: bool = False
    is_popular: bool = False


class ProductListResponse(BaseModel):
    categories: list[ProductListCategoryResponse] = Field(default_factory=list)
    items: list[ProductListItemResponse] = Field(default_factory=list)

    page: int
    size: int
    total: int
    total_pages: int


class ProductTrendPointResponse(BaseModel):
    label: str
    value: int


class AILowestPriceItemResponse(BaseModel):
    id: int
    product_code: str
    category_id: int
    name: str
    brand: str | None = None
    thumbnail_image_url: str | None = None

    current_price: int
    lowest_price: int
    drop_amount: int
    drop_rate: int

    ai_recommendation: str
    ai_description: str
    badge_tone: str = "default"

    trend_points: list[ProductTrendPointResponse] = Field(default_factory=list)


class AILowestPriceListResponse(BaseModel):
    categories: list[ProductListCategoryResponse] = Field(default_factory=list)
    items: list[AILowestPriceItemResponse] = Field(default_factory=list)
    total: int


class ProductDetailResponse(BaseModel):
    id: int
    product_code: str
    name: str
    category_name: str
    brand: str | None = None

    price: int
    original_price: int | None = None
    cost_price: int
    recent_lowest_price: int | None = None

    origin_country: str | None = None
    expiration_date: str | None = None
    stock_qty: int
    shipping_fee: int

    thumbnail_image_url: str | None = None
    detail_image_urls: list[str] = Field(default_factory=list)
    description_html: str | None = None

    ai_pricing_enabled: bool = False
    trend_points: list[ProductTrendPointResponse] = Field(default_factory=list)