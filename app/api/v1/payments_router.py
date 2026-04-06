from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.payment import TossConfirmRequest
from app.services.payment_service import PaymentService

router = APIRouter(
    prefix="/api/v1/payments",
    tags=["Payments"]
)


@router.post("/toss/confirm")
def confirm_toss_payment(
    request: TossConfirmRequest,
    db: Session = Depends(get_db),
):
    return PaymentService.confirm_toss_payment(db, request)