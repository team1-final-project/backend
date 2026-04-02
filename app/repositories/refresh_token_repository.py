from datetime import datetime

from sqlalchemy.orm import Session
from app.models.refresh_token import RefreshToken


def create_refresh_token(db: Session, refresh_token: RefreshToken) -> RefreshToken:
    db.add(refresh_token)
    db.commit()
    db.refresh(refresh_token)
    return refresh_token


def get_refresh_token_by_hash(db: Session, token_hash: str) -> RefreshToken | None:
    return (
        db.query(RefreshToken)
        .filter(RefreshToken.token_hash == token_hash)
        .first()
    )


def update_refresh_token(db: Session, refresh_token: RefreshToken) -> RefreshToken:
    db.add(refresh_token)
    db.commit()
    db.refresh(refresh_token)
    return refresh_token


def revoke_all_refresh_tokens_by_member_id(db: Session, member_id: int):
    tokens = db.query(RefreshToken).filter(
        RefreshToken.member_id == member_id,
        RefreshToken.revoked_at.is_(None),
    ).all()

    now = datetime.utcnow()
    for token in tokens:
        token.revoked_at = now
        db.add(token)

    db.commit()