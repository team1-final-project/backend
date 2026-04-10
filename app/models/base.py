from sqlalchemy import Column, DateTime
from sqlalchemy.orm import declarative_mixin

from app.core.database import Base
from app.core.timezone import now_kst


@declarative_mixin
class TimestampMixin:
    created_at = Column(DateTime, nullable=False, default=now_kst)
    updated_at = Column(DateTime, nullable=False, default=now_kst, onupdate=now_kst)


class BaseModel(Base, TimestampMixin):
    __abstract__ = True