from pydantic import BaseModel, Field


class OrderCreateItemRequest(BaseModel):
    product_id: int
    quantity: int = Field(gt=0)
    cart_item_id: int | None = None


class OrderCreateShippingRequest(BaseModel):
    recipient_name: str
    recipient_phone: str
    zipcode: str
    address1: str
    address2: str
    delivery_request: str | None = None


class OrderCreateRequest(BaseModel):
    items: list[OrderCreateItemRequest]
    shipping: OrderCreateShippingRequest


class OrderCreateResponse(BaseModel):
    order_id: int
    order_no: str
    amount: int
    order_name: str