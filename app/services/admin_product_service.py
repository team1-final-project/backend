import random
import string
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.enums import ImageType, MemberRole
from app.models.brand import Brand
from app.models.catalog_product import CatalogProduct
from app.models.category import Category
from app.models.member import Member
from app.models.product import Product
from app.models.product_image import ProductImage
from app.schemas.admin_product import AdminProductCreateRequest


FIXED_SHIP_FROM_ZIPCODE = "31144"
FIXED_SHIP_FROM_ADDRESS1 = "충청남도 천안시 동남구 대흥로 215 7층"
FIXED_SHIP_FROM_ADDRESS2 = ""


CATEGORY_CODE_PREFIX = {
    "라면": "RM",
    "즉석식품": "RD",
    "카레": "CR",
    "스낵과자": "SN",
    "탄산음료": "SD",
    "소시지": "SG",
}


class AdminProductService:
    @staticmethod
    def _ensure_admin(current_user: Member) -> None:
        if current_user.role != MemberRole.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="관리자만 접근할 수 있습니다.",
            )

    @staticmethod
    def _generate_product_code(db: Session, sub_category_name: str) -> str:
        prefix = CATEGORY_CODE_PREFIX.get(sub_category_name, "PD")

        while True:
            suffix = "".join(
                random.choices(string.ascii_uppercase + string.digits, k=4)
            )
            code = f"{prefix}-{suffix}"

            exists = db.query(Product).filter(Product.product_code == code).first()
            if not exists:
                return code

    @staticmethod
    def _get_or_create_brand(db: Session, brand_name: str | None) -> Brand | None:
        if not brand_name:
            return None

        brand_name = brand_name.strip()
        if not brand_name:
            return None

        brand = db.query(Brand).filter(Brand.name == brand_name).first()
        if brand:
            return brand

        brand = Brand(name=brand_name, is_active=True)
        db.add(brand)
        db.flush()
        return brand

    @staticmethod
    def _get_or_create_catalog_product(
        db: Session,
        external_catalog_id: str | None,
        catalog_name: str | None,
        category_text: str | None,
    ) -> CatalogProduct | None:
        if not external_catalog_id:
            return None

        external_catalog_id = external_catalog_id.strip()
        if not external_catalog_id:
            return None

        catalog = (
            db.query(CatalogProduct)
            .filter(CatalogProduct.external_catalog_id == external_catalog_id)
            .first()
        )
        if catalog:
            if catalog_name:
                catalog.catalog_name = catalog_name
            if category_text:
                catalog.category_text = category_text
            return catalog

        catalog = CatalogProduct(
            external_catalog_id=external_catalog_id,
            catalog_name=catalog_name or external_catalog_id,
            source="NAVER",
            category_text=category_text,
        )
        db.add(catalog)
        db.flush()
        return catalog

    @staticmethod
    def create_product(
        db: Session,
        current_user: Member,
        payload: AdminProductCreateRequest,
    ) -> dict:
        AdminProductService._ensure_admin(current_user)

        category = (
            db.query(Category)
            .filter(Category.id == payload.category_id, Category.is_active.is_(True))
            .first()
        )
        if category is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="카테고리를 찾을 수 없습니다.",
            )

        if category.level != 2:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="상품은 소분류 카테고리에만 등록할 수 있습니다.",
            )

        if (
            payload.ai_pricing_enabled
            and payload.min_price_limit is not None
            and payload.max_price_limit is not None
            and payload.min_price_limit > payload.max_price_limit
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="최소가 제한은 최대가 제한보다 클 수 없습니다.",
            )

        brand = AdminProductService._get_or_create_brand(db, payload.brand_name)

        catalog = AdminProductService._get_or_create_catalog_product(
            db=db,
            external_catalog_id=payload.catalog_external_id,
            catalog_name=payload.catalog_name,
            category_text=category.full_path,
        )

        product_code = AdminProductService._generate_product_code(db, category.name)

        product = Product(
            product_code=product_code,
            product_name=payload.product_name.strip(),
            category_id=category.id,
            brand_id=brand.id if brand else None,
            catalog_product_id=catalog.id if catalog else None,
            origin_country=payload.origin_country,
            description_html=payload.description_html,
            cost_price=payload.cost_price,
            sale_price=payload.sale_price,
            sale_status=payload.sale_status,
            ai_pricing_enabled=payload.ai_pricing_enabled,
            min_price_limit=payload.min_price_limit if payload.ai_pricing_enabled else None,
            max_price_limit=payload.max_price_limit if payload.ai_pricing_enabled else None,
            stock_qty=payload.stock_qty,
            safety_stock_qty=payload.safety_stock_qty,
            expiration_date=payload.expiration_date,
            shipping_fee=payload.shipping_fee,
            brand_name_snapshot=brand.name if brand else payload.brand_name,
            catalog_name_snapshot=payload.catalog_name,
            is_catalog_matched=bool(catalog),
            ship_from_zipcode=FIXED_SHIP_FROM_ZIPCODE,
            ship_from_address1=FIXED_SHIP_FROM_ADDRESS1,
            ship_from_address2=FIXED_SHIP_FROM_ADDRESS2,
        )

        db.add(product)
        db.flush()

        if payload.thumbnail_image_url:
            db.add(
                ProductImage(
                    product_id=product.id,
                    image_type=ImageType.THUMBNAIL,
                    image_url=payload.thumbnail_image_url,
                    sort_order=1,
                    is_active=True,
                )
            )

        for index, image_url in enumerate(payload.detail_image_urls, start=1):
            db.add(
                ProductImage(
                    product_id=product.id,
                    image_type=ImageType.DETAIL,
                    image_url=image_url,
                    sort_order=index,
                    is_active=True,
                )
            )

        db.commit()
        db.refresh(product)

        return {
            "id": product.id,
            "product_code": product.product_code,
            "product_name": product.product_name,
            "message": "상품이 등록되었습니다.",
        }