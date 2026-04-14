import cloudinary
import cloudinary.uploader
from fastapi import HTTPException, status

from app.core.config import settings


class CloudinaryService:
    _configured = False

    @classmethod
    def _configure(cls) -> None:
        if cls._configured:
            return

        if not (
            settings.cloudinary_cloud_name
            and settings.cloudinary_api_key
            and settings.cloudinary_api_secret
        ):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Cloudinary 설정이 누락되었습니다.",
            )

        cloudinary.config(
            cloud_name=settings.cloudinary_cloud_name,
            api_key=settings.cloudinary_api_key,
            api_secret=settings.cloudinary_api_secret,
            secure=True,
        )
        cls._configured = True

    @classmethod
    def upload_product_thumbnail(cls, file_obj, filename: str) -> dict:
        cls._configure()
        try:
            result = cloudinary.uploader.upload(
                file_obj,
                folder=settings.cloudinary_product_folder,
                resource_type="image",
                public_id=None,
                filename_override=filename,
                use_filename=True,
                unique_filename=True,
                overwrite=False,
            )
            return {
                "image_url": result["secure_url"],
                "public_id": result["public_id"],
            }
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"대표이미지 업로드에 실패했습니다. {str(exc)}",
            )

    @classmethod
    def upload_product_detail_image(cls, file_obj, filename: str) -> dict:
        cls._configure()
        try:
            result = cloudinary.uploader.upload(
                file_obj,
                folder=settings.cloudinary_detail_folder,
                resource_type="image",
                public_id=None,
                filename_override=filename,
                use_filename=True,
                unique_filename=True,
                overwrite=False,
            )
            return {
                "image_url": result["secure_url"],
                "public_id": result["public_id"],
            }
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"상세설명 이미지 업로드에 실패했습니다. {str(exc)}",
            )