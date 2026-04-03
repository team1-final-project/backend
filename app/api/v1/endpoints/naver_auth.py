from datetime import timedelta
from app.core.timezone import now_kst
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.oauth_state import (
    create_signed_oauth_state,
    verify_signed_oauth_state,
)
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

router = APIRouter(prefix="/auth/naver", tags=["naver-auth"])


@router.get("/login")
def naver_login():
    state = create_signed_oauth_state("NAVER")

    params = {
        "response_type": "code",
        "client_id": settings.naver_client_id,
        "redirect_uri": settings.naver_redirect_uri,
        "state": state,
    }

    naver_auth_url = "https://nid.naver.com/oauth2.0/authorize"
    return RedirectResponse(url=f"{naver_auth_url}?{urlencode(params)}")


@router.get("/callback")
async def naver_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: Session = Depends(get_db),
):
    if not verify_signed_oauth_state(state, "NAVER"):
        raise HTTPException(status_code=401, detail="유효하지 않은 state 값입니다.")

    token_url = "https://nid.naver.com/oauth2.0/token"

    async with httpx.AsyncClient(timeout=10.0) as client:
        token_response = await client.get(
            token_url,
            params={
                "grant_type": "authorization_code",
                "client_id": settings.naver_client_id,
                "client_secret": settings.naver_client_secret,
                "code": code,
                "state": state,
            },
        )

        if token_response.status_code != 200:
            raise HTTPException(status_code=400, detail="네이버 토큰 발급에 실패했습니다.")

        token_data = token_response.json()
        naver_access_token = token_data.get("access_token")

        if not naver_access_token:
            raise HTTPException(status_code=400, detail="네이버 access token이 없습니다.")

        profile_response = await client.get(
            "https://openapi.naver.com/v1/nid/me",
            headers={"Authorization": f"Bearer {naver_access_token}"},
        )

        if profile_response.status_code != 200:
            raise HTTPException(status_code=400, detail="네이버 사용자 정보 조회에 실패했습니다.")

    profile_data = profile_response.json()
    response = profile_data.get("response") or {}

    social_id = response.get("id")
    email = (response.get("email") or "").strip().lower()
    name = response.get("name") or response.get("nickname") or "Naver User"

    if not social_id:
        raise HTTPException(status_code=400, detail="네이버 사용자 식별값이 없습니다.")

    if not email:
        raise HTTPException(
            status_code=400,
            detail="네이버 이메일 정보가 없습니다. 네이버 로그인에서 이메일 제공 설정을 확인해주세요.",
        )

    member = get_member_by_social(db, "NAVER", social_id)

    if not member:
        member = get_member_by_email(db, email)

        if member:
            if member.social_type == "LOCAL":
                raise HTTPException(
                    status_code=409,
                    detail="이미 일반 회원가입된 이메일입니다. 일반 로그인을 이용해주세요.",
                )
        else:
            member = Member(
                email=email,
                password=None,
                role="USER",
                social_type="NAVER",
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
        expires_at=now_kst() + timedelta(days=settings.refresh_token_expire_days),
        revoked_at=None,
    )
    create_refresh_token_row(db, refresh_token_row)

    member.last_login_at = now_kst()
    update_member(db, member)

    redirect_params = urlencode(
        {
            "access_token": access_token,
            "refresh_token": refresh_token,
        }
    )

    return RedirectResponse(
        url=f"{settings.frontend_naver_callback_url}?{redirect_params}"
    )