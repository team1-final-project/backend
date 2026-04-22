from datetime import datetime
from pydantic import BaseModel


class MyOrderSummaryResponse(BaseModel):
    id: int
    order_number: str
    status: str
    total_amount: int
    created_at: datetime | None = None


class MyOrderListResponse(BaseModel):
    items: list[MyOrderSummaryResponse]
    total_count: int