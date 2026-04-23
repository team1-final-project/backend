from __future__ import annotations

from datetime import timedelta
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.enums import ProductSaleStatus
from app.core.timezone import now_kst
from app.models.category import Category
from app.models.product import Product
from app.models.product_price_history import ProductPriceHistory
from app.services.product_service import ProductService


class HomeService:
    SERIES_COLORS = ["#1d63ff", "#ff5a5a", "#19b86b", "#f0b64b"]

    @staticmethod
    def _badge_priority(label: str | None) -> int:
        if label == "최저가":
            return 3
        if label == "가격 하락중":
            return 2
        if label == "인기 상품":
            return 1
        return 0

    @staticmethod
    def _normalize_series(values: list[int]) -> list[int]:
        if not values:
            return []

        min_value = min(values)
        max_value = max(values)
        if max_value == min_value:
            return [30 for _ in values]

        return [
            round(6 + ((value - min_value) / (max_value - min_value)) * 54)
            for value in values
        ]

    @staticmethod
    def _month_start(dt):
        return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    @staticmethod
    def _shift_month(dt, offset: int):
        total = (dt.year * 12 + (dt.month - 1)) + offset
        year = total // 12
        month = (total % 12) + 1
        return dt.replace(year=year, month=month, day=1)

    @staticmethod
    def _get_latest_history_in_window(
        db: Session,
        *,
        product_id: int,
        start_at,
        end_at,
    ) -> ProductPriceHistory | None:
        return (
            db.query(ProductPriceHistory)
            .filter(
                ProductPriceHistory.product_id == product_id,
                ProductPriceHistory.logged_at >= start_at,
                ProductPriceHistory.logged_at < end_at,
            )
            .order_by(
                ProductPriceHistory.logged_at.desc(),
                ProductPriceHistory.id.desc(),
            )
            .first()
        )

    @staticmethod
    def _resolve_reference_price(
        *,
        sale_price: int,
        market_lowest_price: int | None,
        latest_history: ProductPriceHistory | None,
    ) -> int | None:
        candidates: list[int] = []

        if latest_history and latest_history.previous_sale_price:
            previous_price = int(latest_history.previous_sale_price)
            if previous_price > sale_price:
                candidates.append(previous_price)

        if market_lowest_price is not None and int(market_lowest_price) > sale_price:
            candidates.append(int(market_lowest_price))

        if not candidates:
            return None

        return max(candidates)

    @staticmethod
    def _build_snapshot_rows(db: Session) -> list[dict]:
        rows = (
            db.query(Product, Category)
            .join(Category, Product.category_id == Category.id)
            .filter(
                Product.deleted_at.is_(None),
                Product.sale_status == ProductSaleStatus.ON_SALE,
            )
            .all()
        )

        products = [product for product, _ in rows]
        product_ids = [product.id for product in products]

        thumbnail_map = ProductService._get_thumbnail_map(db, product_ids)
        latest_history_map = ProductService._get_latest_history_map(db, product_ids)
        popular_product_ids = ProductService._get_popular_product_ids(db)

        snapshots: list[dict] = []

        for product, category in rows:
            latest_history = latest_history_map.get(product.id)
            sale_price = int(product.sale_price or 0)
            market_lowest_price = ProductService._resolve_market_lowest_price(
                db=db,
                product=product,
                latest_history=latest_history,
            )
            is_popular = product.id in popular_product_ids

            badge_label, badge_tone, is_lowest_price, is_price_dropped, _ = (
                ProductService._build_badge(
                    sale_price=sale_price,
                    market_lowest_price=market_lowest_price,
                    latest_history=latest_history,
                    is_popular=is_popular,
                )
            )

            reference_price = HomeService._resolve_reference_price(
                sale_price=sale_price,
                market_lowest_price=market_lowest_price,
                latest_history=latest_history,
            )

            drop_amount = 0
            discount_rate = 0
            if reference_price and reference_price > sale_price:
                drop_amount = int(reference_price - sale_price)
                discount_rate = round((drop_amount / reference_price) * 100)

            snapshots.append(
                {
                    "id": product.id,
                    "name": product.product_name,
                    "category_id": product.category_id,
                    "category_name": ProductService._leaf_category_name(category),
                    "thumbnail_image_url": thumbnail_map.get(product.id),
                    "price": sale_price,
                    "original_price": reference_price,
                    "drop_amount": drop_amount,
                    "discount_rate": discount_rate,
                    "badge_label": badge_label,
                    "badge_tone": badge_tone,
                    "is_lowest_price": is_lowest_price,
                    "is_price_dropped": is_price_dropped,
                    "is_popular": is_popular,
                    "latest_history": latest_history,
                    "product": product,
                }
            )

        return snapshots

    @staticmethod
    def _build_card_item(snapshot: dict) -> dict:
        return {
            "id": snapshot["id"],
            "name": snapshot["name"],
            "thumbnail_image_url": snapshot["thumbnail_image_url"],
            "price": snapshot["price"],
            "original_price": snapshot["original_price"],
            "discount_rate": snapshot["discount_rate"],
        }

    @staticmethod
    def _build_best_items(snapshots: list[dict]) -> list[dict]:
        sorted_rows = sorted(
            snapshots,
            key=lambda row: (
                -int(row["is_popular"]),
                -HomeService._badge_priority(row["badge_label"]),
                -row["discount_rate"],
                -row["id"],
            ),
        )
        return [HomeService._build_card_item(row) for row in sorted_rows[:4]]

    @staticmethod
    def _build_hot_deal_items(snapshots: list[dict]) -> list[dict]:
        discounted = [row for row in snapshots if row["discount_rate"] > 0]
        discounted = sorted(
            discounted,
            key=lambda row: (
                -row["discount_rate"],
                -row["drop_amount"],
                -int(row["is_price_dropped"]),
                -int(row["is_popular"]),
                -row["id"],
            ),
        )

        if len(discounted) < 4:
            existing_ids = {row["id"] for row in discounted}
            fillers = [
                row
                for row in sorted(
                    snapshots,
                    key=lambda r: (
                        -HomeService._badge_priority(r["badge_label"]),
                        -int(r["is_popular"]),
                        -r["id"],
                    ),
                )
                if row["id"] not in existing_ids
            ]
            discounted.extend(fillers[: 4 - len(discounted)])

        return [HomeService._build_card_item(row) for row in discounted[:4]]

    @staticmethod
    def _build_price_drop_top5_by_category(snapshots: list[dict]) -> list[dict]:
        grouped: dict[int, list[dict]] = {}
        for row in snapshots:
            grouped.setdefault(row["category_id"], []).append(row)

        categories: list[dict] = []
        for category_id, items in grouped.items():
            category_name = items[0]["category_name"] if items else "미분류"
            sorted_items = sorted(
                items,
                key=lambda row: (-row["drop_amount"], -row["discount_rate"], -row["id"]),
            )[:5]

            categories.append(
                {
                    "category_id": str(category_id),
                    "category_name": category_name,
                    "items": [
                        {
                            "name": item["name"],
                            "drop_amount": item["drop_amount"],
                            "drop_rate": item["discount_rate"],
                        }
                        for item in sorted_items
                    ],
                }
            )

        return sorted(categories, key=lambda row: row["category_name"])

    @staticmethod
    def _build_weekly_graph(db: Session, product: Product, latest_history: ProductPriceHistory | None):
        now = now_kst()
        labels = ["4주전", "3주전", "2주전", "1주전", "현재"]
        windows = [
            (now - timedelta(days=28), now - timedelta(days=21)),
            (now - timedelta(days=21), now - timedelta(days=14)),
            (now - timedelta(days=14), now - timedelta(days=7)),
            (now - timedelta(days=7), now - timedelta(days=1)),
        ]

        rows: list[ProductPriceHistory | None] = []
        for start_at, end_at in windows:
            rows.append(
                HomeService._get_latest_history_in_window(
                    db,
                    product_id=product.id,
                    start_at=start_at,
                    end_at=end_at,
                )
            )
        rows.append(latest_history)

        current_price = int(product.sale_price or 0)

        price_values: list[int] = []
        lowest_values: list[int] = []
        sales_values: list[int] = []
        stock_values: list[int] = []

        last_price = current_price
        last_lowest = current_price
        last_sales = 0
        last_stock = int(product.stock_qty or 0)

        for row in rows:
            if row:
                if row.applied_sale_price is not None:
                    last_price = int(row.applied_sale_price)
                if row.market_lowest_price is not None:
                    last_lowest = int(row.market_lowest_price)
                last_sales = int(getattr(row, "sales_qty", 0) or 0)
                last_stock = int(getattr(row, "remaining_stock", last_stock) or last_stock)

            price_values.append(last_price)
            lowest_values.append(last_lowest)
            sales_values.append(last_sales)
            stock_values.append(last_stock)

        current_value = price_values[-1]
        week_compare = current_value - price_values[-2] if len(price_values) >= 2 else 0
        two_week_compare = current_value - price_values[-3] if len(price_values) >= 3 else 0

        return {
            "labels": labels,
            "series": [
                {
                    "name": "판매가",
                    "color": HomeService.SERIES_COLORS[0],
                    "values": HomeService._normalize_series(price_values),
                },
                {
                    "name": "최저가",
                    "color": HomeService.SERIES_COLORS[1],
                    "values": HomeService._normalize_series(lowest_values),
                },
                {
                    "name": "판매량",
                    "color": HomeService.SERIES_COLORS[2],
                    "values": HomeService._normalize_series(sales_values),
                },
                {
                    "name": "재고",
                    "color": HomeService.SERIES_COLORS[3],
                    "values": HomeService._normalize_series(stock_values),
                },
            ],
            "week_compare": week_compare,
            "two_week_compare": two_week_compare,
            "current_price": current_value,
        }

    @staticmethod
    def _build_monthly_graph(db: Session, product: Product, latest_history: ProductPriceHistory | None):
        now = HomeService._month_start(now_kst())
        labels: list[str] = []
        rows: list[ProductPriceHistory | None] = []

        for offset in range(-4, 1):
            start_at = HomeService._shift_month(now, offset)
            end_at = HomeService._shift_month(now, offset + 1)
            labels.append(f"{start_at.month}월")
            rows.append(
                HomeService._get_latest_history_in_window(
                    db,
                    product_id=product.id,
                    start_at=start_at,
                    end_at=end_at,
                )
            )

        current_price = int(product.sale_price or 0)

        price_values: list[int] = []
        lowest_values: list[int] = []
        sales_values: list[int] = []
        stock_values: list[int] = []

        last_price = current_price
        last_lowest = current_price
        last_sales = 0
        last_stock = int(product.stock_qty or 0)

        for row in rows:
            if row:
                if row.applied_sale_price is not None:
                    last_price = int(row.applied_sale_price)
                if row.market_lowest_price is not None:
                    last_lowest = int(row.market_lowest_price)
                last_sales = int(getattr(row, "sales_qty", 0) or 0)
                last_stock = int(getattr(row, "remaining_stock", last_stock) or last_stock)

            price_values.append(last_price)
            lowest_values.append(last_lowest)
            sales_values.append(last_sales)
            stock_values.append(last_stock)

        return {
            "labels": labels,
            "series": [
                {
                    "name": "판매가",
                    "color": HomeService.SERIES_COLORS[0],
                    "values": HomeService._normalize_series(price_values),
                },
                {
                    "name": "최저가",
                    "color": HomeService.SERIES_COLORS[1],
                    "values": HomeService._normalize_series(lowest_values),
                },
                {
                    "name": "판매량",
                    "color": HomeService.SERIES_COLORS[2],
                    "values": HomeService._normalize_series(sales_values),
                },
                {
                    "name": "재고",
                    "color": HomeService.SERIES_COLORS[3],
                    "values": HomeService._normalize_series(stock_values),
                },
            ],
        }

    @staticmethod
    def _build_ai_ranking_categories(db: Session, snapshots: list[dict]) -> list[dict]:
        grouped: dict[int, list[dict]] = {}
        for row in snapshots:
            grouped.setdefault(row["category_id"], []).append(row)

        result: list[dict] = []

        for category_id, items in grouped.items():
            sorted_items = sorted(
                items,
                key=lambda row: (
                    -int(row["is_popular"]),
                    -row["discount_rate"],
                    -HomeService._badge_priority(row["badge_label"]),
                    -row["id"],
                ),
            )[:4]

            category_products: list[dict] = []
            for row in sorted_items:
                weekly_graph = HomeService._build_weekly_graph(
                    db=db,
                    product=row["product"],
                    latest_history=row["latest_history"],
                )
                monthly_graph = HomeService._build_monthly_graph(
                    db=db,
                    product=row["product"],
                    latest_history=row["latest_history"],
                )

                category_products.append(
                    {
                        "id": str(row["id"]),
                        "name": row["name"],
                        "current_price": weekly_graph["current_price"],
                        "week_compare": weekly_graph["week_compare"],
                        "two_week_compare": weekly_graph["two_week_compare"],
                        "weekly": {
                            "labels": weekly_graph["labels"],
                            "series": weekly_graph["series"],
                        },
                        "monthly": monthly_graph,
                    }
                )

            result.append(
                {
                    "id": str(category_id),
                    "name": items[0]["category_name"] if items else "미분류",
                    "products": category_products,
                }
            )

        return sorted(result, key=lambda row: row["name"])

    @staticmethod
    def get_home_main(db: Session) -> dict:
        snapshots = HomeService._build_snapshot_rows(db)

        if not snapshots:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="홈 화면에 표시할 상품이 없습니다.",
            )

        return {
            "best_items": HomeService._build_best_items(snapshots),
            "hot_deal_items": HomeService._build_hot_deal_items(snapshots),
            "ai_ranking": {
                "price_drop_top5_by_category": HomeService._build_price_drop_top5_by_category(
                    snapshots
                ),
                "categories": HomeService._build_ai_ranking_categories(db, snapshots),
            },
        }