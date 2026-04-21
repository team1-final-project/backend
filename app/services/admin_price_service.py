from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.enums import (
    MemberRole,
    OrderStatus,
    PaymentStatus,
    PriceChangeSource,
)
from app.models.catalog_product import CatalogProduct
from app.models.category import Category
from app.models.member import Member
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.product import Product
from app.models.product_price_history import ProductPriceHistory


class AdminPriceService:
    @staticmethod
    def _ensure_admin(current_user: Member) -> None:
        if current_user.role != MemberRole.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="관리자만 접근할 수 있습니다.",
            )

    @staticmethod
    def _validate_date_range(
        start_date: date | None,
        end_date: date | None,
    ) -> None:
        if start_date and end_date and start_date > end_date:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="시작일은 종료일보다 늦을 수 없습니다.",
            )

    @staticmethod
    def _apply_history_date_filters(query, start_date: date | None, end_date: date | None):
        if start_date is not None:
            start_datetime = datetime.combine(start_date, time.min)
            query = query.filter(ProductPriceHistory.logged_at >= start_datetime)

        if end_date is not None:
            end_datetime = datetime.combine(end_date + timedelta(days=1), time.min)
            query = query.filter(ProductPriceHistory.logged_at < end_datetime)

        return query

    @staticmethod
    def _find_target_product(
        db: Session,
        keyword: str,
        start_date: date | None,
        end_date: date | None,
    ) -> Product:
        keyword = (keyword or "").strip()
        if not keyword:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="상품명 또는 상품코드를 입력해주세요.",
            )

        base_query = (
            db.query(
                Product.id.label("product_id"),
                func.max(ProductPriceHistory.logged_at).label("latest_logged_at"),
            )
            .join(ProductPriceHistory, Product.id == ProductPriceHistory.product_id)
            .filter(Product.deleted_at.is_(None))
        )

        base_query = AdminPriceService._apply_history_date_filters(
            base_query,
            start_date,
            end_date,
        )

        exact_row = (
            base_query.filter(Product.product_code == keyword)
            .group_by(Product.id)
            .order_by(func.max(ProductPriceHistory.logged_at).desc(), Product.id.desc())
            .first()
        )

        target_product_id = None
        if exact_row:
            target_product_id = exact_row.product_id
        else:
            like_keyword = f"%{keyword}%"
            matched_row = (
                base_query.filter(
                    or_(
                        Product.product_name.ilike(like_keyword),
                        Product.product_code.ilike(like_keyword),
                    )
                )
                .group_by(Product.id)
                .order_by(func.max(ProductPriceHistory.logged_at).desc(), Product.id.desc())
                .first()
            )
            if matched_row:
                target_product_id = matched_row.product_id

        if target_product_id is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="검색 조건에 맞는 AI 가격변경 이력을 찾을 수 없습니다.",
            )

        product = (
            db.query(Product)
            .filter(
                Product.id == target_product_id,
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
    def _build_catalog_payload(catalog: CatalogProduct | None) -> dict:
        if catalog is None:
            return {
                "catalog_product_id": None,
                "external_catalog_id": None,
                "catalog_name": None,
                "market_lowest_price": None,
                "pack_count": None,
                "unit_sale_price": None,
            }

        return {
            "catalog_product_id": catalog.id,
            "external_catalog_id": catalog.external_catalog_id,
            "catalog_name": catalog.catalog_name,
            "market_lowest_price": (
                int(catalog.current_lowest_price)
                if catalog.current_lowest_price is not None
                else None
            ),
            "pack_count": int(catalog.pack_count or 1),
            "unit_sale_price": int(catalog.unit_sale_price or 0),
        }

    @staticmethod
    def _build_history_item(history: ProductPriceHistory) -> dict:
        my_unit_sale_price = (
            int(history.my_unit_sale_price)
            if history.my_unit_sale_price is not None
            else None
        )
        market_unit_sale_price = (
            int(history.market_unit_sale_price)
            if history.market_unit_sale_price is not None
            else None
        )

        market_gap_amount = None
        market_gap_rate = None

        if (
            my_unit_sale_price is not None
            and market_unit_sale_price is not None
            and market_unit_sale_price > 0
        ):
            market_gap_amount = my_unit_sale_price - market_unit_sale_price
            market_gap_rate = round(
                (market_gap_amount / market_unit_sale_price) * 100,
                1,
            )

        return {
            "logged_at": history.logged_at,
            "previous_sale_price": (
                int(history.previous_sale_price)
                if history.previous_sale_price is not None
                else None
            ),
            "applied_sale_price": int(history.applied_sale_price),
            "sales_qty": int(history.sales_qty or 0),
            "sales_per_hour": float(history.sales_per_hour or 0),
            "is_lowest_price": bool(history.is_lowest_price),
            "market_lowest_price": (
                int(history.market_lowest_price)
                if history.market_lowest_price is not None
                else None
            ),
            "market_gap_amount": market_gap_amount,
            "market_gap_rate": market_gap_rate,
            "min_price_limit": (
                int(history.min_price_limit)
                if history.min_price_limit is not None
                else None
            ),
            "max_price_limit": (
                int(history.max_price_limit)
                if history.max_price_limit is not None
                else None
            ),
            "price_per_time": (
                int(history.price_per_time)
                if history.price_per_time is not None
                else None
            ),
            "remaining_stock": int(history.remaining_stock or 0),
            "my_pack_count": (
                int(history.my_pack_count)
                if history.my_pack_count is not None
                else None
            ),
            "my_unit_sale_price": my_unit_sale_price,
            "market_pack_count": (
                int(history.market_pack_count)
                if history.market_pack_count is not None
                else None
            ),
            "market_unit_sale_price": market_unit_sale_price,
            "reason": history.note,
            "change_source": history.change_source.value if history.change_source else None,
        }

    @staticmethod
    def get_ai_price_history_detail(
        db: Session,
        current_user: Member,
        keyword: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict:
        AdminPriceService._ensure_admin(current_user)
        AdminPriceService._validate_date_range(start_date, end_date)

        product = AdminPriceService._find_target_product(
            db=db,
            keyword=keyword,
            start_date=start_date,
            end_date=end_date,
        )

        catalog = None
        if product.catalog_product_id:
            catalog = (
                db.query(CatalogProduct)
                .filter(CatalogProduct.id == product.catalog_product_id)
                .first()
            )

        history_query = (
            db.query(ProductPriceHistory)
            .filter(ProductPriceHistory.product_id == product.id)
        )
        history_query = AdminPriceService._apply_history_date_filters(
            history_query,
            start_date,
            end_date,
        )

        histories = (
            history_query
            .order_by(ProductPriceHistory.logged_at.desc(), ProductPriceHistory.id.desc())
            .all()
        )

        if not histories:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="조회 기간에 AI 가격변경 이력이 없습니다.",
            )

        history_items = [
            AdminPriceService._build_history_item(history)
            for history in histories
        ]

        return {
            "keyword": keyword.strip(),
            "start_date": start_date,
            "end_date": end_date,
            "product": {
                "product_id": product.id,
                "product_code": product.product_code,
                "product_name": product.product_name,
                "sale_price": int(product.sale_price),
                "pack_count": int(product.pack_count or 1),
                "unit_sale_price": int(product.unit_sale_price or 0),
            },
            "catalog": AdminPriceService._build_catalog_payload(catalog),
            "histories": history_items,
            "history_count": len(history_items),
        }

    @staticmethod
    def _resolve_stat_range(
        start_date: date | None,
        end_date: date | None,
        period: str,
    ) -> tuple[date, date, datetime, datetime, int]:
        default_days = {"daily": 1, "weekly": 7, "monthly": 30}.get(period, 7)

        resolved_end = end_date or datetime.now().date()
        resolved_start = start_date or (resolved_end - timedelta(days=default_days - 1))

        if resolved_start > resolved_end:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="시작일은 종료일보다 늦을 수 없습니다.",
            )

        start_dt = datetime.combine(resolved_start, time.min)
        end_dt = datetime.combine(resolved_end + timedelta(days=1), time.min)
        total_days = max(1, (resolved_end - resolved_start).days + 1)

        return resolved_start, resolved_end, start_dt, end_dt, total_days

    @staticmethod
    def _get_previous_range(
        start_dt: datetime,
        total_days: int,
    ) -> tuple[datetime, datetime]:
        previous_end_dt = start_dt
        previous_start_dt = previous_end_dt - timedelta(days=total_days)
        return previous_start_dt, previous_end_dt

    @staticmethod
    def _safe_change_rate(current_value: float, previous_value: float) -> float:
        if previous_value == 0:
            return 0.0 if current_value == 0 else 100.0
        return round(((current_value - previous_value) / previous_value) * 100, 1)

    @staticmethod
    def _compare_label(period: str) -> str:
        return {
            "daily": "전일 대비",
            "weekly": "전주 대비",
            "monthly": "전월 대비",
        }.get(period, "전주 대비")

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
    def _period_labels(
        period: str,
        start_day: date,
        end_day: date,
    ) -> list[str]:
        if period == "daily":
            return ["0시", "3시", "6시", "9시", "12시", "15시", "18시", "21시"]

        if period == "monthly":
            total_days = max(1, (end_day - start_day).days + 1)
            week_count = max(1, ((total_days - 1) // 7) + 1)
            return [f"{idx}주" for idx in range(1, week_count + 1)]

        total_days = max(1, (end_day - start_day).days + 1)
        if total_days <= 7:
            return [
                (start_day + timedelta(days=idx)).strftime("%a")
                for idx in range(total_days)
            ]

        return [
            (start_day + timedelta(days=idx)).strftime("%m/%d")
            for idx in range(total_days)
        ]

    @staticmethod
    def _bucket_label(dt: datetime, period: str, start_day: date, end_day: date) -> str:
        if period == "daily":
            bucket = (dt.hour // 3) * 3
            if bucket > 21:
                bucket = 21
            return f"{bucket}시"

        if period == "monthly":
            week_index = ((dt.date() - start_day).days // 7) + 1
            return f"{week_index}주"

        total_days = max(1, (end_day - start_day).days + 1)
        if total_days <= 7:
            return dt.strftime("%a")

        return dt.strftime("%m/%d")

    @staticmethod
    def _hourly_labels() -> list[str]:
        return ["0시", "3시", "6시", "9시", "12시", "15시", "18시", "21시", "24시"]

    @staticmethod
    def _get_mode_product_ids(
        db: Session,
        mode: str,
        start_dt: datetime,
        end_dt: datetime,
    ) -> set[int] | None:
        if mode == "all":
            return None

        sources = (
            [PriceChangeSource.AI]
            if mode == "ai"
            else [PriceChangeSource.MANUAL]
        )

        rows = (
            db.query(ProductPriceHistory.product_id)
            .filter(
                ProductPriceHistory.logged_at >= start_dt,
                ProductPriceHistory.logged_at < end_dt,
                ProductPriceHistory.change_source.in_(sources),
            )
            .distinct()
            .all()
        )
        return {row[0] for row in rows}

    @staticmethod
    def _query_order_rows(
        db: Session,
        start_dt: datetime,
        end_dt: datetime,
    ) -> list[dict]:
        rows = (
            db.query(OrderItem, Order, Product, Category)
            .join(Order, OrderItem.order_id == Order.id)
            .join(Product, OrderItem.product_id == Product.id)
            .outerjoin(Category, Product.category_id == Category.id)
            .filter(
                Product.deleted_at.is_(None),
                Order.ordered_at >= start_dt,
                Order.ordered_at < end_dt,
                or_(
                    Order.payment_status == PaymentStatus.APPROVED,
                    Order.order_status == OrderStatus.PAID,
                ),
            )
            .all()
        )

        result = []
        for order_item, order, product, category in rows:
            ordered_at = order.paid_at or order.ordered_at

            result.append(
                {
                    "product_id": product.id,
                    "product_code": product.product_code,
                    "product_name": product.product_name,
                    "category_name": AdminPriceService._leaf_category_name(category),
                    "ordered_at": ordered_at,
                    "unit_price": int(order_item.unit_price or 0),
                    "quantity": int(order_item.quantity or 0),
                    "line_amount": int(order_item.line_amount or 0),
                    "cost_price": int(product.cost_price or 0),
                    "shipping_fee": int(getattr(product, "shipping_fee", 0) or 0),
                    "current_sale_price": int(product.sale_price or 0),
                    "stock_qty": int(product.stock_qty or 0),
                    "safety_stock_qty": int(getattr(product, "safety_stock_qty", 0) or 0),
                    "ai_pricing_enabled": bool(getattr(product, "ai_pricing_enabled", False)),
                }
            )

        return result

    @staticmethod
    def _query_history_rows(
        db: Session,
        start_dt: datetime,
        end_dt: datetime,
    ) -> list[dict]:
        rows = (
            db.query(ProductPriceHistory, Product, Category)
            .join(Product, ProductPriceHistory.product_id == Product.id)
            .outerjoin(Category, Product.category_id == Category.id)
            .filter(
                Product.deleted_at.is_(None),
                ProductPriceHistory.logged_at >= start_dt,
                ProductPriceHistory.logged_at < end_dt,
            )
            .all()
        )

        result = []
        for history, product, category in rows:
            result.append(
                {
                    "product_id": product.id,
                    "product_code": product.product_code,
                    "product_name": product.product_name,
                    "category_name": AdminPriceService._leaf_category_name(category),
                    "logged_at": history.logged_at,
                    "change_source": history.change_source.value if history.change_source else None,
                    "previous_sale_price": int(history.previous_sale_price or 0),
                    "applied_sale_price": int(history.applied_sale_price or 0),
                    "market_lowest_price": int(history.market_lowest_price or 0),
                    "sales_qty": int(history.sales_qty or 0),
                    "remaining_stock": int(history.remaining_stock or 0),
                }
            )
        return result

    @staticmethod
    def _filter_rows_by_mode(rows: list[dict], product_ids: set[int] | None) -> list[dict]:
        if product_ids is None:
            return rows
        if not product_ids:
            return []
        return [row for row in rows if row["product_id"] in product_ids]

    @staticmethod
    def _build_summary(
        current_rows: list[dict],
        previous_rows: list[dict],
    ) -> dict:
        current_gmv = sum(row["line_amount"] for row in current_rows)
        previous_gmv = sum(row["line_amount"] for row in previous_rows)

        current_volume = sum(row["quantity"] for row in current_rows)
        previous_volume = sum(row["quantity"] for row in previous_rows)

        current_profit = sum(
            (row["unit_price"] - row["cost_price"]) * row["quantity"]
            for row in current_rows
        )
        previous_profit = sum(
            (row["unit_price"] - row["cost_price"]) * row["quantity"]
            for row in previous_rows
        )

        current_margin = round((current_profit / current_gmv) * 100, 1) if current_gmv > 0 else 0.0
        previous_margin = round((previous_profit / previous_gmv) * 100, 1) if previous_gmv > 0 else 0.0

        return {
            "gmv": int(current_gmv),
            "gmv_change_rate": AdminPriceService._safe_change_rate(current_gmv, previous_gmv),
            "sales_volume": int(current_volume),
            "sales_volume_change_rate": AdminPriceService._safe_change_rate(current_volume, previous_volume),
            "contribution_profit": int(current_profit),
            "contribution_profit_change_rate": AdminPriceService._safe_change_rate(current_profit, previous_profit),
            "avg_contribution_margin": current_margin,
            "avg_contribution_margin_change_rate": round(current_margin - previous_margin, 1),
        }

    @staticmethod
    def _build_category_trend(
        rows: list[dict],
        selected_category: str,
        period: str,
        start_day: date,
        end_day: date,
    ) -> list[dict]:
        labels = AdminPriceService._period_labels(period, start_day, end_day)
        bucket_map = {
            label: {"label": label, "sales": 0, "profit": 0}
            for label in labels
        }

        for row in rows:
            if row["category_name"] != selected_category:
                continue

            label = AdminPriceService._bucket_label(row["ordered_at"], period, start_day, end_day)
            if label not in bucket_map:
                continue

            bucket_map[label]["sales"] += row["line_amount"]
            bucket_map[label]["profit"] += (row["unit_price"] - row["cost_price"]) * row["quantity"]

        return [bucket_map[label] for label in labels]

    @staticmethod
    def _build_category_share(rows: list[dict]) -> list[dict]:
        revenue_map: dict[str, int] = defaultdict(int)

        for row in rows:
            revenue_map[row["category_name"]] += row["line_amount"]

        total_revenue = sum(revenue_map.values())
        if total_revenue == 0:
            return []

        items = []
        for name, revenue in sorted(revenue_map.items(), key=lambda x: x[1], reverse=True):
            items.append(
                {
                    "name": name,
                    "value": round((revenue / total_revenue) * 100, 1),
                }
            )
        return items

    @staticmethod
    def _find_hourly_target_product(
        history_rows: list[dict],
        keyword: str,
    ) -> dict | None:
        if not history_rows:
            return None

        keyword = (keyword or "").strip().lower()
        if not keyword:
            return history_rows[0]

        exact = next(
            (
                row
                for row in history_rows
                if row["product_code"].lower() == keyword
            ),
            None,
        )
        if exact:
            return exact

        partial = next(
            (
                row
                for row in history_rows
                if keyword in row["product_code"].lower()
                or keyword in row["product_name"].lower()
            ),
            None,
        )
        return partial or history_rows[0]

    @staticmethod
    def _build_hourly(
        db: Session,
        mode: str,
        hourly_keyword: str,
        hourly_date: date | None,
        reference_end_day: date,
    ) -> dict:
        target_day = hourly_date or reference_end_day
        day_start = datetime.combine(target_day, time.min)
        day_end = datetime.combine(target_day + timedelta(days=1), time.min)

        history_rows = AdminPriceService._query_history_rows(db, day_start, day_end)

        if mode == "ai":
            history_rows = [row for row in history_rows if row["change_source"] == PriceChangeSource.AI.value]
        elif mode == "manual":
            history_rows = [row for row in history_rows if row["change_source"] == PriceChangeSource.MANUAL.value]

        history_rows = sorted(history_rows, key=lambda x: x["logged_at"], reverse=True)
        target_product_row = AdminPriceService._find_hourly_target_product(history_rows, hourly_keyword)

        if target_product_row is None:
            return {
                "product_code": None,
                "product_name": None,
                "items": [],
            }

        target_product_id = target_product_row["product_id"]
        product = (
            db.query(Product)
            .filter(Product.id == target_product_id, Product.deleted_at.is_(None))
            .first()
        )
        unit_cost = int(product.cost_price or 0) if product else 0

        labels = AdminPriceService._hourly_labels()
        bucket_map = {
            label: {
                "time": label,
                "lowest_price": 0,
                "my_price": 0,
                "sales": 0,
                "profit": 0,
                "_count": 0,
            }
            for label in labels
        }

        target_histories = [
            row for row in history_rows if row["product_id"] == target_product_id
        ]

        for row in target_histories:
            bucket_hour = (row["logged_at"].hour // 3) * 3
            if bucket_hour > 21:
                bucket_hour = 21

            label = f"{bucket_hour}시"
            bucket = bucket_map[label]
            bucket["lowest_price"] += row["market_lowest_price"]
            bucket["my_price"] += row["applied_sale_price"]
            bucket["sales"] += row["sales_qty"] * row["applied_sale_price"]
            bucket["profit"] += row["sales_qty"] * (row["applied_sale_price"] - unit_cost)
            bucket["_count"] += 1

        for label in labels:
            bucket = bucket_map[label]
            count = bucket.pop("_count")
            if count > 0:
                bucket["lowest_price"] = round(bucket["lowest_price"] / count)
                bucket["my_price"] = round(bucket["my_price"] / count)

        if bucket_map["24시"]["lowest_price"] == 0:
            bucket_map["24시"] = {
                "time": "24시",
                "lowest_price": bucket_map["21시"]["lowest_price"],
                "my_price": bucket_map["21시"]["my_price"],
                "sales": bucket_map["21시"]["sales"],
                "profit": bucket_map["21시"]["profit"],
            }

        return {
            "product_code": target_product_row["product_code"],
            "product_name": target_product_row["product_name"],
            "items": [bucket_map[label] for label in labels],
        }

    @staticmethod
    def _build_bad_inventory(
        db: Session,
        mode_product_ids: set[int] | None,
        current_rows: list[dict],
        total_days: int,
    ) -> list[dict]:
        products = (
            db.query(Product, Category)
            .outerjoin(Category, Product.category_id == Category.id)
            .filter(Product.deleted_at.is_(None))
            .all()
        )

        sales_qty_map: dict[int, int] = defaultdict(int)
        for row in current_rows:
            sales_qty_map[row["product_id"]] += row["quantity"]

        items = []
        for product, category in products:
            if mode_product_ids is not None and product.id not in mode_product_ids:
                continue

            avg_daily_sales = sales_qty_map[product.id] / total_days if total_days > 0 else 0
            if avg_daily_sales <= 0:
                stock_days = int(product.stock_qty or 0)
            else:
                stock_days = int(round((product.stock_qty or 0) / avg_daily_sales))

            items.append(
                {
                    "product_code": product.product_code,
                    "product_name": product.product_name,
                    "sale_price": int(product.sale_price or 0),
                    "stock_days": stock_days,
                    "category": AdminPriceService._leaf_category_name(category),
                }
            )

        items.sort(key=lambda x: x["stock_days"], reverse=True)
        return items[:5]

    @staticmethod
    def _build_product_mix(
        order_rows: list[dict],
        history_rows: list[dict],
        selected_category: str,
        period: str,
        start_day: date,
        end_day: date,
    ) -> list[dict]:
        labels = AdminPriceService._period_labels(period, start_day, end_day)
        bucket_map = {
            label: {"label": label, "sales": 0, "profit": 0, "discount": 0}
            for label in labels
        }

        for row in order_rows:
            if row["category_name"] != selected_category:
                continue

            label = AdminPriceService._bucket_label(row["ordered_at"], period, start_day, end_day)
            if label not in bucket_map:
                continue

            bucket_map[label]["sales"] += row["line_amount"]
            bucket_map[label]["profit"] += (row["unit_price"] - row["cost_price"]) * row["quantity"]

        for row in history_rows:
            if row["category_name"] != selected_category:
                continue

            label = AdminPriceService._bucket_label(row["logged_at"], period, start_day, end_day)
            if label not in bucket_map:
                continue

            discount = max(0, row["previous_sale_price"] - row["applied_sale_price"])
            bucket_map[label]["discount"] += discount

        return [bucket_map[label] for label in labels]

    @staticmethod
    def _build_ranking(
        db: Session,
        mode: str,
        ranking_type: str,
        ranking_category: str,
        ranking_period: str,
        start_date: date | None,
        end_date: date | None,
    ) -> dict:
        current_start_day, current_end_day, current_start_dt, current_end_dt, total_days = (
            AdminPriceService._resolve_stat_range(start_date, end_date, ranking_period)
        )
        previous_start_dt, previous_end_dt = AdminPriceService._get_previous_range(
            current_start_dt,
            total_days,
        )

        current_mode_ids = AdminPriceService._get_mode_product_ids(
            db,
            mode,
            current_start_dt,
            current_end_dt,
        )
        previous_mode_ids = AdminPriceService._get_mode_product_ids(
            db,
            mode,
            previous_start_dt,
            previous_end_dt,
        )

        current_rows = AdminPriceService._filter_rows_by_mode(
            AdminPriceService._query_order_rows(db, current_start_dt, current_end_dt),
            current_mode_ids,
        )
        previous_rows = AdminPriceService._filter_rows_by_mode(
            AdminPriceService._query_order_rows(db, previous_start_dt, previous_end_dt),
            previous_mode_ids,
        )

        if ranking_category != "전체":
            current_rows = [row for row in current_rows if row["category_name"] == ranking_category]
            previous_rows = [row for row in previous_rows if row["category_name"] == ranking_category]

        compare_label = AdminPriceService._compare_label(ranking_period)

        if ranking_type == "drop":
            history_rows = AdminPriceService._query_history_rows(db, current_start_dt, current_end_dt)
            if mode == "ai":
                history_rows = [row for row in history_rows if row["change_source"] == PriceChangeSource.AI.value]
            elif mode == "manual":
                history_rows = [row for row in history_rows if row["change_source"] == PriceChangeSource.MANUAL.value]

            if ranking_category != "전체":
                history_rows = [row for row in history_rows if row["category_name"] == ranking_category]

            grouped: dict[str, dict] = {}
            for row in history_rows:
                drop_amount = max(0, row["previous_sale_price"] - row["applied_sale_price"])
                if drop_amount <= 0:
                    continue

                existing = grouped.get(row["product_code"])
                candidate = {
                    "product_code": row["product_code"],
                    "product_name": row["product_name"],
                    "category": row["category_name"],
                    "original_price": row["previous_sale_price"],
                    "changed_price": row["applied_sale_price"],
                    "drop_amount": drop_amount,
                }
                if existing is None or candidate["drop_amount"] > existing["drop_amount"]:
                    grouped[row["product_code"]] = candidate

            items = sorted(grouped.values(), key=lambda x: x["drop_amount"], reverse=True)[:5]
            ranked_items = []
            for idx, item in enumerate(items, start=1):
                ranked_items.append({"rank": idx, **item})

            return {
                "compare_label": compare_label,
                "items": ranked_items,
            }

        current_grouped: dict[str, dict] = {}
        previous_grouped: dict[str, dict] = {}

        for row in current_rows:
            data = current_grouped.setdefault(
                row["product_code"],
                {
                    "product_code": row["product_code"],
                    "product_name": row["product_name"],
                    "category": row["category_name"],
                    "sales": 0,
                    "revenue": 0,
                    "profit": 0,
                    "quantity": 0,
                },
            )
            data["sales"] += row["quantity"]
            data["revenue"] += row["line_amount"]
            data["profit"] += (row["unit_price"] - row["cost_price"]) * row["quantity"]
            data["quantity"] += row["quantity"]

        for row in previous_rows:
            data = previous_grouped.setdefault(
                row["product_code"],
                {
                    "sales": 0,
                    "revenue": 0,
                    "profit": 0,
                },
            )
            data["sales"] += row["quantity"]
            data["revenue"] += row["line_amount"]
            data["profit"] += (row["unit_price"] - row["cost_price"]) * row["quantity"]

        metric_key = {
            "sales": "sales",
            "revenue": "revenue",
            "profit": "profit",
        }[ranking_type]

        items = []
        for product_code, row in current_grouped.items():
            previous_row = previous_grouped.get(product_code, {})
            quantity = row["quantity"]
            revenue = row["revenue"]
            profit = row["profit"]

            avg_price = round(revenue / quantity) if quantity > 0 else 0
            avg_profit = round(profit / quantity) if quantity > 0 else 0
            avg_margin = round((profit / revenue) * 100, 1) if revenue > 0 else 0.0

            current_metric = row[metric_key]
            previous_metric = previous_row.get(metric_key, 0)

            items.append(
                {
                    "product_code": row["product_code"],
                    "product_name": row["product_name"],
                    "category": row["category"],
                    "sales": int(row["sales"]),
                    "avg_sales": int(round(row["sales"] / total_days)),
                    "revenue": int(row["revenue"]),
                    "avg_revenue": int(round(row["revenue"] / total_days)),
                    "contribution_profit": int(row["profit"]),
                    "avg_contribution_profit": int(round(row["profit"] / total_days)),
                    "compare_rate": AdminPriceService._safe_change_rate(current_metric, previous_metric),
                    "avg_price": int(avg_price),
                    "avg_profit": int(avg_profit),
                    "avg_margin": float(avg_margin),
                    "_metric_value": current_metric,
                }
            )

        items.sort(key=lambda x: x["_metric_value"], reverse=True)
        items = items[:5]

        ranked_items = []
        for idx, item in enumerate(items, start=1):
            item.pop("_metric_value", None)
            ranked_items.append({"rank": idx, **item})

        return {
            "compare_label": compare_label,
            "items": ranked_items,
        }

    @staticmethod
    def get_sales_stat(
        db: Session,
        current_user: Member,
        mode: str,
        period: str,
        start_date: date | None,
        end_date: date | None,
        trend_category: str | None,
        product_mix_category: str | None,
        hourly_keyword: str,
        hourly_date: date | None,
        ranking_type: str,
        ranking_category: str,
        ranking_period: str,
    ) -> dict:
        AdminPriceService._ensure_admin(current_user)

        mode = (mode or "all").strip().lower()
        period = (period or "weekly").strip().lower()
        ranking_type = (ranking_type or "sales").strip().lower()
        ranking_period = (ranking_period or "weekly").strip().lower()
        ranking_category = (ranking_category or "전체").strip()

        if mode not in {"all", "ai", "manual"}:
            raise HTTPException(status_code=400, detail="잘못된 mode 값입니다.")
        if period not in {"daily", "weekly", "monthly"}:
            raise HTTPException(status_code=400, detail="잘못된 period 값입니다.")
        if ranking_type not in {"sales", "revenue", "profit", "drop"}:
            raise HTTPException(status_code=400, detail="잘못된 ranking_type 값입니다.")
        if ranking_period not in {"daily", "weekly", "monthly"}:
            raise HTTPException(status_code=400, detail="잘못된 ranking_period 값입니다.")

        current_start_day, current_end_day, current_start_dt, current_end_dt, total_days = (
            AdminPriceService._resolve_stat_range(start_date, end_date, period)
        )
        previous_start_dt, previous_end_dt = AdminPriceService._get_previous_range(
            current_start_dt,
            total_days,
        )

        category_rows = (
            db.query(Category)
            .filter(Category.level == 2, Category.is_active.is_(True))
            .order_by(Category.sort_order.asc(), Category.id.asc())
            .all()
        )
        category_options = [
            AdminPriceService._leaf_category_name(category)
            for category in category_rows
        ]
        category_options = list(dict.fromkeys(category_options))

        selected_trend_category = (
            trend_category if trend_category in category_options else (category_options[0] if category_options else "라면")
        )
        selected_product_mix_category = (
            product_mix_category
            if product_mix_category in category_options
            else (category_options[0] if category_options else "라면")
        )

        current_mode_ids = AdminPriceService._get_mode_product_ids(
            db,
            mode,
            current_start_dt,
            current_end_dt,
        )
        previous_mode_ids = AdminPriceService._get_mode_product_ids(
            db,
            mode,
            previous_start_dt,
            previous_end_dt,
        )

        current_order_rows = AdminPriceService._filter_rows_by_mode(
            AdminPriceService._query_order_rows(db, current_start_dt, current_end_dt),
            current_mode_ids,
        )
        previous_order_rows = AdminPriceService._filter_rows_by_mode(
            AdminPriceService._query_order_rows(db, previous_start_dt, previous_end_dt),
            previous_mode_ids,
        )

        current_history_rows = AdminPriceService._filter_rows_by_mode(
            AdminPriceService._query_history_rows(db, current_start_dt, current_end_dt),
            current_mode_ids,
        )

        summary = AdminPriceService._build_summary(current_order_rows, previous_order_rows)
        summary["compare_label"] = AdminPriceService._compare_label(period)

        return {
            "mode": mode,
            "period": period,
            "category_options": category_options,
            "summary": summary,
            "category_trend": AdminPriceService._build_category_trend(
                current_order_rows,
                selected_trend_category,
                period,
                current_start_day,
                current_end_day,
            ),
            "category_share": AdminPriceService._build_category_share(current_order_rows),
            "hourly": AdminPriceService._build_hourly(
                db=db,
                mode=mode,
                hourly_keyword=hourly_keyword,
                hourly_date=hourly_date,
                reference_end_day=current_end_day,
            ),
            "bad_inventory": AdminPriceService._build_bad_inventory(
                db=db,
                mode_product_ids=current_mode_ids,
                current_rows=current_order_rows,
                total_days=total_days,
            ),
            "product_mix": AdminPriceService._build_product_mix(
                order_rows=current_order_rows,
                history_rows=current_history_rows,
                selected_category=selected_product_mix_category,
                period=period,
                start_day=current_start_day,
                end_day=current_end_day,
            ),
            "ranking": AdminPriceService._build_ranking(
                db=db,
                mode=mode,
                ranking_type=ranking_type,
                ranking_category=ranking_category,
                ranking_period=ranking_period,
                start_date=start_date,
                end_date=end_date,
            ),
        }

    @staticmethod
    def _query_ai_order_rows(
        db: Session,
        start_dt: datetime,
        end_dt: datetime,
    ) -> list[dict]:
        rows = (
            db.query(OrderItem, Order, Product, Category)
            .join(Order, OrderItem.order_id == Order.id)
            .join(Product, OrderItem.product_id == Product.id)
            .outerjoin(Category, Product.category_id == Category.id)
            .filter(
                Product.deleted_at.is_(None),
                Product.ai_pricing_enabled.is_(True),
                Order.ordered_at >= start_dt,
                Order.ordered_at < end_dt,
                or_(
                    Order.payment_status == PaymentStatus.APPROVED,
                    Order.order_status == OrderStatus.PAID,
                ),
            )
            .all()
        )

        items = []
        for order_item, order, product, category in rows:
            ordered_at = order.paid_at or order.ordered_at
            items.append(
                {
                    "product_id": product.id,
                    "product_code": product.product_code,
                    "product_name": product.product_name,
                    "category_name": AdminPriceService._leaf_category_name(category),
                    "category_path": category.full_path if category and category.full_path else (category.name if category else "미분류"),
                    "ordered_at": ordered_at,
                    "unit_price": int(order_item.unit_price or 0),
                    "quantity": int(order_item.quantity or 0),
                    "line_amount": int(order_item.line_amount or 0),
                    "cost_price": int(product.cost_price or 0),
                    "stock_qty": int(product.stock_qty or 0),
                    "safety_stock_qty": int(product.safety_stock_qty or 0),
                    "min_price_limit": int(product.min_price_limit) if product.min_price_limit is not None else None,
                    "max_price_limit": int(product.max_price_limit) if product.max_price_limit is not None else None,
                }
            )
        return items

    @staticmethod
    def _query_ai_history_rows(
        db: Session,
        start_dt: datetime | None = None,
        end_dt: datetime | None = None,
    ) -> list[dict]:
        query = (
            db.query(ProductPriceHistory, Product, Category)
            .join(Product, ProductPriceHistory.product_id == Product.id)
            .outerjoin(Category, Product.category_id == Category.id)
            .filter(
                Product.deleted_at.is_(None),
                Product.ai_pricing_enabled.is_(True),
                ProductPriceHistory.change_source == PriceChangeSource.AI,
            )
        )

        if start_dt is not None:
            query = query.filter(ProductPriceHistory.logged_at >= start_dt)
        if end_dt is not None:
            query = query.filter(ProductPriceHistory.logged_at < end_dt)

        rows = query.all()

        items = []
        for history, product, category in rows:
            previous_sale_price = int(history.previous_sale_price or 0)
            applied_sale_price = int(history.applied_sale_price or 0)
            remaining_stock = int(history.remaining_stock or 0)
            safety_stock_qty = int(product.safety_stock_qty or 0)

            items.append(
                {
                    "product_id": product.id,
                    "product_code": product.product_code,
                    "product_name": product.product_name,
                    "category_name": AdminPriceService._leaf_category_name(category),
                    "category_path": category.full_path if category and category.full_path else (category.name if category else "미분류"),
                    "logged_at": history.logged_at,
                    "previous_sale_price": previous_sale_price,
                    "applied_sale_price": applied_sale_price,
                    "market_lowest_price": int(history.market_lowest_price or 0),
                    "price_gap": int(history.price_gap or 0),
                    "sales_qty": int(history.sales_qty or 0),
                    "remaining_stock": remaining_stock,
                    "safety_stock_qty": safety_stock_qty,
                    "min_price_limit": int(history.min_price_limit) if history.min_price_limit is not None else None,
                    "price_per_time": int(history.price_per_time) if history.price_per_time is not None else None,
                    "note": history.note,
                    "direction": (
                        "down"
                        if applied_sale_price < previous_sale_price
                        else "up"
                        if applied_sale_price > previous_sale_price
                        else "flat"
                    ),
                }
            )

        return items

    @staticmethod
    def _build_ai_history_reason_text(
        *,
        previous_sale_price: int,
        applied_sale_price: int,
        remaining_stock: int,
        safety_stock_qty: int,
    ) -> str:
        if safety_stock_qty > 0 and remaining_stock >= safety_stock_qty * 2:
            if applied_sale_price <= previous_sale_price:
                return "악성재고 가격인하"

        if safety_stock_qty > 0 and remaining_stock <= safety_stock_qty:
            if applied_sale_price >= previous_sale_price:
                return "품절임박 가격인상"

        if applied_sale_price < previous_sale_price:
            return "최저가변동 가격인하"

        return "최저가변동 가격인상"


    @staticmethod
    def _build_ai_strategy_reason_text(
        *,
        applied_sale_price: int,
        market_lowest_price: int,
        min_price_limit: int | None,
        price_per_time: int | None,
    ) -> str | None:
        applied_sale_price = int(applied_sale_price or 0)
        market_lowest_price = int(market_lowest_price or 0)
        min_price_limit = int(min_price_limit) if min_price_limit is not None else None
        step_limit = int(price_per_time or 0)

        # 1. 최소가 제한에 이미 닿았거나 거의 근접한 경우
        if min_price_limit is not None:
            if applied_sale_price <= min_price_limit:
                return "최저가 제한"

            if step_limit > 0 and applied_sale_price - min_price_limit <= step_limit:
                return "최저가 제한"

        # 2. 시장 최저가보다 아직 비싸면 회당 조정가 제한 대상으로 본다
        if market_lowest_price > 0 and applied_sale_price > market_lowest_price:
            return "회당 조정가 제한"

        return None

    @staticmethod
    def _manual_projection_factors(category_name: str) -> tuple[float, float, float]:
        mapping = {
            "라면": (0.94, 0.89, 0.93),
            "소시지": (0.91, 0.87, 0.90),
            "스낵과자": (0.93, 0.90, 0.92),
            "즉석식품": (0.92, 0.88, 0.91),
            "카레": (0.94, 0.90, 0.93),
            "탄산음료": (0.95, 0.91, 0.94),
        }
        return mapping.get(category_name, (0.93, 0.89, 0.92))

    @staticmethod
    def _project_manual_metrics_from_row(row: dict) -> dict:
        revenue_factor, profit_factor, sales_factor = AdminPriceService._manual_projection_factors(
            row["category_name"]
        )
        variation_seed = ((row["ordered_at"].day + row["product_id"]) % 5) - 2
        variation = variation_seed * 0.01

        ai_profit = (row["unit_price"] - row["cost_price"]) * row["quantity"]

        projected_revenue = int(round(row["line_amount"] * max(0.72, revenue_factor + variation)))
        projected_profit = int(round(ai_profit * max(0.65, profit_factor + variation)))
        projected_sales = max(1, int(round(row["quantity"] * max(0.72, sales_factor + (variation / 2)))))

        return {
            "revenue": projected_revenue,
            "profit": projected_profit,
            "sales": projected_sales,
        }

    @staticmethod
    def _build_ai_summary(
        current_order_rows: list[dict],
        previous_order_rows: list[dict],
        current_history_rows: list[dict],
        previous_history_rows: list[dict],
        period: str,
    ) -> dict:
        current_revenue = sum(row["line_amount"] for row in current_order_rows)
        previous_revenue = sum(row["line_amount"] for row in previous_order_rows)

        current_profit = sum(
            (row["unit_price"] - row["cost_price"]) * row["quantity"]
            for row in current_order_rows
        )
        previous_profit = sum(
            (row["unit_price"] - row["cost_price"]) * row["quantity"]
            for row in previous_order_rows
        )

        current_margin = round((current_profit / current_revenue) * 100, 1) if current_revenue > 0 else 0.0

        current_lowest_share = round(
            (
                sum(1 for row in current_history_rows if row["applied_sale_price"] <= row["market_lowest_price"])
                / len(current_history_rows)
            ) * 100,
            1,
        ) if current_history_rows else 0.0

        previous_lowest_share = round(
            (
                sum(1 for row in previous_history_rows if row["applied_sale_price"] <= row["market_lowest_price"])
                / len(previous_history_rows)
            ) * 100,
            1,
        ) if previous_history_rows else 0.0

        current_change_count = len(current_history_rows)
        previous_change_count = len(previous_history_rows)

        return {
            "compare_label": AdminPriceService._compare_label(period),
            "ai_revenue": int(current_revenue),
            "ai_revenue_change_rate": AdminPriceService._safe_change_rate(current_revenue, previous_revenue),
            "ai_profit": int(current_profit),
            "ai_profit_margin": float(current_margin),
            "ai_profit_change_rate": AdminPriceService._safe_change_rate(current_profit, previous_profit),
            "lowest_price_share": float(current_lowest_share),
            "lowest_price_share_change_rate": AdminPriceService._safe_change_rate(current_lowest_share, previous_lowest_share),
            "price_change_count": int(current_change_count),
            "price_change_count_change_rate": AdminPriceService._safe_change_rate(current_change_count, previous_change_count),
        }

    @staticmethod
    def _build_ai_simulation_items(
        rows: list[dict],
        period: str,
        start_day: date,
        end_day: date,
    ) -> list[dict]:
        labels = AdminPriceService._period_labels(period, start_day, end_day)
        bucket_map = {
            label: {
                "label": label,
                "ai_revenue": 0,
                "ai_profit": 0,
                "manual_revenue": 0,
                "manual_profit": 0,
            }
            for label in labels
        }

        for row in rows:
            label = AdminPriceService._bucket_label(row["ordered_at"], period, start_day, end_day)
            if label not in bucket_map:
                continue

            ai_profit = (row["unit_price"] - row["cost_price"]) * row["quantity"]
            manual = AdminPriceService._project_manual_metrics_from_row(row)

            bucket_map[label]["ai_revenue"] += row["line_amount"]
            bucket_map[label]["ai_profit"] += ai_profit
            bucket_map[label]["manual_revenue"] += manual["revenue"]
            bucket_map[label]["manual_profit"] += manual["profit"]

        return [bucket_map[label] for label in labels]

    @staticmethod
    def _build_ai_category_comparison(
        current_rows: list[dict],
        previous_rows: list[dict],
        category_options: list[str],
        compare_period: str,
    ) -> dict:
        items = []

        for category_name in category_options:
            current_category_rows = [row for row in current_rows if row["category_name"] == category_name]
            previous_category_rows = [row for row in previous_rows if row["category_name"] == category_name]

            current_revenue = sum(row["line_amount"] for row in current_category_rows)
            current_profit = sum(
                (row["unit_price"] - row["cost_price"]) * row["quantity"]
                for row in current_category_rows
            )
            current_sales = sum(row["quantity"] for row in current_category_rows)
            current_margin = round((current_profit / current_revenue) * 100, 1) if current_revenue > 0 else 0.0

            previous_revenue = sum(row["line_amount"] for row in previous_category_rows)
            previous_profit = sum(
                (row["unit_price"] - row["cost_price"]) * row["quantity"]
                for row in previous_category_rows
            )
            previous_sales = sum(row["quantity"] for row in previous_category_rows)
            previous_margin = round((previous_profit / previous_revenue) * 100, 1) if previous_revenue > 0 else 0.0

            manual_revenue = 0
            manual_profit = 0
            manual_sales = 0

            for row in current_category_rows:
                projected = AdminPriceService._project_manual_metrics_from_row(row)
                manual_revenue += projected["revenue"]
                manual_profit += projected["profit"]
                manual_sales += projected["sales"]

            manual_margin = round((manual_profit / manual_revenue) * 100, 1) if manual_revenue > 0 else 0.0

            items.append(
                {
                    "category": category_name,
                    "performance": {
                        "revenue": int(current_revenue),
                        "profit": int(current_profit),
                        "sales": int(current_sales),
                        "margin": float(current_margin),
                        "revenue_change": AdminPriceService._safe_change_rate(current_revenue, previous_revenue),
                        "profit_change": AdminPriceService._safe_change_rate(current_profit, previous_profit),
                        "sales_change": AdminPriceService._safe_change_rate(current_sales, previous_sales),
                        "margin_change": round(current_margin - previous_margin, 1),
                    },
                    "ai": {
                        "revenue": int(current_revenue),
                        "profit": int(current_profit),
                        "sales": int(current_sales),
                        "margin": float(current_margin),
                    },
                    "manual": {
                        "revenue": int(manual_revenue),
                        "profit": int(manual_profit),
                        "sales": int(manual_sales),
                        "margin": float(manual_margin),
                    },
                }
            )

        return {
            "compare_label": AdminPriceService._compare_label(compare_period),
            "items": items,
        }

    @staticmethod
    def _build_ai_history_section(history_rows: list[dict]) -> dict:
        sorted_rows = sorted(history_rows, key=lambda x: x["logged_at"], reverse=True)

        items = []
        for index, row in enumerate(sorted_rows[:5], start=1):
            reason = AdminPriceService._build_ai_history_reason_text(
                previous_sale_price=row["previous_sale_price"],
                applied_sale_price=row["applied_sale_price"],
                remaining_stock=row["remaining_stock"],
                safety_stock_qty=row["safety_stock_qty"],
            )

            items.append(
                {
                    "rank": index,
                    "occurred_at": row["logged_at"],
                    "product_code": row["product_code"],
                    "product_name": row["product_name"],
                    "reason": reason,
                    "direction": row["direction"],
                }
            )

        return {"items": items}

    @staticmethod
    def _build_ai_strategy_section(
        current_order_rows: list[dict],
        previous_order_rows: list[dict],
        current_history_rows: list[dict],
        period: str,
    ) -> dict:
        previous_grouped = defaultdict(lambda: {"revenue": 0})

        for row in previous_order_rows:
            previous_grouped[row["product_code"]]["revenue"] += row["line_amount"]

        order_grouped = {}
        for row in current_order_rows:
            target = order_grouped.setdefault(
                row["product_code"],
                {
                    "product_code": row["product_code"],
                    "product_name": row["product_name"],
                    "category": row["category_path"],
                    "revenue": 0,
                    "profit": 0,
                    "sales_qty": 0,
                    "avg_price_total": 0,
                    "avg_price_count": 0,
                    "stock": row["stock_qty"],
                },
            )
            target["revenue"] += row["line_amount"]
            target["profit"] += (row["unit_price"] - row["cost_price"]) * row["quantity"]
            target["sales_qty"] += row["quantity"]
            target["avg_price_total"] += row["unit_price"]
            target["avg_price_count"] += 1
            target["stock"] = row["stock_qty"]

        latest_history_map = {}
        for row in sorted(current_history_rows, key=lambda x: x["logged_at"], reverse=True):
            if row["product_code"] not in latest_history_map:
                latest_history_map[row["product_code"]] = row

        items = []

        for product_code, latest_history in latest_history_map.items():
            reason = AdminPriceService._build_ai_strategy_reason_text(
                applied_sale_price=latest_history["applied_sale_price"],
                market_lowest_price=latest_history["market_lowest_price"],
                min_price_limit=latest_history["min_price_limit"],
                price_per_time=latest_history["price_per_time"],
            )

            if not reason:
                continue

            order_info = order_grouped.get(
                product_code,
                {
                    "product_code": latest_history["product_code"],
                    "product_name": latest_history["product_name"],
                    "category": latest_history["category_path"],
                    "revenue": 0,
                    "profit": 0,
                    "sales_qty": int(latest_history["sales_qty"] or 0),
                    "avg_price_total": int(latest_history["applied_sale_price"] or 0),
                    "avg_price_count": 1,
                    "stock": int(latest_history["remaining_stock"] or 0),
                },
            )

            previous_revenue = previous_grouped[product_code]["revenue"]
            compare_rate = AdminPriceService._safe_change_rate(
                order_info["revenue"],
                previous_revenue,
            )

            sale_price = (
                round(order_info["avg_price_total"] / order_info["avg_price_count"])
                if order_info["avg_price_count"] > 0
                else int(latest_history["applied_sale_price"] or 0)
            )

            avg_profit = (
                round(order_info["profit"] / order_info["sales_qty"])
                if order_info["sales_qty"] > 0
                else 0
            )

            margin = (
                round((order_info["profit"] / order_info["revenue"]) * 100, 1)
                if order_info["revenue"] > 0
                else 0.0
            )

            items.append(
                {
                    "product_code": order_info["product_code"],
                    "product_name": order_info["product_name"],
                    "reason": reason,
                    "sales_qty": int(order_info["sales_qty"]),
                    "stock": int(order_info["stock"]),
                    "compare_rate": float(compare_rate),
                    "sale_price": int(sale_price),
                    "profit": int(avg_profit),
                    "margin": float(margin),
                    "category": order_info["category"],
                }
            )

        reason_priority = {
            "최저가 제한": 0,
            "회당 조정가 제한": 1,
        }

        items = sorted(
            items,
            key=lambda x: (
                reason_priority.get(x["reason"], 99),
                x["compare_rate"],
                x["stock"],
            ),
        )[:5]

        for idx, item in enumerate(items, start=1):
            item["rank"] = idx

        return {
            "compare_label": AdminPriceService._compare_label(period),
            "items": items,
        }

    @staticmethod
    def get_ai_stat(
        db: Session,
        current_user: Member,
        period: str,
        start_date: date | None,
        end_date: date | None,
        simulation_keyword: str,
        simulation_category: str,
        simulation_period: str,
        compare_period: str,
        performance_category: str | None,
    ) -> dict:
        AdminPriceService._ensure_admin(current_user)

        period = (period or "weekly").strip().lower()
        simulation_period = (simulation_period or "weekly").strip().lower()
        compare_period = (compare_period or "weekly").strip().lower()
        simulation_category = (simulation_category or "전체").strip()

        if period not in {"daily", "weekly", "monthly"}:
            raise HTTPException(status_code=400, detail="잘못된 period 값입니다.")
        if simulation_period not in {"daily", "weekly", "monthly"}:
            raise HTTPException(status_code=400, detail="잘못된 simulation_period 값입니다.")
        if compare_period not in {"daily", "weekly", "monthly"}:
            raise HTTPException(status_code=400, detail="잘못된 compare_period 값입니다.")

        current_start_day, current_end_day, current_start_dt, current_end_dt, total_days = (
            AdminPriceService._resolve_stat_range(start_date, end_date, period)
        )
        previous_start_dt, previous_end_dt = AdminPriceService._get_previous_range(
            current_start_dt,
            total_days,
        )

        simulation_start_day, simulation_end_day, simulation_start_dt, simulation_end_dt, _ = (
            AdminPriceService._resolve_stat_range(start_date, end_date, simulation_period)
        )

        compare_start_day, compare_end_day, compare_start_dt, compare_end_dt, compare_days = (
            AdminPriceService._resolve_stat_range(start_date, end_date, compare_period)
        )
        compare_previous_start_dt, compare_previous_end_dt = AdminPriceService._get_previous_range(
            compare_start_dt,
            compare_days,
        )

        category_rows = (
            db.query(Category)
            .filter(Category.level == 2, Category.is_active.is_(True))
            .order_by(Category.sort_order.asc(), Category.id.asc())
            .all()
        )
        category_options = [AdminPriceService._leaf_category_name(category) for category in category_rows]
        category_options = list(dict.fromkeys(category_options))

        selected_performance_category = (
            performance_category
            if performance_category and performance_category in category_options
            else (category_options[0] if category_options else "라면")
        )

        current_order_rows = AdminPriceService._query_ai_order_rows(db, current_start_dt, current_end_dt)
        previous_order_rows = AdminPriceService._query_ai_order_rows(db, previous_start_dt, previous_end_dt)
        current_history_rows = AdminPriceService._query_ai_history_rows(db, current_start_dt, current_end_dt)
        previous_history_rows = AdminPriceService._query_ai_history_rows(db, previous_start_dt, previous_end_dt)

        simulation_order_rows = AdminPriceService._query_ai_order_rows(db, simulation_start_dt, simulation_end_dt)

        keyword = (simulation_keyword or "").strip().lower()
        if simulation_category != "전체":
            simulation_order_rows = [
                row for row in simulation_order_rows if row["category_name"] == simulation_category
            ]
        if keyword:
            simulation_order_rows = [
                row for row in simulation_order_rows
                if keyword in row["product_code"].lower() or keyword in row["product_name"].lower()
            ]

        compare_current_rows = AdminPriceService._query_ai_order_rows(db, compare_start_dt, compare_end_dt)
        compare_previous_rows = AdminPriceService._query_ai_order_rows(db, compare_previous_start_dt, compare_previous_end_dt)

        performance_rows = [
            row for row in current_order_rows if row["category_name"] == selected_performance_category
        ]

        return {
            "period": period,
            "category_options": category_options,
            "summary": AdminPriceService._build_ai_summary(
                current_order_rows=current_order_rows,
                previous_order_rows=previous_order_rows,
                current_history_rows=current_history_rows,
                previous_history_rows=previous_history_rows,
                period=period,
            ),
            "simulation": {
                "items": AdminPriceService._build_ai_simulation_items(
                    rows=simulation_order_rows,
                    period=simulation_period,
                    start_day=simulation_start_day,
                    end_day=simulation_end_day,
                )
            },
            "category_comparison": AdminPriceService._build_ai_category_comparison(
                current_rows=compare_current_rows,
                previous_rows=compare_previous_rows,
                category_options=category_options,
                compare_period=compare_period,
            ),
            "performance": {
                "items": AdminPriceService._build_ai_simulation_items(
                    rows=performance_rows,
                    period=period,
                    start_day=current_start_day,
                    end_day=current_end_day,
                )
            },
            "history": AdminPriceService._build_ai_history_section(current_history_rows),
            "strategy": AdminPriceService._build_ai_strategy_section(
                current_order_rows=current_order_rows,
                previous_order_rows=previous_order_rows,
                current_history_rows=current_history_rows,
                period=period,
            ),
        }

    @staticmethod
    def _dashboard_contribution_profit(row: dict) -> int:
        return int(
            (row["unit_price"] - row["cost_price"] - row.get("shipping_fee", 0))
            * row["quantity"]
        )

    @staticmethod
    def _dashboard_today_range() -> tuple[date, date, datetime, datetime]:
        today = datetime.now().date()
        start_dt = datetime.combine(today, time.min)
        end_dt = datetime.combine(today + timedelta(days=1), time.min)
        return today, today, start_dt, end_dt

    @staticmethod
    def _dashboard_last7_range() -> tuple[date, date, datetime, datetime]:
        end_day = datetime.now().date()
        start_day = end_day - timedelta(days=6)
        start_dt = datetime.combine(start_day, time.min)
        end_dt = datetime.combine(end_day + timedelta(days=1), time.min)
        return start_day, end_day, start_dt, end_dt

    @staticmethod
    def _dashboard_categories(db: Session) -> list[str]:
        rows = (
            db.query(Category)
            .filter(Category.level == 2, Category.is_active.is_(True))
            .order_by(Category.sort_order.asc(), Category.id.asc())
            .all()
        )

        names = ["전체"]
        for row in rows:
            name = AdminPriceService._leaf_category_name(row)
            if name not in names:
                names.append(name)
        return names

    @staticmethod
    def _filter_category_rows(rows: list[dict], category: str | None) -> list[dict]:
        selected = (category or "전체").strip()
        if not selected or selected == "전체":
            return rows
        return [row for row in rows if row["category_name"] == selected]

    @staticmethod
    def _build_dashboard_metric_card(
        title: str,
        total_label: str,
        total_value: int,
        ai_label: str,
        ai_value: int,
        manual_label: str,
        manual_value: int,
    ) -> dict:
        return {
            "title": title,
            "total_label": total_label,
            "total_value": int(total_value),
            "details": [
                {"label": ai_label, "value": int(ai_value)},
                {"label": manual_label, "value": int(manual_value)},
            ],
        }

    @staticmethod
    def _build_dashboard_ai_performance(
        db: Session,
        today_rows: list[dict],
        today_start_dt: datetime,
        today_end_dt: datetime,
    ) -> dict:
        ai_rows = [row for row in today_rows if row.get("ai_pricing_enabled")]

        ai_price_change_count = (
            db.query(func.count(ProductPriceHistory.id))
            .filter(
                ProductPriceHistory.logged_at >= today_start_dt,
                ProductPriceHistory.logged_at < today_end_dt,
                ProductPriceHistory.change_source == PriceChangeSource.AI,
            )
            .scalar()
            or 0
        )

        bad_inventory_sold = {}
        bad_inventory_qty = 0

        for row in ai_rows:
            stock_qty = int(row.get("stock_qty") or 0)
            safety_stock_qty = int(row.get("safety_stock_qty") or 0)

            if stock_qty > max(safety_stock_qty, 30):
                bad_inventory_sold[row["product_code"]] = True
                bad_inventory_qty += int(row["quantity"] or 0)

        improvement_profit = sum(
            AdminPriceService._dashboard_contribution_profit(row)
            for row in ai_rows
        )

        return {
            "improvement_profit": int(improvement_profit),
            "ai_price_change_count": int(ai_price_change_count),
            "bad_inventory_sold_sku_count": len(bad_inventory_sold),
            "bad_inventory_sold_qty": int(bad_inventory_qty),
        }

    @staticmethod
    def _build_dashboard_ai_strategy_trend(
        rows: list[dict],
        selected_category: str,
    ) -> list[dict]:
        filtered_rows = AdminPriceService._filter_category_rows(rows, selected_category)

        day_map: dict[date, dict] = {}
        for idx in range(7):
            day = datetime.now().date() - timedelta(days=6 - idx)
            day_map[day] = {
                "label": day.strftime("%a"),
                "ai_profit": 0,
                "manual_profit": 0,
            }

        for row in filtered_rows:
            row_day = row["ordered_at"].date()
            if row_day not in day_map:
                continue

            profit = AdminPriceService._dashboard_contribution_profit(row)
            if row.get("ai_pricing_enabled"):
                day_map[row_day]["ai_profit"] += profit
            else:
                day_map[row_day]["manual_profit"] += profit

        ordered_days = sorted(day_map.keys())
        return [day_map[day] for day in ordered_days]

    @staticmethod
    def _find_contribution_target_product(
        today_order_rows: list[dict],
        keyword: str,
    ) -> tuple[str | None, str | None]:
        keyword = (keyword or "").strip().lower()
        if keyword:
            for row in today_order_rows:
                if (
                    keyword == str(row["product_code"]).lower()
                    or keyword in str(row["product_code"]).lower()
                    or keyword in str(row["product_name"]).lower()
                ):
                    return row["product_code"], row["product_name"]

        if not today_order_rows:
            return None, None

        grouped: dict[str, dict] = {}
        for row in today_order_rows:
            data = grouped.setdefault(
                row["product_code"],
                {
                    "product_name": row["product_name"],
                    "qty": 0,
                },
            )
            data["qty"] += int(row["quantity"] or 0)

        top_code = max(grouped.items(), key=lambda x: x[1]["qty"])[0]
        return top_code, grouped[top_code]["product_name"]

    @staticmethod
    def _build_dashboard_contribution_trend(
        db: Session,
        product_code: str | None,
        target_day: date,
    ) -> list[dict]:
        labels = AdminPriceService._hourly_labels()
        bucket_map = {
            label: {
                "label": label,
                "lowest_price": 0,
                "my_price": 0,
                "sales_qty": 0,
                "contribution_profit": 0,
                "_count": 0,
            }
            for label in labels
        }

        if not product_code:
            return [bucket_map[label] for label in labels]

        product = (
            db.query(Product)
            .filter(
                Product.product_code == product_code,
                Product.deleted_at.is_(None),
            )
            .first()
        )

        if product is None:
            return [bucket_map[label] for label in labels]

        day_start = datetime.combine(target_day, time.min)
        day_end = datetime.combine(target_day + timedelta(days=1), time.min)

        histories = (
            db.query(ProductPriceHistory)
            .filter(
                ProductPriceHistory.product_id == product.id,
                ProductPriceHistory.logged_at >= day_start,
                ProductPriceHistory.logged_at < day_end,
            )
            .order_by(ProductPriceHistory.logged_at.asc(), ProductPriceHistory.id.asc())
            .all()
        )

        unit_cost = int(product.cost_price or 0)
        shipping_fee = int(getattr(product, "shipping_fee", 0) or 0)

        for history in histories:
            bucket_hour = (history.logged_at.hour // 3) * 3
            if bucket_hour > 21:
                bucket_hour = 21

            label = f"{bucket_hour}시"
            bucket = bucket_map[label]

            bucket["lowest_price"] += int(history.market_lowest_price or 0)
            bucket["my_price"] += int(history.applied_sale_price or 0)
            bucket["sales_qty"] += int(history.sales_qty or 0)
            bucket["contribution_profit"] += int(
                (int(history.applied_sale_price or 0) - unit_cost - shipping_fee)
                * int(history.sales_qty or 0)
            )
            bucket["_count"] += 1

        last_lowest = 0
        last_my_price = int(product.sale_price or 0)

        for label in labels:
            bucket = bucket_map[label]
            count = bucket.pop("_count")

            if count > 0:
                bucket["lowest_price"] = round(bucket["lowest_price"] / count)
                bucket["my_price"] = round(bucket["my_price"] / count)
                last_lowest = bucket["lowest_price"]
                last_my_price = bucket["my_price"]
            else:
                bucket["lowest_price"] = int(last_lowest)
                bucket["my_price"] = int(last_my_price)

        return [bucket_map[label] for label in labels]

    @staticmethod
    def _build_dashboard_adjustment_items(db: Session) -> list[dict]:
        rows = (
            db.query(Product, CatalogProduct)
            .outerjoin(CatalogProduct, Product.catalog_product_id == CatalogProduct.id)
            .filter(Product.deleted_at.is_(None))
            .all()
        )

        items = []
        for product, catalog in rows:
            market_lowest = int(catalog.current_lowest_price or 0) if catalog else 0
            current_price = int(product.sale_price or 0)

            if market_lowest <= 0:
                continue

            if current_price <= market_lowest:
                continue

            minimum_safe_price = int(product.cost_price or 0) + int(getattr(product, "shipping_fee", 0) or 0)
            recommended_price = max(market_lowest, minimum_safe_price)

            gap = current_price - market_lowest
            items.append(
                {
                    "product_code": product.product_code,
                    "product_name": product.product_name,
                    "current_price": current_price,
                    "market_lowest_price": market_lowest,
                    "ai_recommended_price": int(recommended_price),
                    "expected_effect": "판매량 증가" if gap >= 300 else "이탈 방지",
                    "reason": "시장 최저가 대비 높음",
                    "_gap": gap,
                }
            )

        items.sort(key=lambda x: x["_gap"], reverse=True)
        trimmed = items[:5]
        for item in trimmed:
            item.pop("_gap", None)
        return trimmed

    @staticmethod
    def _build_dashboard_low_profit_items(today_rows: list[dict]) -> list[dict]:
        grouped: dict[str, dict] = {}

        for row in today_rows:
            data = grouped.setdefault(
                row["product_code"],
                {
                    "product_code": row["product_code"],
                    "product_name": row["product_name"],
                    "profit_sum": 0,
                    "revenue_sum": 0,
                    "qty_sum": 0,
                },
            )
            profit = AdminPriceService._dashboard_contribution_profit(row)
            data["profit_sum"] += profit
            data["revenue_sum"] += int(row["line_amount"] or 0)
            data["qty_sum"] += int(row["quantity"] or 0)

        items = []
        for data in grouped.values():
            qty_sum = data["qty_sum"]
            revenue_sum = data["revenue_sum"]
            profit_sum = data["profit_sum"]

            average_profit = round(profit_sum / qty_sum) if qty_sum > 0 else 0
            profit_rate = round((profit_sum / revenue_sum) * 100, 1) if revenue_sum > 0 else 0.0

            suggestion = "가격 인상 검토"
            if profit_rate <= 0:
                suggestion = "즉시 가격/원가 점검"
            elif profit_rate < 5:
                suggestion = "원가 재검토"

            items.append(
                {
                    "product_code": data["product_code"],
                    "product_name": data["product_name"],
                    "average_profit": int(average_profit),
                    "profit_rate": float(profit_rate),
                    "suggestion": suggestion,
                }
            )

        items.sort(key=lambda x: (x["profit_rate"], x["average_profit"]))
        return [
            {"rank": idx, **item}
            for idx, item in enumerate(items[:5], start=1)
        ]

    @staticmethod
    def _build_dashboard_ranking_items(today_rows: list[dict]) -> list[dict]:
        grouped: dict[str, dict] = {}

        for row in today_rows:
            data = grouped.setdefault(
                row["product_code"],
                {
                    "product_code": row["product_code"],
                    "product_name": row["product_name"],
                    "sales_qty": 0,
                },
            )
            data["sales_qty"] += int(row["quantity"] or 0)

        items = sorted(grouped.values(), key=lambda x: x["sales_qty"], reverse=True)[:5]
        return [
            {"rank": idx, **item}
            for idx, item in enumerate(items, start=1)
        ]

    @staticmethod
    def _build_dashboard_share_points(
        rows: list[dict],
        selected_category: str,
    ) -> list[dict]:
        filtered_rows = AdminPriceService._filter_category_rows(rows, selected_category)

        product_totals: dict[str, int] = defaultdict(int)

        for row in filtered_rows:
            product_totals[row["product_code"]] += int(row["quantity"] or 0)

        top_codes = [
            code for code, _ in sorted(
                product_totals.items(),
                key=lambda x: x[1],
                reverse=True,
            )[:3]
        ]

        day_map: dict[date, dict] = {}
        for idx in range(7):
            day = datetime.now().date() - timedelta(days=6 - idx)
            day_map[day] = {"label": day.strftime("%a"), "segments": [0, 0, 0]}

        for row in filtered_rows:
            row_day = row["ordered_at"].date()
            if row_day not in day_map:
                continue

            if row["product_code"] in top_codes:
                segment_index = top_codes.index(row["product_code"])
                day_map[row_day]["segments"][segment_index] += int(row["quantity"] or 0)

        ordered_days = sorted(day_map.keys())
        return [day_map[day] for day in ordered_days]

    @staticmethod
    def get_dashboard(
        db: Session,
        current_user: Member,
        category: str | None,
        share_category: str | None,
        contribution_keyword: str,
    ) -> dict:
        AdminPriceService._ensure_admin(current_user)

        _, today_day, today_start_dt, today_end_dt = AdminPriceService._dashboard_today_range()
        _, _, last7_start_dt, last7_end_dt = AdminPriceService._dashboard_last7_range()

        categories = AdminPriceService._dashboard_categories(db)

        selected_category = category if category in categories else "전체"
        selected_share_category = share_category if share_category in categories else "전체"

        today_rows = AdminPriceService._query_order_rows(db, today_start_dt, today_end_dt)
        last7_rows = AdminPriceService._query_order_rows(db, last7_start_dt, last7_end_dt)

        today_ai_rows = [row for row in today_rows if row.get("ai_pricing_enabled")]
        today_manual_rows = [row for row in today_rows if not row.get("ai_pricing_enabled")]

        total_gmv = sum(int(row["line_amount"]) for row in today_rows)
        ai_gmv = sum(int(row["line_amount"]) for row in today_ai_rows)
        manual_gmv = sum(int(row["line_amount"]) for row in today_manual_rows)

        total_profit = sum(AdminPriceService._dashboard_contribution_profit(row) for row in today_rows)
        ai_profit = sum(AdminPriceService._dashboard_contribution_profit(row) for row in today_ai_rows)
        manual_profit = sum(AdminPriceService._dashboard_contribution_profit(row) for row in today_manual_rows)

        contribution_product_code, contribution_product_name = (
            AdminPriceService._find_contribution_target_product(today_rows, contribution_keyword)
        )

        return {
            "current_time": datetime.now().isoformat(),
            "categories": categories,
            "gmv_card": AdminPriceService._build_dashboard_metric_card(
                title="금일 매출액(GMV)",
                total_label="전체 매출",
                total_value=total_gmv,
                ai_label="AI 매출",
                ai_value=ai_gmv,
                manual_label="일반 매출",
                manual_value=manual_gmv,
            ),
            "contribution_card": AdminPriceService._build_dashboard_metric_card(
                title="금일 공헌이익",
                total_label="전체 이익",
                total_value=total_profit,
                ai_label="AI 이익",
                ai_value=ai_profit,
                manual_label="일반 이익",
                manual_value=manual_profit,
            ),
            "ai_performance": AdminPriceService._build_dashboard_ai_performance(
                db=db,
                today_rows=today_rows,
                today_start_dt=today_start_dt,
                today_end_dt=today_end_dt,
            ),
            "ai_strategy_trend": AdminPriceService._build_dashboard_ai_strategy_trend(
                rows=last7_rows,
                selected_category=selected_category,
            ),
            "contribution_trend": AdminPriceService._build_dashboard_contribution_trend(
                db=db,
                product_code=contribution_product_code,
                target_day=today_day,
            ),
            "adjustment_items": AdminPriceService._build_dashboard_adjustment_items(db),
            "low_profit_items": AdminPriceService._build_dashboard_low_profit_items(today_rows),
            "ranking_items": AdminPriceService._build_dashboard_ranking_items(today_rows),
            "share_points": AdminPriceService._build_dashboard_share_points(
                rows=last7_rows,
                selected_category=selected_share_category,
            ),
            "contribution_product_code": contribution_product_code,
            "contribution_product_name": contribution_product_name,
        }