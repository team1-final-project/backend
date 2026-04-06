from pydantic import BaseModel, Field


class TossConfirmRequest(BaseModel):
    paymentKey: str
    orderId: str
    amount: int = Field(..., gt=0)