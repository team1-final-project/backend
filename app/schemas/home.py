from pydantic import BaseModel, Field


class HomeCardItemResponse(BaseModel):
    id: int
    name: str
    thumbnail_image_url: str | None = None
    price: int
    original_price: int | None = None
    discount_rate: int = 0


class HomeRankingDropItemResponse(BaseModel):
    name: str
    drop_amount: int
    drop_rate: int


class HomeRankingDropCategoryResponse(BaseModel):
    category_id: str
    category_name: str
    items: list[HomeRankingDropItemResponse] = Field(default_factory=list)


class HomeRankingSeriesResponse(BaseModel):
    name: str
    color: str
    values: list[int] = Field(default_factory=list)


class HomeRankingGraphResponse(BaseModel):
    labels: list[str] = Field(default_factory=list)
    series: list[HomeRankingSeriesResponse] = Field(default_factory=list)


class HomeRankingProductResponse(BaseModel):
    id: str
    name: str
    current_price: int
    week_compare: int
    two_week_compare: int
    weekly: HomeRankingGraphResponse
    monthly: HomeRankingGraphResponse


class HomeRankingCategoryResponse(BaseModel):
    id: str
    name: str
    products: list[HomeRankingProductResponse] = Field(default_factory=list)


class HomeAiRankingResponse(BaseModel):
    price_drop_top5_by_category: list[HomeRankingDropCategoryResponse] = Field(
        default_factory=list
    )
    categories: list[HomeRankingCategoryResponse] = Field(default_factory=list)


class HomeMainResponse(BaseModel):
    best_items: list[HomeCardItemResponse] = Field(default_factory=list)
    hot_deal_items: list[HomeCardItemResponse] = Field(default_factory=list)
    ai_ranking: HomeAiRankingResponse