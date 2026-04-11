from sqlalchemy.orm import Session

from app.models.category import Category


def get_active_categories(db: Session) -> list[Category]:
    return (
        db.query(Category)
        .filter(Category.is_active.is_(True))
        .order_by(Category.level.asc(), Category.sort_order.asc(), Category.id.asc())
        .all()
    )