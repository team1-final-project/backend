from sqlalchemy import Column, DateTime, func
from app.core.database import Base


class BaseModel(Base):
    __abstract__ = True

    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )