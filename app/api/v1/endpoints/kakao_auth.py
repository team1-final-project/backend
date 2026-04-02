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

router = APIRouter(prefix="/auth/kakao", tags=["kakao-auth"])


@router.get("/login")
def kakao_login():
    params = {
        "client_id": settings.kakao_rest_api_key,
        "redirect_uri": settings.kakao_redirect_uri,
        "response_type": "code",
        "prompt": "login",
    }

    kakao_auth_url = "https://kauth.kakao.com/oauth/authorize"
    return RedirectResponse(url=f"{kakao_auth_url}?{urlencode(params)}")


@router.get("/callback")
async def kakao_callback(
    code: str,
    db: Session = Depends(get_db),
):
    token_url = "https://kauth.kakao.com/oauth/token"

    token_payload = {
        "grant_type": "authorization_code",
        "client_id": settings.kakao_rest_api_key,
        "redirect_uri": settings.kakao_redirect_uri,
        "code": code,
    }

    if settings.kakao_client_secret:
        token_payload["client_secret"] = settings.kakao_client_secret

    async with httpx.AsyncClient(timeout=10.0) as client:
        token_response = await client.post(
            token_url,
            data=token_payload,
            headers={"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"},
        )

        if token_response.status_code != 200:
            raise HTTPException(status_code=400, detail="카카오 토큰 발급에 실패했습니다.")

        token_data = token_response.json()
        kakao_access_token = token_data.get("access_token")

        if not kakao_access_token:
            raise HTTPException(status_code=400, detail="카카오 access token이 없습니다.")

        userinfo_response = await client.get(
            "https://kapi.kakao.com/v2/user/me",
            headers={"Authorization": f"Bearer {kakao_access_token}"},
        )

        if userinfo_response.status_code != 200:
            raise HTTPException(status_code=400, detail="카카오 사용자 정보 조회에 실패했습니다.")

    userinfo = userinfo_response.json()

    social_id = str(userinfo.get("id"))
    kakao_account = userinfo.get("kakao_account") or {}
    profile = kakao_account.get("profile") or {}

    email = (kakao_account.get("email") or "").strip().lower()
    name = profile.get("nickname") or "Kakao User"

    if not social_id:
        raise HTTPException(status_code=400, detail="카카오 사용자 식별값이 없습니다.")

    if not email:
        raise HTTPException(
            status_code=400,
            detail="카카오 이메일 정보가 없습니다. 카카오 동의항목에서 이메일을 활성화해주세요.",
        )

    member = get_member_by_social(db, "KAKAO", social_id)

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
                social_type="KAKAO",
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
        url=f"{settings.frontend_kakao_callback_url}?{redirect_params}"
    )