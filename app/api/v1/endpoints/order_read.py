from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_active_user
from app.schemas.order_read import MyOrderListResponse
from app.services.order_read_service import get_my_orders

router = APIRouter()


@router.get("/my-orders", response_model=MyOrderListResponse)
def read_my_orders(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_user),
):
    member_id = getattr(current_user, "id", None) or getattr(current_user, "member_id", None)

    if member_id is None:
        raise HTTPException(status_code=401, detail="사용자 정보를 확인할 수 없습니다.")

    return get_my_orders(db, member_id)