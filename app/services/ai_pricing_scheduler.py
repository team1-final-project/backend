from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.inference import predict_optimal_price
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.enums import PriceChangeSource
from app.core.timezone import now_kst
from app.models.product import Product
from app.models.catalog_product import CatalogProduct
from app.models.product_price_history import ProductPriceHistory
from app.services.naver_crawler_service import fetch_catalog_info_by_catalog

logger = logging.getLogger(__name__)
_scheduler_lock = asyncio.Lock()


def _get_price_change_limit(product: Product) -> float:
    """
    상품별 최대 변경폭 컬럼이 있으면 그 값을 쓰고,
    없으면 전역 기본값을 사용.
    """
    value = getattr(product, "price_change_limit", None)
    if value is None:
        return float(settings.AI_PRICE_CHANGE_LIMIT_DEFAULT)
    return float(value)


def _get_market_info(db: Session, product: Product) -> tuple[float, str | None, str]:
    """
    외부 최저가 조회에 실패하면 예외를 발생시켜
    해당 상품은 저장되지 않도록 한다.
    """
    catalog_product_id = getattr(product, "catalog_product_id", None)
    if not catalog_product_id:
        raise ValueError(f"product_id={product.id}: catalog_product_id가 없습니다.")

    catalog = (
        db.query(CatalogProduct)
        .filter(CatalogProduct.id == catalog_product_id)
        .first()
    )
    if catalog is None:
        raise ValueError(f"product_id={product.id}: catalog_product를 찾을 수 없습니다.")

    external_catalog_id = getattr(catalog, "external_catalog_id", None)
    if not external_catalog_id:
        raise ValueError(f"product_id={product.id}: external_catalog_id가 없습니다.")

    logger.info(
        "외부 최저가 크롤링 시작. product_id=%s, external_catalog_id=%s",
        product.id,
        external_catalog_id,
    )

    info = fetch_catalog_info_by_catalog(str(external_catalog_id))
    if not info:
        raise ValueError(f"product_id={product.id}: 외부 최저가 조회 결과가 없습니다.")

    market_lowest_price = info.get("lowest_price")
    catalog_name = info.get("catalog_name")

    if market_lowest_price is None:
        raise ValueError(f"product_id={product.id}: 외부 최저가가 없습니다.")

    return float(market_lowest_price), catalog_name, str(external_catalog_id)

def _build_history_row(
    product: Product,
    old_price: float,
    result: dict,
    market_lowest_price: Optional[float],
) -> ProductPriceHistory:
    previous_price = int(round(old_price))
    applied_price = int(round(float(result["change_price"])))

    price_gap = applied_price - previous_price
    price_gap_rate = round((price_gap / previous_price) * 100, 2) if previous_price > 0 else 0.0

    is_lowest_price = False
    if market_lowest_price is not None:
        market_lowest_price = int(market_lowest_price)
        is_lowest_price = applied_price <= market_lowest_price

    now = now_kst()

    return ProductPriceHistory(
        product_id=product.id,
        catalog_product_id=getattr(product, "catalog_product_id", None),
        logged_at=now,

        previous_sale_price=previous_price,
        applied_sale_price=applied_price,

        sales_qty=0,
        sales_per_hour=0,

        is_lowest_price=is_lowest_price,
        market_lowest_price=market_lowest_price,

        price_gap=price_gap,
        price_gap_rate=price_gap_rate,

        min_price_limit=getattr(product, "min_price_limit", None),
        max_price_limit=getattr(product, "max_price_limit", None),

        remaining_stock=product.stock_qty,

        change_source=PriceChangeSource.AI,
        changed_by=None,
        note="AI 자동 가격 조정",

        created_at=now,
        updated_at=now,
    )

def _process_one_product(db: Session, product: Product) -> None:
    old_price = float(product.sale_price)

    keyword = getattr(product, "product_name", None)
    current_price = float(product.sale_price)
    min_price_limit = float(getattr(product, "min_price_limit"))
    max_price_limit = float(getattr(product, "max_price_limit"))
    current_stock = float(getattr(product, "stock_qty"))
    safety_stock = float(getattr(product, "safety_stock_qty"))

    product_code = getattr(product, "product_code", None)
    if not product_code:
        raise ValueError(f"product_id={product.id}: product_code가 없습니다.")

    market_lowest_price, catalog_name, external_catalog_id = _get_market_info(db, product)

    result = predict_optimal_price(
        keyword=keyword,
        current_price=current_price,
        price_change_limit=_get_price_change_limit(product),
        min_price_limit=min_price_limit,
        max_price_limit=max_price_limit,
        current_stock=current_stock,
        safety_stock=safety_stock,
        good_id=str(product_code),
        market_lowest_price=market_lowest_price,
        catalog_code=external_catalog_id,
        catalog_name=catalog_name,
    )

    new_price = float(result["change_price"])
    product.sale_price = new_price

    if hasattr(product, "u_date"):
        product.u_date = now_kst()

    history = _build_history_row(
        product=product,
        old_price=old_price,
        result=result,
        market_lowest_price=market_lowest_price,
    )
    db.add(history)
    
def _run_ai_pricing_once_sync() -> None:
    """
    동기 DB 작업 본체
    상품별 개별 commit/rollback 처리로
    한 상품 실패해도 나머지는 계속 진행
    """
    db = SessionLocal()
    try:
        stmt = select(Product).where(Product.ai_pricing_enabled == 1)
        products = db.execute(stmt).scalars().all()

        logger.info("AI 자동 가격조정 시작. 대상 상품 수=%s", len(products))

        for product in products:
            try:
                _process_one_product(db, product)
                db.commit()
                db.refresh(product)
                logger.info(
                    "AI 가격 반영 완료. product_id=%s, sale_price=%s",
                    product.id,
                    product.sale_price,
                )
            except Exception:
                db.rollback()
                logger.exception("AI 가격 반영 실패. product_id=%s", product.id)

        logger.info("AI 자동 가격조정 종료")
    finally:
        db.close()


async def run_ai_pricing_once() -> None:
    """
    비동기 래퍼
    """
    if _scheduler_lock.locked():
        logger.warning("이전 AI 가격조정 작업이 아직 실행 중이라 이번 회차는 건너뜀")
        return

    async with _scheduler_lock:
        await asyncio.to_thread(_run_ai_pricing_once_sync)


async def run_ai_pricing_scheduler_forever() -> None:
    """
    서버 켜져 있는 동안 n분마다 반복 실행
    """
    interval_minutes = int(settings.AI_PRICING_INTERVAL_MINUTES)
    interval_seconds = max(interval_minutes * 60, 1)

    if getattr(settings, "AI_PRICING_RUN_ON_STARTUP", False):
        try:
            await run_ai_pricing_once()
        except Exception:
            logger.exception("서버 시작 직후 AI 가격조정 실행 실패")

    while True:
        started_at = time.monotonic()

        try:
            await run_ai_pricing_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("주기 AI 가격조정 실행 중 예외 발생")

        elapsed = time.monotonic() - started_at
        sleep_seconds = max(interval_seconds - elapsed, 1)
        await asyncio.sleep(sleep_seconds)


async def stop_task_safely(task: asyncio.Task | None) -> None:
    if task is None:
        return

    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task