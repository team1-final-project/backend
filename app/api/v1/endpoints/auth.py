from datetime import timedelta
from app.core.timezone import now_kst

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import (
    create_access_token,
    create_email_signup_verification_token,
    create_refresh_token,
    generate_email_code,
    get_current_active_user,
    hash_password,
    hash_refresh_token,
    hash_text,
    verify_email_signup_verification_token,
    verify_password,
)
from app.models.email_verification import EmailVerification
from app.models.member import Member
from app.models.refresh_token import RefreshToken
from app.repositories.email_verification_repository import (
    create_email_verification,
    get_latest_pending_verification,
    update_email_verification,
)
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
    SendEmailCodeRequest,
    VerifyEmailCodeRequest,
    VerifyEmailCodeResponse,
)
from app.schemas.member import MemberResponse, MemberSignupRequest
from app.services.mail_service import send_signup_verification_email

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/email/send-code")
def send_signup_email_code(
    payload: SendEmailCodeRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    existing_member = get_member_by_email(db, payload.email)
    if existing_member:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 가입된 이메일입니다.",
        )

    code = generate_email_code()

    verification = EmailVerification(
        email=payload.email.strip().lower(),
        purpose="SIGNUP",
        code_hash=hash_text(code),
        expires_at=now_kst() + timedelta(minutes=settings.email_code_expire_minutes),
        verified_at=None,
    )
    create_email_verification(db, verification)

    background_tasks.add_task(
        send_signup_verification_email,
        payload.email.strip().lower(),
        code,
    )

    return {"message": "인증코드 발송을 요청했습니다."}


@router.post("/email/verify-code", response_model=VerifyEmailCodeResponse)
def verify_signup_email_code(
    payload: VerifyEmailCodeRequest,
    db: Session = Depends(get_db),
):
    verification = get_latest_pending_verification(
        db,
        payload.email,
        "SIGNUP",
    )

    if not verification:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="유효한 인증 요청이 없습니다.",
        )

    if verification.expires_at < now_kst():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="인증코드가 만료되었습니다.",
        )

    if verification.code_hash != hash_text(payload.code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="인증코드가 올바르지 않습니다.",
        )

    verification.verified_at = now_kst()
    update_email_verification(db, verification)

    verification_token = create_email_signup_verification_token(payload.email)

    return {
        "message": "이메일 인증이 완료되었습니다.",
        "verification_token": verification_token,
    }


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

    if not verify_email_signup_verification_token(
        payload.verification_token,
        payload.email,
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="이메일 인증이 완료되지 않았습니다.",
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
    form_data: OAuth2PasswordRequestForm = Depends(),
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

    if token_row.expires_at < now_kst():
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

    access_token = create_access_token(
        data={"sub": member.email},
        expires_delta=timedelta(minutes=settings.access_token_expire_minutes),
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
        token_row.revoked_at = now_kst()
        update_refresh_token(db, token_row)

    return {"message": "로그아웃되었습니다."}


@router.get("/me", response_model=MemberResponse)
def read_users_me(
    current_user: Member = Depends(get_current_active_user),
):
    return current_user