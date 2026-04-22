from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.enums import MemberRole, OrderStatus, PaymentStatus, PriceChangeSource
from app.models.catalog_product import CatalogProduct
from app.models.category import Category
from app.models.member import Member
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.product import Product
from app.models.product_price_history import ProductPriceHistory


class AdminDashboardService:
    @staticmethod
    def _ensure_admin(current_user: Member) -> None:
        if current_user.role != MemberRole.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="관리자만 접근할 수 있습니다.",
            )

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
    def _hourly_labels() -> list[str]:
        return ["0시", "3시", "6시", "9시", "12시", "15시", "18시", "21시", "24시"]

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
                    "category_name": AdminDashboardService._leaf_category_name(category),
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
            name = AdminDashboardService._leaf_category_name(row)
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
            AdminDashboardService._dashboard_contribution_profit(row)
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
        filtered_rows = AdminDashboardService._filter_category_rows(rows, selected_category)

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

            profit = AdminDashboardService._dashboard_contribution_profit(row)
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
        labels = AdminDashboardService._hourly_labels()
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
            profit = AdminDashboardService._dashboard_contribution_profit(row)
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
        filtered_rows = AdminDashboardService._filter_category_rows(rows, selected_category)

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
        AdminDashboardService._ensure_admin(current_user)

        _, today_day, today_start_dt, today_end_dt = AdminDashboardService._dashboard_today_range()
        _, _, last7_start_dt, last7_end_dt = AdminDashboardService._dashboard_last7_range()

        categories = AdminDashboardService._dashboard_categories(db)

        selected_category = category if category in categories else "전체"
        selected_share_category = share_category if share_category in categories else "전체"

        today_rows = AdminDashboardService._query_order_rows(db, today_start_dt, today_end_dt)
        last7_rows = AdminDashboardService._query_order_rows(db, last7_start_dt, last7_end_dt)

        today_ai_rows = [row for row in today_rows if row.get("ai_pricing_enabled")]
        today_manual_rows = [row for row in today_rows if not row.get("ai_pricing_enabled")]

        total_gmv = sum(int(row["line_amount"]) for row in today_rows)
        ai_gmv = sum(int(row["line_amount"]) for row in today_ai_rows)
        manual_gmv = sum(int(row["line_amount"]) for row in today_manual_rows)

        total_profit = sum(AdminDashboardService._dashboard_contribution_profit(row) for row in today_rows)
        ai_profit = sum(AdminDashboardService._dashboard_contribution_profit(row) for row in today_ai_rows)
        manual_profit = sum(AdminDashboardService._dashboard_contribution_profit(row) for row in today_manual_rows)

        contribution_product_code, contribution_product_name = (
            AdminDashboardService._find_contribution_target_product(today_rows, contribution_keyword)
        )

        return {
            "current_time": datetime.now().isoformat(),
            "categories": categories,
            "gmv_card": AdminDashboardService._build_dashboard_metric_card(
                title="금일 매출액(GMV)",
                total_label="전체 매출",
                total_value=total_gmv,
                ai_label="AI 매출",
                ai_value=ai_gmv,
                manual_label="일반 매출",
                manual_value=manual_gmv,
            ),
            "contribution_card": AdminDashboardService._build_dashboard_metric_card(
                title="금일 공헌이익",
                total_label="전체 이익",
                total_value=total_profit,
                ai_label="AI 이익",
                ai_value=ai_profit,
                manual_label="일반 이익",
                manual_value=manual_profit,
            ),
            "ai_performance": AdminDashboardService._build_dashboard_ai_performance(
                db=db,
                today_rows=today_rows,
                today_start_dt=today_start_dt,
                today_end_dt=today_end_dt,
            ),
            "ai_strategy_trend": AdminDashboardService._build_dashboard_ai_strategy_trend(
                rows=last7_rows,
                selected_category=selected_category,
            ),
            "contribution_trend": AdminDashboardService._build_dashboard_contribution_trend(
                db=db,
                product_code=contribution_product_code,
                target_day=today_day,
            ),
            "adjustment_items": AdminDashboardService._build_dashboard_adjustment_items(db),
            "low_profit_items": AdminDashboardService._build_dashboard_low_profit_items(today_rows),
            "ranking_items": AdminDashboardService._build_dashboard_ranking_items(today_rows),
            "share_points": AdminDashboardService._build_dashboard_share_points(
                rows=last7_rows,
                selected_category=selected_share_category,
            ),
            "contribution_product_code": contribution_product_code,
            "contribution_product_name": contribution_product_name,
        }