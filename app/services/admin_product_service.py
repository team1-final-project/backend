import re

from fastapi import HTTPException, status
from sqlalchemy.orm import Session, aliased
from datetime import date, datetime, time, timedelta
from math import ceil
from sqlalchemy import or_, and_, func

from app.core.enums import ImageType, InventoryChangeType, MemberRole
from app.models.brand import Brand
from app.models.catalog_product import CatalogProduct
from app.models.category import Category
from app.models.member import Member
from app.models.product import Product
from app.models.product_image import ProductImage
from app.models.product_price_history import ProductPriceHistory
from app.models.inventory_log import InventoryLog
from app.core.timezone import now_kst
from app.schemas.admin_product import (
    AdminProductCreateRequest,
    AdminProductUpdateRequest,
    AdminLiveInventoryUpdateRequest,
    AdminInboundCreateRequest,
)
from app.services.utils.catalog_pricing_utils import (
    parse_pack_count,
    calculate_unit_sale_price,
)

from app.repositories.catalog_product_repository import (
    get_catalog_product_by_external_catalog_id,
)
from app.services.naver_crawler_service import fetch_catalog_info_by_catalog


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
    def resolve_catalog_name(
        db: Session,
        external_catalog_id: str | None,
    ) -> str | None:
        if not external_catalog_id:
            return None

        external_catalog_id = external_catalog_id.strip()
        if not external_catalog_id:
            return None

        catalog = get_catalog_product_by_external_catalog_id(
            db,
            external_catalog_id,
        )
        if catalog:
            return catalog.catalog_name

        crawl_result = fetch_catalog_info_by_catalog(external_catalog_id)
        if not crawl_result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="카탈로그가 존재하지 않거나 크롤링에 실패했습니다.",
            )

        catalog_name = crawl_result.get("catalog_name")
        lowest_price = crawl_result.get("lowest_price")

        if not catalog_name and lowest_price is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="카탈로그가 존재하지 않거나 크롤링 결과가 올바르지 않습니다.",
            )

        if not catalog_name:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="카탈로그 이름을 찾을 수 없습니다.",
            )

        return catalog_name

    @staticmethod
    def _get_or_create_catalog_product(
        db: Session,
        external_catalog_id: str | None,
        catalog_name: str | None,
        category_text: str | None = None,
    ) -> CatalogProduct | None:
        if not external_catalog_id:
            return None

        external_catalog_id = external_catalog_id.strip()
        if not external_catalog_id:
            return None

        catalog = get_catalog_product_by_external_catalog_id(
            db,
            external_catalog_id,
        )
        if catalog:
            if catalog_name:
                catalog.catalog_name = catalog_name
            if category_text:
                catalog.category_text = category_text
            return catalog

        if not catalog_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="카탈로그 이름이 없어 카탈로그를 생성할 수 없습니다.",
            )

        catalog = CatalogProduct(
            external_catalog_id=external_catalog_id,
            catalog_name=catalog_name,
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
    def _normalize_product_code(product_code: str) -> str:
        code = product_code.strip()
        if not code:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="상품코드는 비어 있을 수 없습니다.",
            )
        return code

    @staticmethod
    def _ensure_product_code_unique(
        db: Session,
        product_code: str,
        exclude_product_id: int | None = None,
    ) -> None:
        query = db.query(Product).filter(
            Product.product_code == product_code,
            Product.deleted_at.is_(None),
        )

        if exclude_product_id is not None:
            query = query.filter(Product.id != exclude_product_id)

        exists = query.first()
        if exists:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="이미 사용 중인 상품코드입니다.",
            )

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

        product_code = AdminProductService._normalize_product_code(payload.product_code)
        AdminProductService._ensure_product_code_unique(db, product_code)

        pack_count = parse_pack_count(payload.product_name)
        unit_sale_price = calculate_unit_sale_price(
            payload.sale_price,
            pack_count,
        )

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
            unit_sale_price=unit_sale_price,
            pack_count=pack_count,
            sale_status=payload.sale_status,
            ai_pricing_enabled=payload.ai_pricing_enabled,
            min_price_limit=(
                payload.min_price_limit if payload.ai_pricing_enabled else None
            ),
            max_price_limit=(
                payload.max_price_limit if payload.ai_pricing_enabled else None
            ),
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

        initial_stock_qty = int(payload.stock_qty or 0)

        if initial_stock_qty > 0:
            inventory_log = InventoryLog(
                product_id=product.id,
                change_type=InventoryChangeType.INBOUND,
                qty_before=0,
                change_qty=initial_stock_qty,
                qty_after=initial_stock_qty,
                related_order_item_id=None,
                note="상품 최초 등록 초기재고",
                created_by=current_user.id,
                occurred_at=now_kst(),
            )
            db.add(inventory_log)

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
    def list_price_search_items(
        db: Session,
        current_user: Member,
    ) -> dict:
        AdminProductService._ensure_admin(current_user)

        latest_history_subquery = (
            db.query(
                ProductPriceHistory.product_id.label("product_id"),
                func.max(ProductPriceHistory.logged_at).label("latest_logged_at"),
            )
            .group_by(ProductPriceHistory.product_id)
            .subquery()
        )

        latest_history = aliased(ProductPriceHistory)

        records = (
            db.query(Product, Category, CatalogProduct, latest_history)
            .outerjoin(Category, Product.category_id == Category.id)
            .outerjoin(CatalogProduct, Product.catalog_product_id == CatalogProduct.id)
            .outerjoin(
                latest_history_subquery,
                Product.id == latest_history_subquery.c.product_id,
            )
            .outerjoin(
                latest_history,
                and_(
                    latest_history.product_id == latest_history_subquery.c.product_id,
                    latest_history.logged_at
                    == latest_history_subquery.c.latest_logged_at,
                ),
            )
            .filter(Product.deleted_at.is_(None))
            .order_by(Product.updated_at.desc(), Product.id.desc())
            .all()
        )

        items = []
        for product, category, catalog, price_history in records:
            market_lowest_price = None
            if price_history and price_history.market_lowest_price is not None:
                market_lowest_price = int(price_history.market_lowest_price)
            elif catalog and catalog.current_lowest_price is not None:
                market_lowest_price = int(catalog.current_lowest_price)

            is_lowest_price = None
            price_gap = None
            price_gap_rate = None

            if market_lowest_price is not None:
                price_gap = int(product.sale_price) - int(market_lowest_price)
                is_lowest_price = int(product.sale_price) <= int(market_lowest_price)

                if int(market_lowest_price) > 0:
                    price_gap_rate = round(
                        (price_gap / int(market_lowest_price)) * 100,
                        1,
                    )

            items.append(
                {
                    "id": product.id,
                    "product_code": product.product_code,
                    "product_name": product.product_name,
                    "sale_status": product.sale_status,
                    "category_id": product.category_id,
                    "category_path": category.full_path if category else None,
                    "catalog_external_id": (
                        catalog.external_catalog_id if catalog else None
                    ),
                    "sale_price": int(product.sale_price),
                    "ai_pricing_enabled": bool(product.ai_pricing_enabled),
                    "min_price_limit": product.min_price_limit,
                    "max_price_limit": product.max_price_limit,
                    "stock_qty": int(product.stock_qty),
                    "market_lowest_price": market_lowest_price,
                    "is_lowest_price": is_lowest_price,
                    "price_gap": price_gap,
                    "price_gap_rate": price_gap_rate,
                    "updated_at": product.updated_at,
                }
            )

        return {"items": items}

    @staticmethod
    def get_matching_summary(
        db: Session,
        current_user: Member,
    ) -> dict:
        AdminProductService._ensure_admin(current_user)

        today = now_kst().date()

        current_end = today
        current_start = today - timedelta(days=6)

        previous_end = current_start - timedelta(days=1)
        previous_start = previous_end - timedelta(days=6)

        def count_summary(start_date: date, end_date: date) -> dict:
            records = (
                db.query(Product, CatalogProduct)
                .outerjoin(CatalogProduct, Product.catalog_product_id == CatalogProduct.id)
                .filter(
                    Product.deleted_at.is_(None),
                    func.date(Product.updated_at) >= start_date,
                    func.date(Product.updated_at) <= end_date,
                )
                .all()
            )

            total_count = len(records)
            matched_count = sum(
                1
                for product, catalog in records
                if catalog is not None and catalog.external_catalog_id
            )
            unmatched_count = total_count - matched_count
            ai_price_count = sum(
                1 for product, catalog in records if bool(product.ai_pricing_enabled)
            )

            return {
                "total_count": total_count,
                "matched_count": matched_count,
                "unmatched_count": unmatched_count,
                "ai_price_count": ai_price_count,
            }

        current_summary = count_summary(current_start, current_end)
        previous_summary = count_summary(previous_start, previous_end)

        return {
            "current_period": {
                "start_date": current_start,
                "end_date": current_end,
            },
            "previous_period": {
                "start_date": previous_start,
                "end_date": previous_end,
            },
            "summary": {
                "total_count": current_summary["total_count"],
                "total_diff": current_summary["total_count"] - previous_summary["total_count"],
                "matched_count": current_summary["matched_count"],
                "matched_diff": current_summary["matched_count"] - previous_summary["matched_count"],
                "unmatched_count": current_summary["unmatched_count"],
                "unmatched_diff": current_summary["unmatched_count"] - previous_summary["unmatched_count"],
                "ai_price_count": current_summary["ai_price_count"],
                "ai_price_diff": current_summary["ai_price_count"] - previous_summary["ai_price_count"],
            },
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

        pack_count = parse_pack_count(payload.product_name)
        unit_sale_price = calculate_unit_sale_price(
            payload.sale_price,
            pack_count,
        )

        product.product_name = payload.product_name.strip()
        product.category_id = category.id
        product.brand_id = brand.id if brand else None
        product.catalog_product_id = catalog.id if catalog else None
        product.origin_country = payload.origin_country
        product.description_html = payload.description_html
        product.cost_price = payload.cost_price
        product.sale_price = payload.sale_price
        product.unit_sale_price = unit_sale_price
        product.pack_count = pack_count
        product.sale_status = payload.sale_status
        product.ai_pricing_enabled = payload.ai_pricing_enabled
        product.min_price_limit = (
            payload.min_price_limit if payload.ai_pricing_enabled else None
        )
        product.max_price_limit = (
            payload.max_price_limit if payload.ai_pricing_enabled else None
        )
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

    @staticmethod
    def get_product_list(
        db: Session,
        current_user: Member,
        keyword: str | None = None,
        category_id: int | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        page: int = 1,
        size: int = 10,
    ) -> dict:
        AdminProductService._ensure_admin(current_user)

        page = max(page, 1)
        size = max(1, min(size, 100))

        base_query = (
            db.query(Product, Category)
            .join(Category, Category.id == Product.category_id)
            .filter(Product.deleted_at.is_(None))
        )

        if category_id is not None:
            base_query = base_query.filter(Product.category_id == category_id)

        if keyword:
            keyword = keyword.strip()
            if keyword:
                like_keyword = f"%{keyword}%"
                base_query = base_query.filter(
                    or_(
                        Product.product_name.ilike(like_keyword),
                        Product.product_code.ilike(like_keyword),
                    )
                )

        if start_date is not None:
            start_datetime = datetime.combine(start_date, time.min)
            base_query = base_query.filter(Product.updated_at >= start_datetime)

        if end_date is not None:
            end_datetime = datetime.combine(end_date + timedelta(days=1), time.min)
            base_query = base_query.filter(Product.updated_at < end_datetime)

        summary_products = [row[0] for row in base_query.all()]

        summary = {
            "total_count": len(summary_products),
            "sale_count": sum(
                1
                for product in summary_products
                if product.sale_status and product.sale_status.value == "ON_SALE"
            ),
            "sold_out_count": sum(
                1
                for product in summary_products
                if product.sale_status and product.sale_status.value == "SOLD_OUT"
            ),
            "ai_enabled_count": sum(
                1 for product in summary_products if bool(product.ai_pricing_enabled)
            ),
        }

        total = summary["total_count"]
        total_pages = ceil(total / size) if total > 0 else 1

        rows = (
            base_query.order_by(Product.updated_at.desc(), Product.id.desc())
            .offset((page - 1) * size)
            .limit(size)
            .all()
        )

        items = []
        for product, category in rows:
            items.append(
                {
                    "id": product.id,
                    "product_code": product.product_code,
                    "product_name": product.product_name,
                    "category_id": product.category_id,
                    "category_name": getattr(category, "full_path", None) or category.name,
                    "sale_price": product.sale_price,
                    "ai_pricing_enabled": bool(product.ai_pricing_enabled),
                    "stock_qty": product.stock_qty,
                    "sale_status": product.sale_status.value if product.sale_status else None,
                    "updated_at": product.updated_at,
                }
            )

        return {
            "items": items,
            "summary": summary,
            "page": page,
            "size": size,
            "total": total,
            "total_pages": total_pages,
        }

    @staticmethod
    def list_live_inventory_items(
        db: Session,
        current_user: Member,
    ) -> dict:
        AdminProductService._ensure_admin(current_user)

        records = (
            db.query(Product, Category)
            .outerjoin(Category, Product.category_id == Category.id)
            .filter(Product.deleted_at.is_(None))
            .order_by(Product.updated_at.desc(), Product.id.desc())
            .all()
        )

        items = []
        for product, category in records:
            total_stock = int(product.stock_qty or 0)
            available_stock = int(product.stock_qty or 0)
            safety_stock_qty = int(product.safety_stock_qty or 0)
            purchase_price = int(product.cost_price or 0)
            asset_amount = available_stock * purchase_price

            if available_stock <= 0:
                inventory_status = "일시품절"
            elif available_stock <= safety_stock_qty:
                inventory_status = "발주권고"
            else:
                inventory_status = "안전재고"

            items.append(
                {
                    "id": product.id,
                    "product_code": product.product_code,
                    "product_name": product.product_name,
                    "total_stock": total_stock,
                    "available_stock": available_stock,
                    "safety_stock_qty": safety_stock_qty,
                    "inventory_status": inventory_status,
                    "purchase_price": purchase_price,
                    "asset_amount": asset_amount,
                    "sale_status": product.sale_status,
                    "category": category.full_path if category else None,
                }
            )

        return {"items": items}

    @staticmethod
    def list_inventory_history_items(
        db: Session,
        current_user: Member,
        keyword: str | None = None,
        change_type: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict:
        AdminProductService._ensure_admin(current_user)

        change_type_label_map = {
            InventoryChangeType.INBOUND: "입고",
            InventoryChangeType.ORDER_OUT: "출고",
        }

        query = (
            db.query(InventoryLog, Product)
            .join(Product, Product.id == InventoryLog.product_id)
            .filter(Product.deleted_at.is_(None))
        )

        if keyword:
            keyword = keyword.strip()
            if keyword:
                like_keyword = f"%{keyword}%"
                query = query.filter(
                    or_(
                        Product.product_name.ilike(like_keyword),
                        Product.product_code.ilike(like_keyword),
                        InventoryLog.note.ilike(like_keyword),
                    )
                )

        if change_type:
            normalized_type = change_type.strip().upper()
            try:
                query = query.filter(
                    InventoryLog.change_type == InventoryChangeType(normalized_type)
                )
            except ValueError:
                pass

        if start_date is not None:
            start_datetime = datetime.combine(start_date, time.min)
            query = query.filter(InventoryLog.occurred_at >= start_datetime)

        if end_date is not None:
            end_datetime = datetime.combine(end_date + timedelta(days=1), time.min)
            query = query.filter(InventoryLog.occurred_at < end_datetime)

        records = (
            query.order_by(InventoryLog.occurred_at.desc(), InventoryLog.id.desc())
            .all()
        )

        items = []
        for inventory_log, product in records:
            items.append(
                {
                    "id": inventory_log.id,
                    "product_id": product.id,
                    "product_code": product.product_code,
                    "product_name": product.product_name,
                    "change_type": inventory_log.change_type,
                    "change_type_label": change_type_label_map.get(
                        inventory_log.change_type,
                        inventory_log.change_type.value,
                    ),
                    "qty_before": int(inventory_log.qty_before or 0),
                    "change_qty": int(inventory_log.change_qty or 0),
                    "qty_after": int(inventory_log.qty_after or 0),
                    "note": inventory_log.note,
                    "occurred_at": inventory_log.occurred_at,
                }
            )

        return {"items": items}


    @staticmethod
    def update_live_inventory_row(
        db: Session,
        current_user: Member,
        product_code: str,
        payload: AdminLiveInventoryUpdateRequest,
    ) -> dict:
        AdminProductService._ensure_admin(current_user)

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

        product.sale_status = payload.sale_status

        db.add(product)
        db.commit()
        db.refresh(product)

        return {
            "id": product.id,
            "product_code": product.product_code,
            "sale_status": product.sale_status,
            "message": "실시간 재고 항목이 수정되었습니다.",
        }

    
    @staticmethod
    def create_inbound(
        db: Session,
        current_user: Member,
        payload: AdminInboundCreateRequest,
    ) -> dict:
        AdminProductService._ensure_admin(current_user)

        product_code = payload.product_code.strip()

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

        qty_before = int(product.stock_qty or 0)
        inbound_qty = int(payload.inbound_qty or 0)
        qty_after = qty_before + inbound_qty

        product.stock_qty = qty_after

        if payload.expiration_date is not None:
            product.expiration_date = payload.expiration_date

        inventory_log = InventoryLog(
            product_id=product.id,
            change_type=InventoryChangeType.INBOUND,
            qty_before=qty_before,
            change_qty=inbound_qty,
            qty_after=qty_after,
            related_order_item_id=None,
            note=payload.note or "관리자 입고 등록",
            created_by=current_user.id,
            occurred_at=now_kst(),
        )

        try:
            db.add(product)
            db.add(inventory_log)
            db.commit()
            db.refresh(product)
        except Exception:
            db.rollback()
            raise

        return {
            "id": product.id,
            "product_code": product.product_code,
            "product_name": product.product_name,
            "qty_before": qty_before,
            "inbound_qty": inbound_qty,
            "qty_after": qty_after,
            "expiration_date": product.expiration_date,
            "message": "입고 등록이 완료되었습니다.",
        }

    @staticmethod
    def update_ai_pricing_enabled(
        db: Session,
        current_user: Member,
        product_id: int,
        ai_pricing_enabled: bool,
    ) -> dict:
        AdminProductService._ensure_admin(current_user)

        product = (
            db.query(Product)
            .filter(
                Product.id == product_id,
                Product.deleted_at.is_(None),
            )
            .first()
        )

        if product is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="상품을 찾을 수 없습니다.",
            )

        product.ai_pricing_enabled = ai_pricing_enabled

        if not ai_pricing_enabled:
            product.min_price_limit = None
            product.max_price_limit = None

        db.add(product)
        db.commit()
        db.refresh(product)

        return {
            "id": product.id,
            "product_code": product.product_code,
            "ai_pricing_enabled": product.ai_pricing_enabled,
            "message": "AI 가격변경 사용 여부가 변경되었습니다.",
        }