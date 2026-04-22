from typing import List, Optional

from pydantic import BaseModel


class DashboardMetricDetail(BaseModel):
    label: str
    value: int | float


class DashboardMetricCard(BaseModel):
    title: str
    total_label: str
    total_value: int | float
    details: List[DashboardMetricDetail]


class DashboardAiPerformance(BaseModel):
    improvement_profit: int | float
    ai_price_change_count: int
    bad_inventory_sold_sku_count: int
    bad_inventory_sold_qty: int


class DashboardAiTrendPoint(BaseModel):
    label: str
    ai_profit: int | float
    manual_profit: int | float


class DashboardContributionTrendPoint(BaseModel):
    label: str
    lowest_price: int | float
    my_price: int | float
    sales_qty: int | float
    contribution_profit: int | float


class DashboardAdjustmentItem(BaseModel):
    product_code: str
    product_name: str
    current_price: int | float
    market_lowest_price: Optional[int | float] = 0
    ai_recommended_price: Optional[int | float] = 0
    expected_effect: str = "-"
    reason: str = "-"


class DashboardLowProfitItem(BaseModel):
    rank: int
    product_code: str
    product_name: str
    average_profit: int | float
    profit_rate: float
    suggestion: str


class DashboardRankingItem(BaseModel):
    rank: int
    product_code: str
    product_name: str
    sales_qty: int | float


class DashboardSharePoint(BaseModel):
    label: str
    segments: List[int | float]


class AdminDashboardResponse(BaseModel):
    current_time: str
    categories: List[str]

    gmv_card: DashboardMetricCard
    contribution_card: DashboardMetricCard
    ai_performance: DashboardAiPerformance

    ai_strategy_trend: List[DashboardAiTrendPoint]
    contribution_trend: List[DashboardContributionTrendPoint]

    adjustment_items: List[DashboardAdjustmentItem]
    low_profit_items: List[DashboardLowProfitItem]
    ranking_items: List[DashboardRankingItem]

    share_points: List[DashboardSharePoint]

    contribution_product_code: Optional[str] = ""
    contribution_product_name: Optional[str] = ""