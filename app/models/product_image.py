from sqlalchemy import Boolean, Column, Enum as SqlEnum, ForeignKey, Integer, String
from app.core.enums import ImageType
from app.models.base import BaseModel


class ProductImage(BaseModel):
    __tablename__ = "product_image"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("product.id"), nullable=False, index=True)
    image_type = Column(
        SqlEnum(ImageType, name="image_type_enum"),
        nullable=False,
    )
    image_url = Column(String(500), nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)