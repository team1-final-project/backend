from sqlalchemy import Column, DateTime
from app.core.database import Base
from app.core.timezone import now_kst


class BaseModel(Base):
    __abstract__ = True

    created_at = Column(DateTime, default=now_kst, nullable=False)
    updated_at = Column(DateTime, default=now_kst, onupdate=now_kst, nullable=False)