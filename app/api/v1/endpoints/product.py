from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.product import ProductDetailResponse, ProductListResponse
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


@router.get("/by-code/{product_code}", response_model=ProductDetailResponse)
def read_product_by_code(
    product_code: str,
    db: Session = Depends(get_db),
):
    return ProductService.get_product_detail_by_code(
        db=db,
        product_code=product_code,
    )


@router.get("/{product_id}", response_model=ProductDetailResponse)
def read_product_detail(
    product_id: int,
    db: Session = Depends(get_db),
):
    return ProductService.get_product_detail(
        db=db,
        product_id=product_id,
    )