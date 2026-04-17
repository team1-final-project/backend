from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_active_user
from app.models.member import Member
from app.schemas.admin_price import AdminAiPriceHistoryDetailResponse
from app.services.admin_price_service import AdminPriceService

router = APIRouter(prefix="/admin/price", tags=["admin-price-history"])


@router.get("/history", response_model=AdminAiPriceHistoryDetailResponse)
def read_admin_ai_price_history_detail(
    keyword: str | None = Query(default=None),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: Member = Depends(get_current_active_user),
):
    return AdminPriceService.get_ai_price_history_detail(
        db=db,
        current_user=current_user,
        keyword=keyword or "",
        start_date=start_date,
        end_date=end_date,
    )