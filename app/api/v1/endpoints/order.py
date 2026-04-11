from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_active_user
from app.models.member import Member
from app.schemas.order import OrderCreateRequest, OrderCreateResponse
from app.services.order_service import OrderService

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("", response_model=OrderCreateResponse, status_code=201)
def create_order(
    payload: OrderCreateRequest,
    db: Session = Depends(get_db),
    current_user: Member = Depends(get_current_active_user),
):
    return OrderService.create_order(db, current_user, payload)