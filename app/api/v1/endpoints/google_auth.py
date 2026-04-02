from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_refresh_token,
)
from app.models.member import Member
from app.models.refresh_token import RefreshToken
from app.repositories.member_repository import (
    create_member,
    get_member_by_email,
    get_member_by_social,
    update_member,
)
from app.repositories.refresh_token_repository import (
    create_refresh_token as create_refresh_token_row,
)

router = APIRouter(prefix="/auth/google", tags=["google-auth"])


@router.get("/login")
def google_login():
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "consent",
    }

    google_auth_url = "https://accounts.google.com/o/oauth2/v2/auth"
    return RedirectResponse(url=f"{google_auth_url}?{urlencode(params)}")


@router.get("/callback")
async def google_callback(
    code: str,
    db: Session = Depends(get_db),
):
    token_url = "https://oauth2.googleapis.com/token"

    async with httpx.AsyncClient(timeout=10.0) as client:
        token_response = await client.post(
            token_url,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": settings.google_redirect_uri,
                "grant_type": "authorization_code",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        if token_response.status_code != 200:
            raise HTTPException(status_code=400, detail="구글 토큰 발급에 실패했습니다.")

        token_data = token_response.json()
        google_access_token = token_data.get("access_token")

        if not google_access_token:
            raise HTTPException(status_code=400, detail="구글 access token이 없습니다.")

        userinfo_response = await client.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {google_access_token}"},
        )

        if userinfo_response.status_code != 200:
            raise HTTPException(status_code=400, detail="구글 사용자 정보 조회에 실패했습니다.")

    userinfo = userinfo_response.json()

    social_id = userinfo.get("sub")
    email = (userinfo.get("email") or "").strip().lower()
    name = userinfo.get("name") or "Google User"

    if not social_id or not email:
        raise HTTPException(status_code=400, detail="구글 사용자 정보가 올바르지 않습니다.")

    member = get_member_by_social(db, "GOOGLE", social_id)

    if not member:
        member = get_member_by_email(db, email)

        if member:
            if member.social_type == "LOCAL":
                raise HTTPException(
                    status_code=409,
                    detail="이미 일반 회원가입된 이메일입니다. 일반 로그인으로 이용해주세요.",
                )
        else:
            member = Member(
                email=email,
                password=None,
                role="USER",
                social_type="GOOGLE",
                social_id=social_id,
                name=name,
                phone=None,
                status="ACTIVE",
            )
            member = create_member(db, member)

    access_token = create_access_token(
        data={"sub": member.email},
        expires_delta=timedelta(minutes=settings.access_token_expire_minutes),
    )

    refresh_token = create_refresh_token()
    refresh_token_hash = hash_refresh_token(refresh_token)

    refresh_token_row = RefreshToken(
        member_id=member.id,
        token_hash=refresh_token_hash,
        expires_at=(
            datetime.now(timezone.utc)
            + timedelta(days=settings.refresh_token_expire_days)
        ).replace(tzinfo=None),
        revoked_at=None,
    )
    create_refresh_token_row(db, refresh_token_row)

    member.last_login_at = datetime.utcnow()
    update_member(db, member)

    redirect_params = urlencode(
        {
            "access_token": access_token,
            "refresh_token": refresh_token,
        }
    )

    return RedirectResponse(
        url=f"{settings.frontend_google_callback_url}?{redirect_params}"
    )