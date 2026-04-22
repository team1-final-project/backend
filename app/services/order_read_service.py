from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models.order import Order


def _to_status_text(raw_status):
    if raw_status is None:
        return "PENDING"
    if hasattr(raw_status, "value"):
        return str(raw_status.value)
    return str(raw_status)


def get_my_orders(db: Session, member_id: int):
    stmt = (
        select(Order)
        .where(Order.member_id == member_id)
        .order_by(desc(Order.id))
    )

    orders = db.execute(stmt).scalars().all()

    items = []
    for order in orders:
        items.append(
            {
                "id": order.id,
                "order_number": order.order_no,
                "status": _to_status_text(
                    getattr(order, "order_status", None)
                    or getattr(order, "payment_status", None)
                    or getattr(order, "status", None)
                ),
                "total_product_amount": int(order.total_product_amount or 0),
                "total_shipping_fee": int(order.total_shipping_fee or 0),
                "total_payment_amount": int(order.total_payment_amount or 0),
                "ordered_at": order.ordered_at,
            }
        )

    return {
        "items": items,
        "total_count": len(items),
    }