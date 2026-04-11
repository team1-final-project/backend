from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.repositories.category_repository import get_active_categories
from app.schemas.category import MainCategoryResponse, SubCategoryResponse

router = APIRouter(prefix="/categories", tags=["categories"])


@router.get("", response_model=list[MainCategoryResponse])
def read_categories(db: Session = Depends(get_db)):
    categories = get_active_categories(db)

    main_categories = [category for category in categories if category.level == 1]
    sub_categories = [category for category in categories if category.level == 2]

    sub_category_map: dict[int, list[SubCategoryResponse]] = {}

    for sub_category in sub_categories:
        if sub_category.parent_id is None:
            continue

        sub_category_map.setdefault(sub_category.parent_id, []).append(
            SubCategoryResponse(
                id=sub_category.id,
                name=sub_category.name,
            )
        )

    result = []
    for main_category in main_categories:
        result.append(
            MainCategoryResponse(
                id=main_category.id,
                name=main_category.name,
                subCategories=sub_category_map.get(main_category.id, []),
            )
        )

    return result