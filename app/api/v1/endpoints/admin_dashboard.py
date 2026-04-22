from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_active_user
from app.models.member import Member
from app.schemas.admin_dashboard import AdminDashboardResponse
from app.services.admin_dashboard_service import AdminDashboardService

router = APIRouter(prefix="/admin/dashboard", tags=["admin-dashboard"])


@router.get("", response_model=AdminDashboardResponse)
def read_admin_dashboard(
    category: str | None = Query(default=None),
    share_category: str | None = Query(default=None),
    contribution_keyword: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: Member = Depends(get_current_active_user),
):
    return AdminDashboardService.get_dashboard(
        db=db,
        current_user=current_user,
        category=category,
        share_category=share_category,
        contribution_keyword=contribution_keyword or "",
    )