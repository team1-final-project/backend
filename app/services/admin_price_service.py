from __future__ import annotations

from datetime import date, datetime, time, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.enums import MemberRole
from app.models.catalog_product import CatalogProduct
from app.models.member import Member
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