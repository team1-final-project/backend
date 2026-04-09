from sqlalchemy import Column, DateTime, Enum as SqlEnum, Integer, String
from app.models.base import BaseModel
from app.core.enums import VerificationPurpose


class EmailVerification(BaseModel):
    __tablename__ = "email_verification"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), nullable=False, index=True)
    purpose = Column(
        SqlEnum(VerificationPurpose, name="verification_purpose_enum"),
        nullable=False,
        default=VerificationPurpose.SIGNUP,
    )
    code_hash = Column(String(255), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    verified_at = Column(DateTime, nullable=True)