from datetime import datetime, timedelta, timezone

import jwt
from jwt.exceptions import InvalidTokenError

from app.core.config import settings


def create_signed_oauth_state(provider: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=10)
    payload = {
        "type": "oauth_state",
        "provider": provider,
        "exp": expire,
    }
    return jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def verify_signed_oauth_state(state: str, provider: str) -> bool:
    try:
        payload = jwt.decode(
            state,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        return (
            payload.get("type") == "oauth_state"
            and payload.get("provider") == provider
        )
    except InvalidTokenError:
        return False