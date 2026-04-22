from __future__ import annotations

from math import ceil
from datetime import timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.enums import ImageType, OrderStatus, PaymentStatus, ProductSaleStatus
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

        return sorted(items, key=lambda x: -x["id"])

    @staticmethod
    def _build_ai_lowest_trend_points(
        db: Session,
        product_id: int,
        current_price: int,
    ) -> list[dict]:
        now = now_kst()
        weekly_windows = [
            ("4주전", 28, 21),
            ("3주전", 21, 14),
            ("2주전", 14, 7),
            ("1주전", 7, 0),
        ]

        last_known_price = int(current_price or 0)
        points: list[dict] = []

        for label, start_days_ago, end_days_ago in weekly_windows:
            window_start = now - timedelta(days=start_days_ago)
            window_end = now - timedelta(days=end_days_ago)

            row = (
                db.query(ProductPriceHistory)
                .filter(
                    ProductPriceHistory.product_id == product_id,
                    ProductPriceHistory.logged_at >= window_start,
                    ProductPriceHistory.logged_at < window_end,
                )
                .order_by(
                    ProductPriceHistory.logged_at.desc(),
                    ProductPriceHistory.id.desc(),
                )
                .first()
            )

            if row and row.applied_sale_price is not None:
                last_known_price = int(row.applied_sale_price)

            points.append(
                {
                    "label": label,
                    "value": int(last_known_price),
                }
            )

        return points

    @staticmethod
    def _build_ai_lowest_recommendation(
        *,
        current_price: int,
        lowest_price: int,
        market_lowest_price: int | None,
        trend_points: list[dict],
    ) -> tuple[str, str, str]:
        trend_values = [int(point["value"]) for point in trend_points] or [current_price]
        average_price = sum(trend_values + [current_price]) / max(len(trend_values) + 1, 1)

        if market_lowest_price is not None and current_price <= market_lowest_price:
            return (
                "지금 구매 추천",
                "현재 판매가가 시장 최저가 수준이라 바로 구매해도 괜찮아요.",
                "primary",
            )

        if current_price <= lowest_price:
            return (
                "최저가 근접",
                "최근 4주 기준 가장 낮은 가격 구간에 가까워요.",
                "accent",
            )

        if current_price < average_price:
            return (
                "가격 하락중",
                "최근 4주 평균보다 낮은 흐름이라 조금 더 지켜볼 만해요.",
                "accent",
            )

        return (
            "추가 관찰",
            "최근 가격 흐름이 안정적이라 조금 더 추이를 보는 것도 좋아요.",
            "default",
        )

    @staticmethod
    def _sort_ai_lowest_items(items: list[dict], sort: str) -> list[dict]:
        if sort == "lowest":
            return sorted(items, key=lambda x: (x["lowest_price"], x["current_price"], -x["id"]))

        if sort == "priceLow":
            return sorted(items, key=lambda x: (x["current_price"], -x["id"]))

        if sort == "recommend":
            def recommendation_priority(item: dict) -> int:
                label = item.get("ai_recommendation")
                if label == "지금 구매 추천":
                    return 3
                if label == "최저가 근접":
                    return 2
                if label == "가격 하락중":
                    return 1
                return 0

            return sorted(
                items,
                key=lambda x: (
                    -recommendation_priority(x),
                    -x["drop_amount"],
                    -x["id"],
                ),
            )

        # default: 하락폭순
        return sorted(items, key=lambda x: (-x["drop_amount"], x["lowest_price"], -x["id"]))

    @staticmethod
    def get_ai_lowest_products(
        db: Session,
        *,
        keyword: str | None = None,
        category_id: int | None = None,
        sort: str = "drop",
    ) -> dict:
        if sort not in {"drop", "lowest", "priceLow", "recommend"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="지원하지 않는 정렬 방식입니다.",
            )

        query = (
            db.query(Product, Category)
            .join(Category, Product.category_id == Category.id)
            .filter(
                Product.deleted_at.is_(None),
                Product.sale_status == ProductSaleStatus.ON_SALE,
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

        items: list[dict] = []
        for product, category in rows:
            latest_history = latest_history_map.get(product.id)
            market_lowest_price = ProductService._resolve_market_lowest_price(
                db=db,
                product=product,
                latest_history=latest_history,
            )

            current_price = int(product.sale_price or 0)
            trend_points = ProductService._build_ai_lowest_trend_points(
                db=db,
                product_id=product.id,
                current_price=current_price,
            )
            trend_values = [int(point["value"]) for point in trend_points] or [current_price]

            recent_lowest_price = min(trend_values + [current_price])
            recent_highest_price = max(trend_values + [current_price])

            lowest_price = (
                int(market_lowest_price)
                if market_lowest_price is not None
                else int(recent_lowest_price)
            )

            drop_amount = max(0, int(recent_highest_price) - int(current_price))
            drop_rate = (
                round((drop_amount / int(recent_highest_price)) * 100)
                if int(recent_highest_price) > 0
                else 0
            )

            ai_recommendation, ai_description, badge_tone = (
                ProductService._build_ai_lowest_recommendation(
                    current_price=current_price,
                    lowest_price=lowest_price,
                    market_lowest_price=market_lowest_price,
                    trend_points=trend_points,
                )
            )

            items.append(
                {
                    "id": product.id,
                    "product_code": product.product_code,
                    "category_id": product.category_id,
                    "name": product.product_name,
                    "brand": product.brand_name_snapshot,
                    "thumbnail_image_url": thumbnail_map.get(product.id),
                    "current_price": current_price,
                    "lowest_price": int(lowest_price),
                    "drop_amount": int(drop_amount),
                    "drop_rate": int(drop_rate),
                    "ai_recommendation": ai_recommendation,
                    "ai_description": ai_description,
                    "badge_tone": badge_tone,
                    "trend_points": trend_points,
                }
            )

        sorted_items = ProductService._sort_ai_lowest_items(items, sort)

        return {
            "categories": ProductService._get_category_options(db),
            "items": sorted_items,
            "total": len(sorted_items),
        }



    @staticmethod
    def _resolve_market_lowest_price(
        db: Session,
        product: Product,
        latest_history: ProductPriceHistory | None,
    ) -> int | None:
        if latest_history and latest_history.market_lowest_price is not None:
            return int(latest_history.market_lowest_price)

        if getattr(product, "catalog_product_id", None):
            from app.models.catalog_product import CatalogProduct

            catalog = (
                db.query(CatalogProduct)
                .filter(CatalogProduct.id == product.catalog_product_id)
                .first()
            )
            if catalog and catalog.current_lowest_price is not None:
                return int(catalog.current_lowest_price)

        return None

    @staticmethod
    def _get_product_images(db: Session, product_id: int) -> list[ProductImage]:
        return (
            db.query(ProductImage)
            .filter(
                ProductImage.product_id == product_id,
                ProductImage.is_active.is_(True),
            )
            .order_by(ProductImage.sort_order.asc(), ProductImage.id.asc())
            .all()
        )

    @staticmethod
    def _build_trend_points(db: Session, product_id: int, current_price: int) -> list[dict]:
        history_rows = (
            db.query(ProductPriceHistory)
            .filter(ProductPriceHistory.product_id == product_id)
            .order_by(
                ProductPriceHistory.logged_at.desc(),
                ProductPriceHistory.id.desc(),
            )
            .limit(5)
            .all()
        )

        if not history_rows:
            return [{"label": "현재", "value": int(current_price or 0)}]

        history_rows = list(reversed(history_rows))
        labels_base = ["4주전", "3주전", "2주전", "1주전", "현재"]
        labels = labels_base[-len(history_rows):]

        points: list[dict] = []
        for label, row in zip(labels, history_rows):
            points.append(
                {
                    "label": label,
                    "value": int(row.applied_sale_price or current_price or 0),
                }
            )

        return points

    @staticmethod
    def _get_public_product(
        db: Session,
        *,
        product_id: int | None = None,
        product_code: str | None = None,
    ) -> tuple[Product, Category | None]:
        query = (
            db.query(Product, Category)
            .outerjoin(Category, Product.category_id == Category.id)
            .filter(
                Product.deleted_at.is_(None),
                Product.sale_status == ProductSaleStatus.ON_SALE,
            )
        )

        if product_id is not None:
            query = query.filter(Product.id == product_id)

        if product_code is not None:
            query = query.filter(Product.product_code == product_code)

        row = query.first()
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="상품을 찾을 수 없습니다.",
            )

        return row

    @staticmethod
    def _build_product_detail_response(
        db: Session,
        *,
        product: Product,
        category: Category | None,
    ) -> dict:
        latest_history = (
            db.query(ProductPriceHistory)
            .filter(ProductPriceHistory.product_id == product.id)
            .order_by(
                ProductPriceHistory.logged_at.desc(),
                ProductPriceHistory.id.desc(),
            )
            .first()
        )

        market_lowest_price = ProductService._resolve_market_lowest_price(
            db=db,
            product=product,
            latest_history=latest_history,
        )

        sale_price = int(product.sale_price or 0)
        original_price = None
        if market_lowest_price is not None and sale_price < market_lowest_price:
            original_price = int(market_lowest_price)

        images = ProductService._get_product_images(db, product.id)
        thumbnail_image_url = None
        detail_image_urls: list[str] = []

        for image in images:
            if image.image_type == ImageType.THUMBNAIL:
                if thumbnail_image_url is None:
                    thumbnail_image_url = image.image_url
            else:
                detail_image_urls.append(image.image_url)

        return {
            "id": product.id,
            "product_code": product.product_code,
            "name": product.product_name,
            "category_name": ProductService._leaf_category_name(category),
            "brand": product.brand_name_snapshot,
            "price": sale_price,
            "original_price": original_price,
            "cost_price": int(product.cost_price or 0),
            "recent_lowest_price": market_lowest_price,
            "origin_country": product.origin_country,
            "expiration_date": (
                product.expiration_date.isoformat()
                if product.expiration_date is not None
                else None
            ),
            "stock_qty": int(product.stock_qty or 0),
            "shipping_fee": int(product.shipping_fee or 0),
            "thumbnail_image_url": thumbnail_image_url,
            "detail_image_urls": detail_image_urls,
            "description_html": product.description_html,
            "ai_pricing_enabled": bool(product.ai_pricing_enabled),
            "trend_points": ProductService._build_trend_points(
                db=db,
                product_id=product.id,
                current_price=sale_price,
            ),
        }

    @staticmethod
    def get_product_detail(
        db: Session,
        *,
        product_id: int,
    ) -> dict:
        product, category = ProductService._get_public_product(
            db=db,
            product_id=product_id,
        )
        return ProductService._build_product_detail_response(
            db=db,
            product=product,
            category=category,
        )

    @staticmethod
    def get_product_detail_by_code(
        db: Session,
        *,
        product_code: str,
    ) -> dict:
        product, category = ProductService._get_public_product(
            db=db,
            product_code=product_code,
        )
        return ProductService._build_product_detail_response(
            db=db,
            product=product,
            category=category,
        )

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
                Product.sale_status == ProductSaleStatus.ON_SALE,
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

            market_lowest_price = ProductService._resolve_market_lowest_price(
                db=db,
                product=product,
                latest_history=latest_history,
            )

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
            if market_lowest_price is not None and sale_price < int(market_lowest_price):
                original_price = int(market_lowest_price)

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