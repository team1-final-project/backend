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
from app.models.product_price_history import ProductPriceHistory

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


def _get_market_info(product: Product) -> tuple[Optional[float], Optional[str]]:
    """
    외부 최저가 / 카탈로그명 조회.
    네 기존 크롤링 서비스에 맞춰 여기만 연결하면 됨.

    지금은 안전하게 fallback(None, None) 처리.
    필요하면 아래 TODO 부분만 네 crawler 함수명에 맞게 바꿔.
    """
    catalog_code = getattr(product, "catalog_id", None) or getattr(product, "catalog_code", None)
    if not catalog_code:
        return None, None

    try:
        # TODO:
        # 네 프로젝트의 실제 함수명에 맞춰 수정
        # 예:
        # from app.services.naver_crawler_service import fetch_catalog_info_by_catalog
        # info = fetch_catalog_info_by_catalog(str(catalog_code))
        # return info.get("lowest_price"), info.get("catalog_name")

        return None, None
    except Exception:
        logger.exception("외부 최저가 조회 실패. product_id=%s", product.id)
        return None, None


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

        remaining_stock=int(product.stock_qty or 0),

        change_source=PriceChangeSource.AI,
        changed_by=None,
        note="AI 자동 가격 조정",

        created_at=now,
        updated_at=now,
    )

def _process_one_product(db: Session, product: Product) -> None:
    """
    상품 1건 처리
    """
    old_price = float(product.sale_price)

    # ===== 필수 매핑 =====
    keyword = getattr(product, "product_name", None)
    current_price = float(product.sale_price)
    min_price_limit = float(getattr(product, "min_price_limit"))
    max_price_limit = float(getattr(product, "max_price_limit"))
    current_stock = float(getattr(product, "stock_qty"))
    safety_stock = float(getattr(product, "safety_stock_qty"))

    product_code = getattr(product, "product_code", None)
    if not product_code:
        raise ValueError(f"product_id={product.id}: product_code가 없습니다.")

    catalog_code = getattr(product, "catalog_id", None) or getattr(product, "catalog_code", None)
    market_lowest_price, catalog_name = _get_market_info(product)

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
        catalog_code=str(catalog_code) if catalog_code is not None else None,
        catalog_name=catalog_name,
    )

    new_price = float(result["change_price"])

    # 3-1) product.sale_price 반영
    product.sale_price = new_price

    # 필요하면 수정일 직접 갱신
    if hasattr(product, "u_date"):
        from app.core.timezone import now_kst
        product.u_date = now_kst()

    # 3-2) price history 로그 삽입
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