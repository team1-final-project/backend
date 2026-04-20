from __future__ import annotations

import json
import logging
import os
import random
import string
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.enums import (
    InventoryChangeType,
    MemberRole,
    MemberStatus,
    OrderStatus,
    PaymentProvider,
    PaymentStatus,
    PriceChangeSource,
    ProductSaleStatus,
)
from app.core.timezone import now_kst
from app.models.inventory_log import InventoryLog
from app.models.member import Member
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.order_shipping import OrderShipping
from app.models.payment import Payment
from app.models.product import Product
from app.models.product_price_history import ProductPriceHistory

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[2]
RUNTIME_DIR = BASE_DIR / ".runtime"
STATE_FILE = RUNTIME_DIR / "price_simulator_state.json"
STOP_FILE = RUNTIME_DIR / "price_simulator.stop"

SIMULATOR_DEFAULT_PHONE = "010-0000-0000"
SIMULATOR_DEFAULT_ZIPCODE = "04524"
SIMULATOR_DEFAULT_ADDRESS1 = "서울특별시 중구 을지로 100"
SIMULATOR_DEFAULT_ADDRESS2 = "시뮬레이터 생성 주문"
SIMULATOR_DEFAULT_REQUEST = "문 앞에 놓아주세요."


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


def _generate_random_suffix(length: int = 6) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=length))


def _generate_order_no(now: datetime, product_id: int) -> str:
    return f"SIM-{now.strftime('%Y%m%d%H%M%S')}-{product_id}-{_generate_random_suffix(4)}"


def _generate_payment_key(order_no: str) -> str:
    return f"sim-pay-{order_no}-{_generate_random_suffix(6)}"


def _split_quantity(total_qty: int) -> list[int]:
    if total_qty <= 1:
        return [total_qty]

    chunk_count = random.randint(1, min(3, total_qty))
    parts: list[int] = []
    remaining = total_qty

    for index in range(chunk_count - 1):
        max_alloc = remaining - (chunk_count - index - 1)
        allocated = random.randint(1, max_alloc)
        parts.append(allocated)
        remaining -= allocated

    parts.append(remaining)
    random.shuffle(parts)
    return parts


def _select_simulation_member(db: Session) -> Member:
    active_users = (
        db.query(Member)
        .filter(
            Member.status == MemberStatus.ACTIVE,
            Member.role == MemberRole.USER,
        )
        .order_by(Member.id.asc())
        .all()
    )
    if active_users:
        return random.choice(active_users)

    active_members = (
        db.query(Member)
        .filter(Member.status == MemberStatus.ACTIVE)
        .order_by(Member.id.asc())
        .all()
    )
    if active_members:
        return random.choice(active_members)

    any_member = db.query(Member).order_by(Member.id.asc()).first()
    if any_member:
        return any_member

    raise RuntimeError("시뮬레이터 주문 생성에 사용할 member 데이터가 없습니다.")


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


def _normalize_unit_price(total_price: int, pack_count: int) -> int:
    normalized_pack_count = max(1, int(pack_count or 1))
    return max(1, round(total_price / normalized_pack_count))


def _simulate_sale_price(product: Product) -> tuple[int, int]:
    previous_sale_price = int(product.sale_price or 0)
    if previous_sale_price <= 0:
        previous_sale_price = 1000

    stock_qty = int(product.stock_qty or 0)
    safety_stock_qty = int(product.safety_stock_qty or 0)

    if product.ai_pricing_enabled:
        if safety_stock_qty > 0 and stock_qty >= safety_stock_qty * 2:
            delta_choices = [-300, -200, -100, -100, 0, 100]
        elif safety_stock_qty > 0 and stock_qty <= safety_stock_qty:
            delta_choices = [0, 100, 100, 200, 300]
        else:
            delta_choices = [-200, -100, 0, 100, 200]
    else:
        delta_choices = [-200, -100, 0, 100, 200]

    delta = random.choice(delta_choices)
    applied_sale_price = previous_sale_price + delta

    if product.min_price_limit is not None:
        applied_sale_price = max(applied_sale_price, int(product.min_price_limit))
    if product.max_price_limit is not None:
        applied_sale_price = min(applied_sale_price, int(product.max_price_limit))

    applied_sale_price = max(100, applied_sale_price)
    return previous_sale_price, applied_sale_price


def _simulate_market_lowest_price(
    product: Product,
    latest_history: ProductPriceHistory | None,
    applied_sale_price: int,
) -> int:
    base_price = (
        int(latest_history.market_lowest_price)
        if latest_history and latest_history.market_lowest_price is not None
        else applied_sale_price
    )

    variation = random.choice([-200, -100, -50, -20, 0, 20, 50, 100])
    market_lowest_price = max(100, base_price + variation)

    if product.ai_pricing_enabled and random.random() < 0.55:
        market_lowest_price = max(100, applied_sale_price + random.choice([-50, 0, 50]))

    return market_lowest_price


def _create_order_bundle(
    db: Session,
    *,
    buyer: Member,
    product: Product,
    quantity: int,
    ordered_at: datetime,
) -> tuple[Order, OrderItem]:
    order_no = _generate_order_no(ordered_at, product.id)

    unit_price = int(product.sale_price or 0)
    shipping_fee = int(product.shipping_fee or 0)
    line_amount = unit_price * quantity
    total_payment_amount = line_amount + shipping_fee

    order = Order(
        order_no=order_no,
        member_id=buyer.id,
        order_status=OrderStatus.PAID,
        payment_status=PaymentStatus.APPROVED,
        total_product_amount=line_amount,
        total_shipping_fee=shipping_fee,
        total_payment_amount=total_payment_amount,
        ordered_at=ordered_at,
        paid_at=ordered_at,
        canceled_at=None,
    )
    db.add(order)
    db.flush()

    order_item = OrderItem(
        order_id=order.id,
        product_id=product.id,
        cart_item_id=None,
        product_code=product.product_code,
        product_name=product.product_name,
        unit_price=unit_price,
        quantity=quantity,
        line_amount=line_amount,
    )
    db.add(order_item)
    db.flush()

    shipping = OrderShipping(
        order_id=order.id,
        recipient_name=buyer.name or "시뮬레이터 사용자",
        recipient_phone=buyer.phone or SIMULATOR_DEFAULT_PHONE,
        zipcode=SIMULATOR_DEFAULT_ZIPCODE,
        address1=SIMULATOR_DEFAULT_ADDRESS1,
        address2=SIMULATOR_DEFAULT_ADDRESS2,
        delivery_request=SIMULATOR_DEFAULT_REQUEST,
    )
    db.add(shipping)

    payment = Payment(
        order_id=order.id,
        provider=PaymentProvider.TOSS,
        payment_key=_generate_payment_key(order_no),
        provider_order_id=order_no,
        method="SIMULATOR",
        amount=total_payment_amount,
        status="APPROVED",
        approved_at=ordered_at,
        canceled_at=None,
        raw_response={
            "simulated": True,
            "order_no": order_no,
            "product_id": product.id,
            "product_code": product.product_code,
            "quantity": quantity,
        },
    )
    db.add(payment)

    return order, order_item


def _create_inventory_log(
    db: Session,
    *,
    product_id: int,
    qty_before: int,
    sold_qty: int,
    qty_after: int,
    order_item_id: int,
    buyer_id: int | None,
    occurred_at: datetime,
) -> None:
    inventory_log = InventoryLog(
        product_id=product_id,
        change_type=InventoryChangeType.ORDER_OUT,
        qty_before=qty_before,
        change_qty=sold_qty,
        qty_after=qty_after,
        related_order_item_id=order_item_id,
        note="판매 시뮬레이터 자동 주문",
        created_by=buyer_id,
        occurred_at=occurred_at,
    )
    db.add(inventory_log)


def _create_price_history_snapshot(
    db: Session,
    *,
    product: Product,
    latest_history: ProductPriceHistory | None,
    logged_at: datetime,
    previous_sale_price: int,
    applied_sale_price: int,
    sold_qty: int,
    remaining_stock: int,
) -> None:
    market_lowest_price = _simulate_market_lowest_price(
        product=product,
        latest_history=latest_history,
        applied_sale_price=applied_sale_price,
    )

    price_gap = applied_sale_price - market_lowest_price
    price_gap_rate = round((price_gap / market_lowest_price) * 100, 2) if market_lowest_price > 0 else 0

    pack_count = max(1, int(product.pack_count or 1))
    my_unit_sale_price = _normalize_unit_price(applied_sale_price, pack_count)
    market_pack_count = max(
        1,
        int(latest_history.market_pack_count or pack_count) if latest_history else pack_count,
    )
    market_unit_sale_price = _normalize_unit_price(market_lowest_price, market_pack_count)

    history = ProductPriceHistory(
        product_id=product.id,
        catalog_product_id=product.catalog_product_id,
        logged_at=logged_at,
        previous_sale_price=previous_sale_price,
        applied_sale_price=applied_sale_price,
        sales_qty=sold_qty,
        sales_per_hour=round(sold_qty / random.uniform(0.5, 1.5), 2),
        is_lowest_price=applied_sale_price <= market_lowest_price,
        market_lowest_price=market_lowest_price,
        price_gap=price_gap,
        price_gap_rate=price_gap_rate,
        min_price_limit=product.min_price_limit,
        max_price_limit=product.max_price_limit,
        remaining_stock=remaining_stock,
        my_pack_count=pack_count,
        my_unit_sale_price=my_unit_sale_price,
        market_pack_count=market_pack_count,
        market_unit_sale_price=market_unit_sale_price,
        change_source=PriceChangeSource.AI if product.ai_pricing_enabled else PriceChangeSource.MANUAL,
        changed_by=None,
        note="판매 시뮬레이터 자동 스냅샷",
    )
    db.add(history)


def _process_one_product_simulation(db: Session, product: Product) -> dict[str, int]:
    """
    상품 1건에 대해 판매/주문/결제/재고/가격이력을 함께 반영한다.
    반환값은 생성/변경 결과 요약.
    """
    current_stock = int(product.stock_qty or 0)
    if current_stock <= 0:
        return {
            "sold_qty": 0,
            "order_count": 0,
        }

    total_sold_qty = min(random.randint(-20, -1), current_stock)
    # if total_sold_qty <= 0:
    #     return {
    #         "sold_qty": 0,
    #         "order_count": 0,
    #     }

    previous_sale_price, applied_sale_price = _simulate_sale_price(product)
    product.sale_price = applied_sale_price
    product.unit_sale_price = _normalize_unit_price(applied_sale_price, int(product.pack_count or 1))

    latest_history = _get_latest_history(db, product.id)
    sale_chunks = _split_quantity(total_sold_qty)

    cycle_now = now_kst()
    created_order_count = 0

    for chunk_qty in sale_chunks:
        buyer = _select_simulation_member(db)

        qty_before = int(product.stock_qty or 0)
        qty_after = max(0, qty_before + chunk_qty)

        _, order_item = _create_order_bundle(
            db,
            buyer=buyer,
            product=product,
            quantity=chunk_qty,
            ordered_at=cycle_now,
        )

        product.stock_qty = qty_after
        if qty_after <= 0:
            product.sale_status = ProductSaleStatus.SOLD_OUT

        _create_inventory_log(
            db,
            product_id=product.id,
            qty_before=qty_before,
            sold_qty=chunk_qty,
            qty_after=qty_after,
            order_item_id=order_item.id,
            buyer_id=buyer.id,
            occurred_at=cycle_now,
        )

        created_order_count += 1

    _create_price_history_snapshot(
        db,
        product=product,
        latest_history=latest_history,
        logged_at=cycle_now,
        previous_sale_price=previous_sale_price,
        applied_sale_price=applied_sale_price,
        sold_qty=total_sold_qty,
        remaining_stock=int(product.stock_qty or 0),
    )

    return {
        "sold_qty": total_sold_qty,
        "order_count": created_order_count,
    }


def run_one_cycle_sync() -> dict[str, int]:
    """
    판매중(ON_SALE) 상품 전체를 한 번 순회한다.
    상품별로 주문/결제/재고/가격이력을 함께 생성한다.
    """
    db = SessionLocal()
    processed_count = 0
    updated_count = 0
    total_sold_qty = 0
    total_order_count = 0

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
                result = _process_one_product_simulation(db, product)
                db.commit()

                sold_qty = int(result["sold_qty"])
                order_count = int(result["order_count"])

                if sold_qty > 0:
                    updated_count += 1
                    total_sold_qty += sold_qty
                    total_order_count += order_count

                    logger.info(
                        (
                            "시뮬레이션 판매 반영 완료. "
                            "product_id=%s, product_code=%s, sold_qty=%s, order_count=%s, stock_qty=%s"
                        ),
                        product.id,
                        product.product_code,
                        sold_qty,
                        order_count,
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
            "total_order_count": total_order_count,
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
                    f"total_sold_qty={result['total_sold_qty']}, "
                    f"total_order_count={result['total_order_count']}"
                ),
            )

    except KeyboardInterrupt:
        logger.info("Ctrl+C 감지. 시뮬레이터를 종료합니다.")
    finally:
        stopped_at = now_kst()
        previous_state = _read_state()
        _clear_stop_request()
        _write_state(
            is_running=False,
            pid=None,
            started_at=started_at,
            stopped_at=stopped_at,
            last_cycle_at=(
                datetime.fromisoformat(previous_state["last_cycle_at"])
                if previous_state.get("last_cycle_at")
                else None
            ),
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