from sqlalchemy import Column, DateTime, Enum as SqlEnum, Integer, String, UniqueConstraint
from app.models.base import BaseModel
from app.core.enums import MemberRole, MemberStatus, SocialType


class Member(BaseModel):
    __tablename__ = "member"

    __table_args__ = (
        UniqueConstraint("social_type", "social_id", name="uq_member_social_type_social_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password = Column(String(255), nullable=True)  # 해시 저장

    role = Column(SqlEnum(MemberRole, name="member_role_enum"), nullable=False, default=MemberRole.USER)
    social_type = Column(SqlEnum(SocialType, name="social_type_enum"), nullable=False, default=SocialType.LOCAL)
    social_id = Column(String(255), nullable=True)

    name = Column(String(100), nullable=False)
    phone = Column(String(20), nullable=True)

    status = Column(SqlEnum(MemberStatus, name="member_status_enum"), nullable=False, default=MemberStatus.ACTIVE)
    last_login_at = Column(DateTime, nullable=True)