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
                "order_number": getattr(order, "order_number", f"ORDER-{order.id}"),
                "status": _to_status_text(
                    getattr(order, "order_status", None)
                    or getattr(order, "status", None)
                    or getattr(order, "payment_status", None)
                ),
                "total_amount": int(
                    getattr(order, "total_amount", None)
                    or getattr(order, "final_amount", None)
                    or getattr(order, "amount", None)
                    or 0
                ),
                "created_at": getattr(order, "created_at", None),
            }
        )

    return {
        "items": items,
        "total_count": len(items),
    }