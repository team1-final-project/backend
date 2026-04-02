from datetime import datetime, timedelta, timezone
from hashlib import sha256
from secrets import randbelow, token_urlsafe
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models.member import Member
from app.repositories.member_repository import get_member_by_email

password_hash = PasswordHash.recommended()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return password_hash.verify(plain_password, hashed_password)


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    to_encode.update({"exp": expire})

    return jwt.encode(
        to_encode,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def create_refresh_token() -> str:
    return token_urlsafe(48)


def hash_refresh_token(refresh_token: str) -> str:
    return sha256(refresh_token.encode("utf-8")).hexdigest()


def generate_email_code() -> str:
    return f"{randbelow(1_000_000):06d}"


def hash_text(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def create_email_signup_verification_token(email: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.email_signup_token_expire_minutes
    )
    payload = {
        "sub": email,
        "type": "signup_email_verification",
        "exp": expire,
    }
    return jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def verify_email_signup_verification_token(token: str, email: str) -> bool:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        return (
            payload.get("sub") == email
            and payload.get("type") == "signup_email_verification"
        )
    except InvalidTokenError:
        return False


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Session = Depends(get_db),
) -> Member:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="인증 정보를 확인할 수 없습니다.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        email: str | None = payload.get("sub")
        if email is None:
            raise credentials_exception
    except InvalidTokenError:
        raise credentials_exception

    member = get_member_by_email(db, email)
    if member is None:
        raise credentials_exception

    return member


async def get_current_active_user(
    current_user: Annotated[Member, Depends(get_current_user)],
) -> Member:
    if current_user.status != "ACTIVE":
        raise HTTPException(status_code=403, detail="비활성화된 계정입니다.")
    return current_user