from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_active_user
from app.models.member import Member
from app.schemas.admin_product import (
    AdminProductCreateRequest,
    AdminProductCreateResponse,
    ProductImageUploadResponse,
)
from app.services.admin_product_service import AdminProductService
from app.services.cloudinary_service import CloudinaryService

router = APIRouter(prefix="/admin/products", tags=["admin-products"])


@router.post("", response_model=AdminProductCreateResponse, status_code=201)
def create_admin_product(
    payload: AdminProductCreateRequest,
    db: Session = Depends(get_db),
    current_user: Member = Depends(get_current_active_user),
):
    return AdminProductService.create_product(db, current_user, payload)


@router.post(
    "/images/thumbnail",
    response_model=ProductImageUploadResponse,
)
async def upload_product_thumbnail(
    file: UploadFile = File(...),
):
    return CloudinaryService.upload_product_thumbnail(file.file, file.filename or "thumbnail")


@router.post(
    "/images/detail",
    response_model=ProductImageUploadResponse,
)
async def upload_product_detail(
    file: UploadFile = File(...),
):
    return CloudinaryService.upload_product_detail_image(file.file, file.filename or "detail")