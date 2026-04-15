from datetime import datetime

from sqlalchemy.orm import Session

from app.models.catalog_product import CatalogProduct


def get_catalog_product_by_external_catalog_id(
    db: Session,
    external_catalog_id: str,
) -> CatalogProduct | None:
    return (
        db.query(CatalogProduct)
        .filter(CatalogProduct.external_catalog_id == external_catalog_id)
        .first()
    )


def update_catalog_product_lowest_price(
    db: Session,
    catalog_product: CatalogProduct,
    lowest_price: int,
    checked_at: datetime | None = None,
) -> CatalogProduct:
    catalog_product.current_lowest_price = lowest_price
    catalog_product.current_lowest_price_at = checked_at or datetime.now()

    db.add(catalog_product)
    db.commit()
    db.refresh(catalog_product)
    return catalog_product