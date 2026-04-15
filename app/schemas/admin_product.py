from datetime import date, datetime

from pydantic import BaseModel, Field

from app.core.enums import ProductSaleStatus


class AdminProductBaseRequest(BaseModel):
    category_id: int
    product_name: str = Field(min_length=1, max_length=255)

    sale_status: ProductSaleStatus

    catalog_external_id: str | None = None
    catalog_name: str | None = None

    sale_price: int = Field(ge=0)
    cost_price: int = Field(ge=0)

    ai_pricing_enabled: bool = False
    min_price_limit: int | None = Field(default=None, ge=0)
    max_price_limit: int | None = Field(default=None, ge=0)

    stock_qty: int = Field(ge=0)
    safety_stock_qty: int = Field(ge=0)
    expiration_date: date | None = None

    description_html: str | None = None

    brand_name: str | None = None
    origin_country: str | None = None

    shipping_fee: int = Field(default=0, ge=0)

    thumbnail_image_url: str | None = None
    detail_image_urls: list[str] = Field(default_factory=list)


class AdminProductCreateRequest(AdminProductBaseRequest):
    pass


class AdminProductUpdateRequest(AdminProductBaseRequest):
    pass


class AdminProductCreateResponse(BaseModel):
    id: int
    product_code: str
    product_name: str
    message: str


class AdminProductUpdateResponse(BaseModel):
    id: int
    product_code: str
    product_name: str
    message: str


class AdminProductDetailResponse(BaseModel):
    product_code: str
    category_id: int
    product_name: str
    sale_status: ProductSaleStatus

    catalog_external_id: str | None = None
    catalog_name: str | None = None

    sale_price: int
    cost_price: int

    ai_pricing_enabled: bool
    min_price_limit: int | None = None
    max_price_limit: int | None = None

    stock_qty: int
    safety_stock_qty: int
    expiration_date: date | None = None

    description_html: str | None = None

    brand_name: str | None = None
    origin_country: str | None = None

    shipping_fee: int

    thumbnail_image_url: str | None = None
    detail_image_urls: list[str] = Field(default_factory=list)


class ProductImageUploadResponse(BaseModel):
    image_url: str
    public_id: str

class CatalogNameResolveResponse(BaseModel):
    external_catalog_id: str
    catalog_name: str | None = None

class AdminPriceSearchItemResponse(BaseModel):
    id: int
    product_code: str
    product_name: str
    sale_status: ProductSaleStatus

    category_id: int
    category_path: str | None = None
    catalog_external_id: str | None = None

    sale_price: int
    ai_pricing_enabled: bool
    min_price_limit: int | None = None
    max_price_limit: int | None = None

    stock_qty: int

    market_lowest_price: int | None = None
    is_lowest_price: bool | None = None
    price_gap: int | None = None
    price_gap_rate: float | None = None

    updated_at: datetime


class AdminPriceSearchListResponse(BaseModel):
    items: list[AdminPriceSearchItemResponse] = Field(default_factory=list)