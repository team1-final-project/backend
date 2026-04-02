from sqlalchemy import Column, DateTime, Integer, String
from app.models.base import BaseModel


class Member(BaseModel):
    __tablename__ = "member"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password = Column(String(255), nullable=True)  # 해시 저장

    role = Column(String(20), nullable=False, default="USER")
    social_type = Column(String(20), nullable=False, default="LOCAL")
    social_id = Column(String(255), unique=True, nullable=True)

    name = Column(String(100), nullable=False)
    phone = Column(String(20), nullable=True)

    status = Column(String(20), nullable=False, default="ACTIVE")
    last_login_at = Column(DateTime, nullable=True)