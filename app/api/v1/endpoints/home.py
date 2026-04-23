from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.home import HomeMainResponse
from app.services.home_service import HomeService

router = APIRouter(prefix="/home", tags=["home"])


@router.get("", response_model=HomeMainResponse)
def read_home_main(
    db: Session = Depends(get_db),
):
    return HomeService.get_home_main(db=db)