from datetime import datetime
from pydantic import BaseModel, ConfigDict, EmailStr


class MemberSignupRequest(BaseModel):
    email: EmailStr
    password: str
    name: str
    phone: str | None = None


class MemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    role: str
    social_type: str
    social_id: str | None = None
    name: str
    phone: str | None = None
    status: str
    last_login_at: datetime | None = None
    created_at: datetime
    updated_at: datetime