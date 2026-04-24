from __future__ import annotations

import asyncio
import contextlib
import datetime
import logging
import time
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.inference import predict_optimal_price
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.enums import PriceChangeSource, ProductSaleStatus
from app.core.timezone import now_kst
from app.models.product import Product
from app.models.catalog_product import CatalogProduct
from app.models.product_price_history import ProductPriceHistory
from app.services.naver_crawler_service import (
    fetch_catalog_info_by_catalog,
    NaverCaptchaDetectedError,
)
from app.services.utils.catalog_pricing_utils import (
    parse_pack_count,
    calculate_unit_sale_price,
)

logger = logging.getLogger(__name__)
_scheduler_lock = asyncio.Lock()
CAPTCHA_RETRY_SECONDS = 15
DEAD_STOCK_DAYS = 90


def _get_price_change_limit(product: Product) -> float:
    """
    상품별 회당 조정가(price_per_time)가 있으면 그 값을 쓰고,
    없으면 전역 기본값을 사용.
    """
    value = getattr(product, "price_per_time", None)
    if value is None:
        return float(settings.AI_PRICE_CHANGE_LIMIT_DEFAULT)
    return float(value)


def _get_inventory_base_date(product: Product) -> datetime.datetime | None:
    """
    악성재고 판정 기준일을 가져온다.
    실제 입고일 컬럼이 있으면 그 값을 우선 사용하고,
    현재 모델에 입고일이 없다면 상품 생성일(created_at/c_date)을 보조 기준으로 사용한다.
    """
    for attr in (
        "stock_received_at",
        "last_stocked_at",
        "received_at",
        "created_at",
        "c_date",
    ):
        value = getattr(product, attr, None)
        if value is None:
            continue

        if isinstance(value, datetime.datetime):
            return value

        if isinstance(value, datetime.date):
            return datetime.datetime.combine(value, datetime.time.min)

    return None


def _is_dead_stock(product: Product) -> bool:
    """
    악성재고 여부
    - 기준: 재고 기준일로부터 90일 이상 경과
    """
    base_date = _get_inventory_base_date(product)
    if base_date is None:
        return False

    now = now_kst()

    # timezone aware/naive 혼용으로 인한 TypeError 방지
    if base_date.tzinfo is not None and now.tzinfo is None:
        base_date = base_date.replace(tzinfo=None)
    elif base_date.tzinfo is None and now.tzinfo is not None:
        now = now.replace(tzinfo=None)

    return now - base_date >= datetime.timedelta(days=DEAD_STOCK_DAYS)




def _get_market_info(
    db: Session,
    product: Product,
) -> tuple[CatalogProduct, float, str | None, str]:
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
    
    catalog.current_lowest_price = int(market_lowest_price)

    if catalog_name:
        catalog.catalog_name = catalog_name

    pack_count = parse_pack_count(catalog_name)
    catalog.pack_count = pack_count
    catalog.current_lowest_price = int(market_lowest_price)
    catalog.unit_sale_price = calculate_unit_sale_price(
        market_lowest_price,
        pack_count,
    )

    return catalog, float(market_lowest_price), catalog_name, str(external_catalog_id)

def _build_ai_history_reason(
        *,
        previous_price: int,
        applied_price: int,
        stock_qty: int,
        safety_stock_qty: int,
        is_dead_stock: bool = False,
    ) -> str:
        if is_dead_stock and applied_price <= previous_price:
            return "악성재고(90일 이상) 가격인하"

        if safety_stock_qty > 0 and stock_qty >= safety_stock_qty * 2:
            if applied_price <= previous_price:
                return "악성재고 가격인하"

        if safety_stock_qty > 0 and stock_qty <= safety_stock_qty:
            if applied_price >= previous_price:
                return "품절임박 가격인상"

        if applied_price < previous_price:
            return "최저가변동 가격인하"

        return "최저가변동 가격인상"

def _build_history_row(
    product: Product,
    old_price: float,
    result: dict,
    market_lowest_price: Optional[float],
    my_pack_count: int,
    my_unit_sale_price: int,
    market_pack_count: Optional[int],
    market_unit_sale_price: Optional[int],
) -> ProductPriceHistory:
    previous_price = int(round(old_price))
    applied_price = int(round(float(result["change_price"])))

    price_gap = applied_price - previous_price
    price_gap_rate = round((price_gap / previous_price) * 100, 2) if previous_price > 0 else 0.0

    # 이제 최저가 여부는 "개당 가격" 기준
    is_lowest_price = False
    if market_unit_sale_price is not None:
        is_lowest_price = int(my_unit_sale_price) <= int(market_unit_sale_price)

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
        market_lowest_price=int(market_lowest_price) if market_lowest_price is not None else None,

        price_gap=price_gap,
        price_gap_rate=price_gap_rate,

        min_price_limit=getattr(product, "min_price_limit", None),
        max_price_limit=getattr(product, "max_price_limit", None),
        price_per_time=getattr(product, "price_per_time", None),

        remaining_stock=int(product.stock_qty or 0),

        my_pack_count=my_pack_count,
        my_unit_sale_price=my_unit_sale_price,
        market_pack_count=market_pack_count,
        market_unit_sale_price=market_unit_sale_price,

        change_source=PriceChangeSource.AI,
        changed_by=None,
        note=_build_ai_history_reason(
            previous_price=previous_price,
            applied_price=applied_price,
            stock_qty=int(product.stock_qty or 0),
            safety_stock_qty=int(product.safety_stock_qty or 0),
            is_dead_stock=_is_dead_stock(product),
        ),

        created_at=now,
        updated_at=now,
    )

def _process_one_product(db: Session, product: Product) -> bool:
    """
    상품 1건 처리
    - product 기준 값 읽기
    - 카탈로그 크롤링 + catalog_product 최신화
    - AI 가격 결정 (개당 최저가 기준)
    - product / product_price_history 반영
    """
    old_price = float(product.sale_price)

    keyword = getattr(product, "product_name", None)
    current_price = float(product.sale_price)

    min_price_limit_raw = getattr(product, "min_price_limit", None)
    max_price_limit_raw = getattr(product, "max_price_limit", None)
    price_per_time_raw = getattr(product, "price_per_time", None)

    if min_price_limit_raw is None or max_price_limit_raw is None:
        raise ValueError(
            f"product_id={product.id}: 최소가/최대가 제한이 없어 AI 가격조정을 진행할 수 없습니다."
        )

    if price_per_time_raw is None:
        raise ValueError(
            f"product_id={product.id}: 회당 조정가(price_per_time)가 없어 AI 가격조정을 진행할 수 없습니다."
        )

    min_price_limit = float(min_price_limit_raw)
    max_price_limit = float(max_price_limit_raw)
    current_stock = float(getattr(product, "stock_qty"))
    safety_stock = float(getattr(product, "safety_stock_qty"))
    is_dead_stock = _is_dead_stock(product)

    product_code = getattr(product, "product_code", None)
    if not product_code:
        raise ValueError(f"product_id={product.id}: product_code가 없습니다.")

    my_pack_count = int(getattr(product, "pack_count", 1) or 1)

    # 1) 카탈로그 크롤링 및 catalog_product 최신화
    catalog, market_lowest_price, catalog_name, external_catalog_id = _get_market_info(db, product)

    market_pack_count = int(getattr(catalog, "pack_count", 1) or 1)
    market_unit_sale_price = (
        int(getattr(catalog, "unit_sale_price", 0))
        if getattr(catalog, "unit_sale_price", None) is not None
        else None
    )

    # 2) AI 가격 결정
    result = predict_optimal_price(
        keyword=keyword,
        current_price=current_price,
        price_change_limit=_get_price_change_limit(product),
        min_price_limit=min_price_limit,
        max_price_limit=max_price_limit,
        current_stock=current_stock,
        safety_stock=safety_stock,
        good_id=str(product_code),
        my_pack_count=my_pack_count,
        market_lowest_price=market_lowest_price,
        market_unit_price=float(market_unit_sale_price) if market_unit_sale_price is not None else None,
        catalog_code=external_catalog_id,
        catalog_name=catalog_name,
        is_dead_stock=is_dead_stock,
    )

    # 3) product 가격 반영
    new_price = int(round(float(result["change_price"])))
    old_price_int = int(round(old_price))

    if new_price == old_price_int:
        logger.info(
            "AI 가격 유지. product_id=%s, sale_price=%s",
            product.id,
            old_price_int,
        )
        return False

    product.sale_price = new_price
    product.unit_sale_price = calculate_unit_sale_price(
        new_price,
        my_pack_count,
    )

    if hasattr(product, "u_date"):
        product.u_date = now_kst()

    # 4) history 저장
    history = _build_history_row(
        product=product,
        old_price=old_price,
        result=result,
        market_lowest_price=market_lowest_price,
        my_pack_count=my_pack_count,
        my_unit_sale_price=int(product.unit_sale_price or 0),
        market_pack_count=market_pack_count,
        market_unit_sale_price=market_unit_sale_price,
    )
    db.add(history)

    return True
    
def _run_ai_pricing_once_sync() -> None:
    """
    동기 DB 작업 본체
    - 일반 실패: 해당 상품만 rollback 후 다음 상품 진행
    - 캡챠 감지: 현재 회차 즉시 중단하고 상위로 예외 전파
    """
    db = SessionLocal()
    try:
        stmt = (
            select(Product)
            .where(
                Product.ai_pricing_enabled.is_(True),
                Product.sale_status == ProductSaleStatus.ON_SALE,
                Product.deleted_at.is_(None),
            )
        )
        products = db.execute(stmt).scalars().all()

        logger.info("AI 자동 가격조정 시작. 대상 상품 수=%s", len(products))

        for product in products:
            try:
                changed = _process_one_product(db, product)
                db.commit()
                db.refresh(product)

                if changed:
                    logger.info(
                        "AI 가격 반영 완료. product_id=%s, sale_price=%s",
                        product.id,
                        product.sale_price,
                    )
                else:
                    logger.info(
                        "AI 가격 미변경. history 저장 없음. product_id=%s, sale_price=%s",
                        product.id,
                        product.sale_price,
                    )

            except NaverCaptchaDetectedError:
                db.rollback()
                logger.warning(
                    "캡챠 감지로 현재 AI 가격조정 회차를 즉시 중단합니다. product_id=%s",
                    product.id,
                )
                raise

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
    - 캡챠 감지 시: 즉시 중단 후 30초 뒤 재시도
    """
    interval_minutes = int(settings.AI_PRICING_INTERVAL_MINUTES)
    interval_seconds = max(interval_minutes * 60, 1)

    if getattr(settings, "AI_PRICING_RUN_ON_STARTUP", False):
        try:
            await run_ai_pricing_once()
        except NaverCaptchaDetectedError:
            logger.warning(
                "서버 시작 직후 캡챠 감지. %s초 후 재시도합니다.",
                CAPTCHA_RETRY_SECONDS,
            )
            await asyncio.sleep(CAPTCHA_RETRY_SECONDS)
        except Exception:
            logger.exception("서버 시작 직후 AI 가격조정 실행 실패")

    while True:
        started_at = time.monotonic()

        try:
            await run_ai_pricing_once()

        except asyncio.CancelledError:
            raise

        except NaverCaptchaDetectedError:
            logger.warning(
                "AI 가격 조정 중 캡챠 감지. 현재 회차를 중단하고 %s초 후 재시도합니다.",
                CAPTCHA_RETRY_SECONDS,
            )
            await asyncio.sleep(CAPTCHA_RETRY_SECONDS)
            continue

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