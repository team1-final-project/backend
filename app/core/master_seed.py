from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.brand import Brand
from app.models.category import Category

CATEGORY_SEED_DATA = [
    {
        "id": 101,
        "parent_id": None,
        "name": "가공 / 간편식품",
        "level": 1,
        "full_path": "가공 / 간편식품",
        "sort_order": 1,
        "is_active": True,
    },
    {
        "id": 102,
        "parent_id": None,
        "name": "간식 / 음료",
        "level": 1,
        "full_path": "간식 / 음료",
        "sort_order": 2,
        "is_active": True,
    },
    {
        "id": 103,
        "parent_id": None,
        "name": "냉장 / 육가공",
        "level": 1,
        "full_path": "냉장 / 육가공",
        "sort_order": 3,
        "is_active": True,
    },
    {
        "id": 111,
        "parent_id": 101,
        "name": "라면",
        "level": 2,
        "full_path": "가공 / 간편식품 > 라면",
        "sort_order": 1,
        "is_active": True,
    },
    {
        "id": 112,
        "parent_id": 101,
        "name": "즉석식품",
        "level": 2,
        "full_path": "가공 / 간편식품 > 즉석식품",
        "sort_order": 2,
        "is_active": True,
    },
    {
        "id": 113,
        "parent_id": 101,
        "name": "카레",
        "level": 2,
        "full_path": "가공 / 간편식품 > 카레",
        "sort_order": 3,
        "is_active": True,
    },
    {
        "id": 121,
        "parent_id": 102,
        "name": "스낵과자",
        "level": 2,
        "full_path": "간식 / 음료 > 스낵과자",
        "sort_order": 1,
        "is_active": True,
    },
    {
        "id": 122,
        "parent_id": 102,
        "name": "탄산음료",
        "level": 2,
        "full_path": "간식 / 음료 > 탄산음료",
        "sort_order": 2,
        "is_active": True,
    },
    {
        "id": 131,
        "parent_id": 103,
        "name": "소시지",
        "level": 2,
        "full_path": "냉장 / 육가공 > 소시지",
        "sort_order": 1,
        "is_active": True,
    },
]

BRAND_SEED_DATA = [
    {"id": 201, "name": "팔도", "is_active": True},
    {"id": 202, "name": "코카콜라", "is_active": True},
    {"id": 203, "name": "롯데", "is_active": True},
    {"id": 204, "name": "삼양", "is_active": True},
    {"id": 205, "name": "오뚜기", "is_active": True},
    {"id": 206, "name": "농심", "is_active": True},
    {"id": 207, "name": "오리온", "is_active": True},
]


def _seed_categories(db: Session) -> None:
    for item in CATEGORY_SEED_DATA:
        exists = db.get(Category, item["id"])
        if exists:
            continue

        db.add(Category(**item))


def _seed_brands(db: Session) -> None:
    for item in BRAND_SEED_DATA:
        exists = db.get(Brand, item["id"])
        if exists:
            continue

        db.add(Brand(**item))


def seed_master_data() -> None:
    db = SessionLocal()
    try:
        _seed_categories(db)
        _seed_brands(db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()