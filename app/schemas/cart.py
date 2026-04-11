from pydantic import BaseModel


class CartItemResponse(BaseModel):
    id: int
    productId: int
    name: str
    price: int
    quantity: int
    image: str | None = None
    checked: bool


class CartResponse(BaseModel):
    cartId: int
    items: list[CartItemResponse]


class CartItemQuantityUpdateRequest(BaseModel):
    quantity: int


class CartItemCheckedUpdateRequest(BaseModel):
    checked: bool


class CartCheckAllRequest(BaseModel):
    checked: bool