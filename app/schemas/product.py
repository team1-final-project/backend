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