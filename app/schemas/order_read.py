from datetime import datetime
from pydantic import BaseModel


class MyOrderSummaryResponse(BaseModel):
    id: int
    order_number: str
    status: str
    total_product_amount: int
    total_shipping_fee: int
    total_payment_amount: int
    ordered_at: datetime | None = None


class MyOrderListResponse(BaseModel):
    items: list[MyOrderSummaryResponse]
    total_count: int