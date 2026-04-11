from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_active_user
from app.models.member import Member
from app.schemas.cart import (
    CartCheckAllRequest,
    CartItemCheckedUpdateRequest,
    CartItemQuantityUpdateRequest,
    CartResponse,
)
from app.services.cart_service import CartService

router = APIRouter(prefix="/cart", tags=["cart"])


@router.get("/me", response_model=CartResponse)
def read_my_cart(
    db: Session = Depends(get_db),
    current_user: Member = Depends(get_current_active_user),
):
    return CartService.get_my_cart(db, current_user)


@router.patch("/items/{cart_item_id}/quantity", response_model=CartResponse)
def update_cart_item_quantity(
    cart_item_id: int,
    payload: CartItemQuantityUpdateRequest,
    db: Session = Depends(get_db),
    current_user: Member = Depends(get_current_active_user),
):
    return CartService.update_quantity(db, current_user, cart_item_id, payload.quantity)


@router.patch("/items/{cart_item_id}/checked", response_model=CartResponse)
def update_cart_item_checked(
    cart_item_id: int,
    payload: CartItemCheckedUpdateRequest,
    db: Session = Depends(get_db),
    current_user: Member = Depends(get_current_active_user),
):
    return CartService.update_checked(db, current_user, cart_item_id, payload.checked)


@router.patch("/me/check-all", response_model=CartResponse)
def update_cart_check_all(
    payload: CartCheckAllRequest,
    db: Session = Depends(get_db),
    current_user: Member = Depends(get_current_active_user),
):
    return CartService.check_all(db, current_user, payload.checked)


@router.delete("/items/{cart_item_id}", response_model=CartResponse)
def delete_cart_item(
    cart_item_id: int,
    db: Session = Depends(get_db),
    current_user: Member = Depends(get_current_active_user),
):
    return CartService.delete_item(db, current_user, cart_item_id)