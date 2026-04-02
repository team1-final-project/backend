from sqlalchemy import Column, DateTime, Integer, String
from app.models.base import BaseModel


class EmailVerification(BaseModel):
    __tablename__ = "email_verification"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), nullable=False, index=True)
    purpose = Column(String(50), nullable=False, default="SIGNUP")
    code_hash = Column(String(255), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    verified_at = Column(DateTime, nullable=True)