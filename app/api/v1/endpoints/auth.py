from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import (
    create_access_token,
    create_refresh_token,
    get_current_active_user,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.models.member import Member
from app.models.refresh_token import RefreshToken
from app.repositories.member_repository import (
    create_member,
    get_member_by_email,
    update_member,
)
from app.repositories.refresh_token_repository import (
    create_refresh_token as create_refresh_token_row,
    get_refresh_token_by_hash,
    update_refresh_token,
)
from app.schemas.auth import (
    AccessTokenResponse,
    LoginTokenResponse,
    RefreshTokenRequest,
)
from app.schemas.member import MemberResponse, MemberSignupRequest

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_TOKEN_EXPIRE_DAYS = 14


@router.post("/signup", response_model=MemberResponse, status_code=201)
def signup(
    payload: MemberSignupRequest,
    db: Session = Depends(get_db),
):
    existing_member = get_member_by_email(db, payload.email)
    if existing_member:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 가입된 이메일입니다.",
        )

    member = Member(
        email=payload.email,
        password=hash_password(payload.password),
        role="USER",
        social_type="LOCAL",
        social_id=None,
        name=payload.name,
        phone=payload.phone,
        status="ACTIVE",
    )

    return create_member(db, member)


@router.post("/login", response_model=LoginTokenResponse)
def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Session = Depends(get_db),
):
    member = get_member_by_email(db, form_data.username)

    if not member:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="이메일 또는 비밀번호가 올바르지 않습니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if member.social_type != "LOCAL":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="소셜 로그인 계정입니다. 소셜 로그인을 이용해주세요.",
        )

    if not member.password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="비밀번호가 설정되지 않은 계정입니다.",
        )

    if not verify_password(form_data.password, member.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="이메일 또는 비밀번호가 올바르지 않습니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if member.status != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="사용할 수 없는 계정입니다.",
        )

    access_token_expires = timedelta(
        minutes=settings.access_token_expire_minutes
    )
    access_token = create_access_token(
        data={"sub": member.email},
        expires_delta=access_token_expires,
    )

    refresh_token = create_refresh_token()
    refresh_token_hash = hash_refresh_token(refresh_token)

    refresh_token_row = RefreshToken(
        member_id=member.id,
        token_hash=refresh_token_hash,
        expires_at=(datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)).replace(tzinfo=None),
        revoked_at=None,
    )
    create_refresh_token_row(db, refresh_token_row)

    member.last_login_at = datetime.now(timezone.utc).replace(tzinfo=None)
    update_member(db, member)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }


@router.post("/refresh", response_model=AccessTokenResponse)
def refresh_access_token(
    payload: RefreshTokenRequest,
    db: Session = Depends(get_db),
):
    token_hash = hash_refresh_token(payload.refresh_token)
    token_row = get_refresh_token_by_hash(db, token_hash)

    if not token_row:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않은 리프레시 토큰입니다.",
        )

    if token_row.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="이미 만료된 리프레시 토큰입니다.",
        )

    if token_row.expires_at < datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="리프레시 토큰이 만료되었습니다.",
        )

    member = db.query(Member).filter(Member.id == token_row.member_id).first()
    if not member or member.status != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="사용할 수 없는 계정입니다.",
        )

    access_token_expires = timedelta(
        minutes=settings.access_token_expire_minutes
    )
    access_token = create_access_token(
        data={"sub": member.email},
        expires_delta=access_token_expires,
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
    }


@router.post("/logout")
def logout(
    payload: RefreshTokenRequest,
    db: Session = Depends(get_db),
):
    token_hash = hash_refresh_token(payload.refresh_token)
    token_row = get_refresh_token_by_hash(db, token_hash)

    if token_row and token_row.revoked_at is None:
        token_row.revoked_at = datetime.utcnow()
        update_refresh_token(db, token_row)

    return {"message": "로그아웃되었습니다."}


@router.get("/me", response_model=MemberResponse)
def read_users_me(
    current_user: Annotated[Member, Depends(get_current_active_user)],
):
    return current_user