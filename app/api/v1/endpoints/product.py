from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.product import ProductListResponse
from app.services.product_service import ProductService

router = APIRouter(prefix="/products", tags=["products"])


@router.get("", response_model=ProductListResponse)
def read_products(
    keyword: str | None = Query(default=None),
    category_id: int | None = Query(default=None),
    sort: str = Query(default="latest"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=8, ge=1, le=100),
    db: Session = Depends(get_db),
):
    return ProductService.get_product_list(
        db=db,
        keyword=keyword,
        category_id=category_id,
        sort=sort,
        page=page,
        size=size,
    )