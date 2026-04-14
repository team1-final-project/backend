from datetime import date

from pydantic import BaseModel, Field

from app.core.enums import ProductSaleStatus


class AdminProductCreateRequest(BaseModel):
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


class AdminProductCreateResponse(BaseModel):
    id: int
    product_code: str
    product_name: str
    message: str


class ProductImageUploadResponse(BaseModel):
    image_url: str
    public_id: str