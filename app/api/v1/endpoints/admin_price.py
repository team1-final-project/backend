from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_active_user
from app.models.member import Member
from app.schemas.admin_price import (
    AdminAiPriceHistoryDetailResponse,
    AdminAiStatResponse,
    AdminSalesStatResponse,
)
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


@router.get("/sales-stat", response_model=AdminSalesStatResponse)
def read_admin_sales_stat(
    mode: str = Query(default="all"),
    period: str = Query(default="weekly"),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    trend_category: str | None = Query(default=None),
    product_mix_category: str | None = Query(default=None),
    hourly_keyword: str | None = Query(default=None),
    hourly_date: date | None = Query(default=None),
    ranking_type: str = Query(default="sales"),
    ranking_category: str | None = Query(default="전체"),
    ranking_period: str = Query(default="weekly"),
    db: Session = Depends(get_db),
    current_user: Member = Depends(get_current_active_user),
):
    return AdminPriceService.get_sales_stat(
        db=db,
        current_user=current_user,
        mode=mode,
        period=period,
        start_date=start_date,
        end_date=end_date,
        trend_category=trend_category,
        product_mix_category=product_mix_category,
        hourly_keyword=hourly_keyword or "",
        hourly_date=hourly_date,
        ranking_type=ranking_type,
        ranking_category=ranking_category or "전체",
        ranking_period=ranking_period,
    )


@router.get("/ai-stat", response_model=AdminAiStatResponse)
def read_admin_ai_stat(
    period: str = Query(default="weekly"),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    simulation_keyword: str | None = Query(default=None),
    simulation_category: str | None = Query(default="전체"),
    simulation_period: str = Query(default="weekly"),
    compare_period: str = Query(default="weekly"),
    performance_category: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: Member = Depends(get_current_active_user),
):
    return AdminPriceService.get_ai_stat(
        db=db,
        current_user=current_user,
        period=period,
        start_date=start_date,
        end_date=end_date,
        simulation_keyword=simulation_keyword or "",
        simulation_category=simulation_category or "전체",
        simulation_period=simulation_period,
        compare_period=compare_period,
        performance_category=performance_category,
    )