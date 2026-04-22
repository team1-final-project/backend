from __future__ import annotations

from math import ceil
from datetime import datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.enums import ImageType, OrderStatus, PaymentStatus
from app.core.timezone import now_kst
from app.models.category import Category
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.product import Product
from app.models.product_image import ProductImage
from app.models.product_price_history import ProductPriceHistory


class ProductService:
    @staticmethod
    def _leaf_category_name(category: Category | None) -> str:
        if category is None:
            return "미분류"

        raw = (category.full_path or category.name or "").strip()
        if not raw:
            return "미분류"

        if ">" in raw:
            return raw.split(">")[-1].strip()

        if "/" in raw:
            return raw.split("/")[-1].strip()

        return raw

    @staticmethod
    def _get_category_options(db: Session) -> list[dict]:
        categories = (
            db.query(Category)
            .filter(
                Category.level == 2,
                Category.is_active.is_(True),
            )
            .order_by(Category.sort_order.asc(), Category.id.asc())
            .all()
        )

        return [
            {
                "id": category.id,
                "name": ProductService._leaf_category_name(category),
            }
            for category in categories
        ]

    @staticmethod
    def _get_popular_product_ids(db: Session) -> set[int]:
        seven_days_ago = now_kst() - timedelta(days=7)

        rows = (
            db.query(
                OrderItem.product_id.label("product_id"),
                func.sum(OrderItem.quantity).label("total_qty"),
            )
            .join(Order, OrderItem.order_id == Order.id)
            .join(Product, OrderItem.product_id == Product.id)
            .filter(
                Product.deleted_at.is_(None),
                Order.ordered_at >= seven_days_ago,
                or_(
                    Order.payment_status == PaymentStatus.APPROVED,
                    Order.order_status == OrderStatus.PAID,
                ),
            )
            .group_by(OrderItem.product_id)
            .order_by(func.sum(OrderItem.quantity).desc(), OrderItem.product_id.asc())
            .limit(5)
            .all()
        )

        return {int(row.product_id) for row in rows}

    @staticmethod
    def _get_thumbnail_map(db: Session, product_ids: list[int]) -> dict[int, str]:
        if not product_ids:
            return {}

        rows = (
            db.query(ProductImage)
            .filter(
                ProductImage.product_id.in_(product_ids),
                ProductImage.image_type == ImageType.THUMBNAIL,
                ProductImage.is_active.is_(True),
            )
            .order_by(
                ProductImage.product_id.asc(),
                ProductImage.sort_order.asc(),
                ProductImage.id.asc(),
            )
            .all()
        )

        thumbnail_map: dict[int, str] = {}
        for row in rows:
            if row.product_id not in thumbnail_map:
                thumbnail_map[row.product_id] = row.image_url

        return thumbnail_map

    @staticmethod
    def _get_latest_history_map(
        db: Session,
        product_ids: list[int],
    ) -> dict[int, ProductPriceHistory]:
        if not product_ids:
            return {}

        rows = (
            db.query(ProductPriceHistory)
            .filter(ProductPriceHistory.product_id.in_(product_ids))
            .order_by(
                ProductPriceHistory.product_id.asc(),
                ProductPriceHistory.logged_at.desc(),
                ProductPriceHistory.id.desc(),
            )
            .all()
        )

        history_map: dict[int, ProductPriceHistory] = {}
        for row in rows:
            if row.product_id not in history_map:
                history_map[row.product_id] = row

        return history_map

    @staticmethod
    def _build_badge(
        *,
        sale_price: int,
        market_lowest_price: int | None,
        latest_history: ProductPriceHistory | None,
        is_popular: bool,
    ) -> tuple[str | None, str | None, bool, bool, bool]:
        is_lowest_price = False
        is_price_dropped = False

        if market_lowest_price is not None and sale_price < market_lowest_price:
            is_lowest_price = True

        if latest_history is not None:
            previous_sale_price = int(latest_history.previous_sale_price or 0)
            applied_sale_price = int(latest_history.applied_sale_price or 0)
            if previous_sale_price > applied_sale_price:
                is_price_dropped = True

        # 우선순위: 최저가 > 가격 하락중 > 인기 상품
        if is_lowest_price:
            return "최저가", "accent", True, is_price_dropped, is_popular

        if is_price_dropped:
            return "가격 하락중", "accent", False, True, is_popular

        if is_popular:
            return "인기 상품", "default", False, False, True

        return None, None, False, is_price_dropped, is_popular

    @staticmethod
    def _sort_items(items: list[dict], sort: str) -> list[dict]:
        if sort == "priceLow":
            return sorted(items, key=lambda x: (x["price"], -x["id"]))

        if sort == "priceHigh":
            return sorted(items, key=lambda x: (-x["price"], -x["id"]))

        if sort == "ai":
            def badge_priority(item: dict) -> int:
                label = item.get("badge_label")
                if label == "최저가":
                    return 3
                if label == "가격 하락중":
                    return 2
                if label == "인기 상품":
                    return 1
                return 0

            return sorted(
                items,
                key=lambda x: (
                    -badge_priority(x),
                    -int(x.get("is_popular", False)),
                    -x["id"],
                ),
            )

        # latest
        return sorted(items, key=lambda x: -x["id"])

    @staticmethod
    def get_product_list(
        db: Session,
        *,
        keyword: str | None = None,
        category_id: int | None = None,
        sort: str = "latest",
        page: int = 1,
        size: int = 8,
    ) -> dict:
        page = max(page, 1)
        size = max(1, min(size, 100))

        if sort not in {"latest", "priceLow", "priceHigh", "ai"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="지원하지 않는 정렬 방식입니다.",
            )

        query = (
            db.query(Product, Category)
            .join(Category, Product.category_id == Category.id)
            .filter(
                Product.deleted_at.is_(None),
                Product.sale_status == "ON_SALE",
            )
        )

        if category_id is not None:
            query = query.filter(Product.category_id == category_id)

        if keyword:
            normalized_keyword = keyword.strip()
            if normalized_keyword:
                like_keyword = f"%{normalized_keyword}%"
                query = query.filter(
                    or_(
                        Product.product_name.ilike(like_keyword),
                        Product.product_code.ilike(like_keyword),
                        Product.brand_name_snapshot.ilike(like_keyword),
                    )
                )

        rows = query.all()
        products = [product for product, _ in rows]
        product_ids = [product.id for product in products]

        thumbnail_map = ProductService._get_thumbnail_map(db, product_ids)
        latest_history_map = ProductService._get_latest_history_map(db, product_ids)
        popular_product_ids = ProductService._get_popular_product_ids(db)

        items: list[dict] = []
        for product, category in rows:
            latest_history = latest_history_map.get(product.id)

            market_lowest_price = None
            if latest_history and latest_history.market_lowest_price is not None:
                market_lowest_price = int(latest_history.market_lowest_price)
            elif product.catalog_product_id:
                # catalog_product.current_lowest_price는 admin에서도 fallback으로 활용 중
                # 필요 시 추후 join 최적화 가능
                pass

            if market_lowest_price is None and getattr(product, "catalog_product_id", None):
                # 필요 최소 쿼리
                from app.models.catalog_product import CatalogProduct

                catalog = (
                    db.query(CatalogProduct)
                    .filter(CatalogProduct.id == product.catalog_product_id)
                    .first()
                )
                if catalog and catalog.current_lowest_price is not None:
                    market_lowest_price = int(catalog.current_lowest_price)

            sale_price = int(product.sale_price or 0)
            is_popular = product.id in popular_product_ids

            badge_label, badge_tone, is_lowest_price, is_price_dropped, is_popular = (
                ProductService._build_badge(
                    sale_price=sale_price,
                    market_lowest_price=market_lowest_price,
                    latest_history=latest_history,
                    is_popular=is_popular,
                )
            )

            original_price = None
            if market_lowest_price is not None and sale_price < market_lowest_price:
                original_price = market_lowest_price

            items.append(
                {
                    "id": product.id,
                    "product_code": product.product_code,
                    "category_id": product.category_id,
                    "name": product.product_name,
                    "brand": product.brand_name_snapshot,
                    "price": sale_price,
                    "original_price": original_price,
                    "thumbnail_image_url": thumbnail_map.get(product.id),
                    "badge_label": badge_label,
                    "badge_tone": badge_tone,
                    "market_lowest_price": market_lowest_price,
                    "is_lowest_price": is_lowest_price,
                    "is_price_dropped": is_price_dropped,
                    "is_popular": is_popular,
                    "category_name": ProductService._leaf_category_name(category),
                }
            )

        sorted_items = ProductService._sort_items(items, sort)
        total = len(sorted_items)
        total_pages = ceil(total / size) if total > 0 else 1

        start = (page - 1) * size
        paged_items = sorted_items[start:start + size]

        return {
            "categories": ProductService._get_category_options(db),
            "items": paged_items,
            "page": page,
            "size": size,
            "total": total,
            "total_pages": total_pages,
        }