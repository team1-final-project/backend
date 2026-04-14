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
from app.schemas.admin_product import (
    AdminProductCreateRequest,
    AdminProductUpdateRequest,
)


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
    def _validate_category_and_price(
        db: Session,
        category_id: int,
        ai_pricing_enabled: bool,
        min_price_limit: int | None,
        max_price_limit: int | None,
    ) -> Category:
        category = (
            db.query(Category)
            .filter(Category.id == category_id, Category.is_active.is_(True))
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
            ai_pricing_enabled
            and min_price_limit is not None
            and max_price_limit is not None
            and min_price_limit > max_price_limit
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="최소가 제한은 최대가 제한보다 클 수 없습니다.",
            )

        return category

    @staticmethod
    def _get_product_by_code(db: Session, product_code: str) -> Product:
        product = (
            db.query(Product)
            .filter(
                Product.product_code == product_code,
                Product.deleted_at.is_(None),
            )
            .first()
        )
        if product is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="상품을 찾을 수 없습니다.",
            )
        return product

    @staticmethod
    def create_product(
        db: Session,
        current_user: Member,
        payload: AdminProductCreateRequest,
    ) -> dict:
        AdminProductService._ensure_admin(current_user)

        category = AdminProductService._validate_category_and_price(
            db=db,
            category_id=payload.category_id,
            ai_pricing_enabled=payload.ai_pricing_enabled,
            min_price_limit=payload.min_price_limit,
            max_price_limit=payload.max_price_limit,
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

    @staticmethod
    def get_product_detail(
        db: Session,
        current_user: Member,
        product_code: str,
    ) -> dict:
        AdminProductService._ensure_admin(current_user)

        product = AdminProductService._get_product_by_code(db, product_code)

        thumbnail = (
            db.query(ProductImage)
            .filter(
                ProductImage.product_id == product.id,
                ProductImage.image_type == ImageType.THUMBNAIL,
                ProductImage.is_active.is_(True),
            )
            .order_by(ProductImage.sort_order.asc(), ProductImage.id.asc())
            .first()
        )

        detail_images = (
            db.query(ProductImage)
            .filter(
                ProductImage.product_id == product.id,
                ProductImage.image_type == ImageType.DETAIL,
                ProductImage.is_active.is_(True),
            )
            .order_by(ProductImage.sort_order.asc(), ProductImage.id.asc())
            .all()
        )

        catalog_external_id = None
        catalog_name = product.catalog_name_snapshot

        if product.catalog_product_id:
            catalog = (
                db.query(CatalogProduct)
                .filter(CatalogProduct.id == product.catalog_product_id)
                .first()
            )
            if catalog:
                catalog_external_id = catalog.external_catalog_id
                catalog_name = catalog.catalog_name

        return {
            "product_code": product.product_code,
            "category_id": product.category_id,
            "product_name": product.product_name,
            "sale_status": product.sale_status,
            "catalog_external_id": catalog_external_id,
            "catalog_name": catalog_name,
            "sale_price": product.sale_price,
            "cost_price": product.cost_price,
            "ai_pricing_enabled": product.ai_pricing_enabled,
            "min_price_limit": product.min_price_limit,
            "max_price_limit": product.max_price_limit,
            "stock_qty": product.stock_qty,
            "safety_stock_qty": product.safety_stock_qty,
            "expiration_date": product.expiration_date,
            "description_html": product.description_html,
            "brand_name": product.brand_name_snapshot,
            "origin_country": product.origin_country,
            "shipping_fee": product.shipping_fee,
            "thumbnail_image_url": thumbnail.image_url if thumbnail else None,
            "detail_image_urls": [image.image_url for image in detail_images],
        }

    @staticmethod
    def update_product(
        db: Session,
        current_user: Member,
        product_code: str,
        payload: AdminProductUpdateRequest,
    ) -> dict:
        AdminProductService._ensure_admin(current_user)

        product = AdminProductService._get_product_by_code(db, product_code)

        category = AdminProductService._validate_category_and_price(
            db=db,
            category_id=payload.category_id,
            ai_pricing_enabled=payload.ai_pricing_enabled,
            min_price_limit=payload.min_price_limit,
            max_price_limit=payload.max_price_limit,
        )

        brand = AdminProductService._get_or_create_brand(db, payload.brand_name)

        catalog = AdminProductService._get_or_create_catalog_product(
            db=db,
            external_catalog_id=payload.catalog_external_id,
            catalog_name=payload.catalog_name,
            category_text=category.full_path,
        )

        product.product_name = payload.product_name.strip()
        product.category_id = category.id
        product.brand_id = brand.id if brand else None
        product.catalog_product_id = catalog.id if catalog else None
        product.origin_country = payload.origin_country
        product.description_html = payload.description_html
        product.cost_price = payload.cost_price
        product.sale_price = payload.sale_price
        product.sale_status = payload.sale_status
        product.ai_pricing_enabled = payload.ai_pricing_enabled
        product.min_price_limit = (
            payload.min_price_limit if payload.ai_pricing_enabled else None
        )
        product.max_price_limit = (
            payload.max_price_limit if payload.ai_pricing_enabled else None
        )
        product.stock_qty = payload.stock_qty
        product.safety_stock_qty = payload.safety_stock_qty
        product.expiration_date = payload.expiration_date
        product.shipping_fee = payload.shipping_fee
        product.brand_name_snapshot = brand.name if brand else payload.brand_name
        product.catalog_name_snapshot = payload.catalog_name
        product.is_catalog_matched = bool(catalog)
        product.ship_from_zipcode = FIXED_SHIP_FROM_ZIPCODE
        product.ship_from_address1 = FIXED_SHIP_FROM_ADDRESS1
        product.ship_from_address2 = FIXED_SHIP_FROM_ADDRESS2

        thumbnail = (
            db.query(ProductImage)
            .filter(
                ProductImage.product_id == product.id,
                ProductImage.image_type == ImageType.THUMBNAIL,
                ProductImage.is_active.is_(True),
            )
            .order_by(ProductImage.sort_order.asc(), ProductImage.id.asc())
            .first()
        )

        if payload.thumbnail_image_url:
            if thumbnail:
                thumbnail.image_url = payload.thumbnail_image_url
            else:
                db.add(
                    ProductImage(
                        product_id=product.id,
                        image_type=ImageType.THUMBNAIL,
                        image_url=payload.thumbnail_image_url,
                        sort_order=1,
                        is_active=True,
                    )
                )

        existing_detail_images = (
            db.query(ProductImage)
            .filter(
                ProductImage.product_id == product.id,
                ProductImage.image_type == ImageType.DETAIL,
                ProductImage.is_active.is_(True),
            )
            .order_by(ProductImage.sort_order.asc(), ProductImage.id.asc())
            .all()
        )

        existing_urls = {image.image_url for image in existing_detail_images}
        next_sort_order = len(existing_detail_images) + 1

        for image_url in payload.detail_image_urls:
            if image_url in existing_urls:
                continue

            db.add(
                ProductImage(
                    product_id=product.id,
                    image_type=ImageType.DETAIL,
                    image_url=image_url,
                    sort_order=next_sort_order,
                    is_active=True,
                )
            )
            next_sort_order += 1

        db.commit()
        db.refresh(product)

        return {
            "id": product.id,
            "product_code": product.product_code,
            "product_name": product.product_name,
            "message": "상품이 수정되었습니다.",
        }