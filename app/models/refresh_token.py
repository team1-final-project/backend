from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from app.models.base import BaseModel


class RefreshToken(BaseModel):
    __tablename__ = "refresh_token"

    id = Column(Integer, primary_key=True, index=True)
    member_id = Column(Integer, ForeignKey("member.id"), nullable=False, index=True)

    token_hash = Column(String(255), nullable=False, unique=True, index=True)

    expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime, nullable=True)