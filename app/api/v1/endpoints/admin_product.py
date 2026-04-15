from fastapi import APIRouter, Depends, File, UploadFile, Query
from sqlalchemy.orm import Session
from datetime import date

from app.core.database import get_db
from app.core.security import get_current_active_user
from app.models.member import Member
from app.schemas.admin_product import (
    AdminProductCreateRequest,
    AdminProductCreateResponse,
    AdminProductDetailResponse,
    AdminProductUpdateRequest,
    AdminProductUpdateResponse,
    ProductImageUploadResponse,
    CatalogNameResolveResponse,
    AdminProductListResponse,
)
from app.services.admin_product_service import AdminProductService
from app.services.cloudinary_service import CloudinaryService

router = APIRouter(prefix="/admin/products", tags=["admin-products"])

@router.get("", response_model=AdminProductListResponse)
def get_admin_products(
    keyword: str | None = Query(default=None),
    category_id: int | None = Query(default=None),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: Member = Depends(get_current_active_user),
):
    return AdminProductService.get_product_list(
        db=db,
        current_user=current_user,
        keyword=keyword,
        category_id=category_id,
        start_date=start_date,
        end_date=end_date,
        page=page,
        size=size,
    )

@router.post("", response_model=AdminProductCreateResponse, status_code=201)
def create_admin_product(
    payload: AdminProductCreateRequest,
    db: Session = Depends(get_db),
    current_user: Member = Depends(get_current_active_user),
):
    return AdminProductService.create_product(db, current_user, payload)


@router.get("/{product_code}", response_model=AdminProductDetailResponse)
def read_admin_product_detail(
    product_code: str,
    db: Session = Depends(get_db),
    current_user: Member = Depends(get_current_active_user),
):
    return AdminProductService.get_product_detail(db, current_user, product_code)


@router.put("/{product_code}", response_model=AdminProductUpdateResponse)
def update_admin_product(
    product_code: str,
    payload: AdminProductUpdateRequest,
    db: Session = Depends(get_db),
    current_user: Member = Depends(get_current_active_user),
):
    return AdminProductService.update_product(db, current_user, product_code, payload)


@router.post("/images/thumbnail", response_model=ProductImageUploadResponse)
async def upload_product_thumbnail(
    file: UploadFile = File(...),
):
    return CloudinaryService.upload_product_thumbnail(
        file.file,
        file.filename or "thumbnail",
    )


@router.post("/images/detail", response_model=ProductImageUploadResponse)
async def upload_product_detail(
    file: UploadFile = File(...),
):
    return CloudinaryService.upload_product_detail_image(file.file, file.filename or "detail")

@router.get(
    "/catalogs/{external_catalog_id}/name",
    response_model=CatalogNameResolveResponse,
)
def get_catalog_name(
    external_catalog_id: str,
    db: Session = Depends(get_db),
    current_user: Member = Depends(get_current_active_user),
):
    AdminProductService._ensure_admin(current_user)

    catalog_name = AdminProductService.resolve_catalog_name(
        db,
        external_catalog_id,
    )

    return {
        "external_catalog_id": external_catalog_id,
        "catalog_name": catalog_name,
    }
