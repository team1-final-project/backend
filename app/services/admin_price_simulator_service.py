from __future__ import annotations

import json
import logging
import os
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.enums import InventoryChangeType, ProductSaleStatus
from app.core.timezone import now_kst
from app.models.inventory_log import InventoryLog
from app.models.product import Product
from app.models.product_price_history import ProductPriceHistory

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[2]
RUNTIME_DIR = BASE_DIR / ".runtime"
STATE_FILE = RUNTIME_DIR / "price_simulator_state.json"
STOP_FILE = RUNTIME_DIR / "price_simulator.stop"


def _ensure_runtime_dir() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)


def _dt_to_str(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _default_state() -> dict[str, Any]:
    return {
        "is_running": False,
        "pid": None,
        "started_at": None,
        "stopped_at": None,
        "last_cycle_at": None,
        "last_message": None,
    }


def _read_state() -> dict[str, Any]:
    _ensure_runtime_dir()

    if not STATE_FILE.exists():
        return _default_state()

    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return _default_state()


def _write_state(
    *,
    is_running: bool,
    pid: int | None,
    started_at: datetime | None,
    stopped_at: datetime | None,
    last_cycle_at: datetime | None,
    last_message: str | None,
) -> None:
    _ensure_runtime_dir()

    payload = {
        "is_running": is_running,
        "pid": pid,
        "started_at": _dt_to_str(started_at),
        "stopped_at": _dt_to_str(stopped_at),
        "last_cycle_at": _dt_to_str(last_cycle_at),
        "last_message": last_message,
    }

    STATE_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _clear_stop_request() -> None:
    if STOP_FILE.exists():
        STOP_FILE.unlink(missing_ok=True)


def _request_stop() -> None:
    _ensure_runtime_dir()
    STOP_FILE.write_text("stop", encoding="utf-8")


def _should_stop() -> bool:
    return STOP_FILE.exists()


def _get_latest_history(db: Session, product_id: int) -> ProductPriceHistory | None:
    return (
        db.query(ProductPriceHistory)
        .filter(ProductPriceHistory.product_id == product_id)
        .order_by(
            ProductPriceHistory.logged_at.desc(),
            ProductPriceHistory.id.desc(),
        )
        .first()
    )


def _process_one_product_simulation(db: Session, product: Product) -> int:
    """
    상품 1건에 대해 랜덤 판매를 반영한다.
    반환값은 실제 차감된 수량.
    """
    current_stock = int(product.stock_qty or 0)
    if current_stock <= 0:
        return 0

    random_qty = random.randint(1, 20)
    actual_sold_qty = min(random_qty, current_stock)

    if actual_sold_qty <= 0:
        return 0

    qty_before = current_stock
    qty_after = current_stock - actual_sold_qty
    now = now_kst()

    # 1) product 재고 차감
    product.stock_qty = qty_after

    # 2) inventory_log 적재
    inventory_log = InventoryLog(
        product_id=product.id,
        change_type=InventoryChangeType.ORDER_OUT,
        qty_before=qty_before,
        change_qty=actual_sold_qty,
        qty_after=qty_after,
        related_order_item_id=None,
        note="가격 시뮬레이터 자동 판매",
        created_by=None,
        occurred_at=now,
    )
    db.add(inventory_log)

    # 3) 가장 최근 product_price_history 업데이트
    latest_history = _get_latest_history(db, product.id)
    if latest_history is not None:
        latest_history.sales_qty = int(latest_history.sales_qty or 0) + actual_sold_qty

        elapsed_hours = max(
            (now - latest_history.logged_at).total_seconds() / 3600,
            1 / 3600,
        )
        latest_history.sales_per_hour = round(
            int(latest_history.sales_qty or 0) / elapsed_hours,
            2,
        )

    return actual_sold_qty


def run_one_cycle_sync() -> dict[str, int]:
    """
    판매중(ON_SALE) 상품 전체를 한 번 순회한다.
    같은 사이클 시각에 전체 상품을 돌고,
    상품별 차감 수량만 랜덤이다.
    """
    db = SessionLocal()
    processed_count = 0
    updated_count = 0
    total_sold_qty = 0

    try:
        products = (
            db.query(Product)
            .filter(
                Product.sale_status == ProductSaleStatus.ON_SALE,
                Product.deleted_at.is_(None),
            )
            .order_by(Product.id.asc())
            .all()
        )

        for product in products:
            if _should_stop():
                logger.info("중지 요청 감지. 현재 사이클을 마무리하고 종료합니다.")
                break

            processed_count += 1

            try:
                sold_qty = _process_one_product_simulation(db, product)
                db.commit()

                if sold_qty > 0:
                    updated_count += 1
                    total_sold_qty += sold_qty

                    logger.info(
                        "시뮬레이션 판매 반영 완료. product_id=%s, product_code=%s, sold_qty=%s, stock_qty=%s",
                        product.id,
                        product.product_code,
                        sold_qty,
                        product.stock_qty,
                    )
            except Exception:
                db.rollback()
                logger.exception(
                    "시뮬레이션 판매 반영 실패. product_id=%s, product_code=%s",
                    product.id,
                    product.product_code,
                )

        return {
            "processed_count": processed_count,
            "updated_count": updated_count,
            "total_sold_qty": total_sold_qty,
        }
    finally:
        db.close()


def run_simulator_forever(
    min_seconds: int = 180,
    max_seconds: int = 300,
) -> None:
    """
    포그라운드 CLI 실행용.
    종료는
    1) 다른 터미널에서 stop 명령 실행
    2) 현재 터미널에서 Ctrl+C
    """
    if min_seconds <= 0 or max_seconds <= 0:
        raise ValueError("대기 시간은 0보다 커야 합니다.")
    if min_seconds > max_seconds:
        raise ValueError("min_seconds는 max_seconds보다 클 수 없습니다.")

    state = _read_state()
    if state.get("is_running"):
        raise RuntimeError("시뮬레이터가 이미 실행 중입니다.")

    _clear_stop_request()

    started_at = now_kst()
    _write_state(
        is_running=True,
        pid=os.getpid(),
        started_at=started_at,
        stopped_at=None,
        last_cycle_at=None,
        last_message="시뮬레이터가 시작되었습니다.",
    )

    logger.info(
        "가격 시뮬레이터 시작. pid=%s, wait_range=%s~%s초",
        os.getpid(),
        min_seconds,
        max_seconds,
    )

    try:
        while True:
            if _should_stop():
                logger.info("중지 요청 감지. 시뮬레이터를 종료합니다.")
                break

            wait_seconds = random.randint(min_seconds, max_seconds)
            logger.info("다음 사이클까지 %s초 대기", wait_seconds)

            for _ in range(wait_seconds):
                if _should_stop():
                    break
                time.sleep(1)

            if _should_stop():
                logger.info("대기 중 중지 요청 감지. 시뮬레이터를 종료합니다.")
                break

            result = run_one_cycle_sync()
            last_cycle_at = now_kst()

            _write_state(
                is_running=True,
                pid=os.getpid(),
                started_at=started_at,
                stopped_at=None,
                last_cycle_at=last_cycle_at,
                last_message=(
                    f"사이클 완료 - processed={result['processed_count']}, "
                    f"updated={result['updated_count']}, "
                    f"total_sold_qty={result['total_sold_qty']}"
                ),
            )

    except KeyboardInterrupt:
        logger.info("Ctrl+C 감지. 시뮬레이터를 종료합니다.")
    finally:
        stopped_at = now_kst()
        _clear_stop_request()
        _write_state(
            is_running=False,
            pid=None,
            started_at=started_at,
            stopped_at=stopped_at,
            last_cycle_at=_read_state().get("last_cycle_at"),
            last_message="시뮬레이터가 종료되었습니다.",
        )


def request_stop() -> dict[str, Any]:
    state = _read_state()

    if not state.get("is_running"):
        return {
            "is_running": False,
            "message": "현재 실행 중인 시뮬레이터가 없습니다.",
        }

    _request_stop()
    return {
        "is_running": True,
        "message": "중지 요청을 등록했습니다. 다음 확인 지점에서 종료됩니다.",
    }


def get_status() -> dict[str, Any]:
    return _read_state()