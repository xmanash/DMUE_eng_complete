import hmac
from typing import Optional

from app.core.config import settings


OPEN_PATHS = frozenset({"/", "/docs", "/redoc", "/openapi.json"})


def configured_api_key() -> str:
    return (settings.DMUE_API_KEY or "").strip()


def auth_required() -> bool:
    if settings.AUTH_REQUIRED:
        return True
    return settings.DMUE_ENV.lower() in {"staging", "production"}


def cors_origins() -> list[str]:
    raw = (settings.CORS_ALLOW_ORIGINS or "").strip()
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def extract_api_key(authorization: Optional[str], x_api_key: Optional[str]) -> str:
    if x_api_key and x_api_key.strip():
        return x_api_key.strip()
    if authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer" and value.strip():
            return value.strip()
    return ""


def key_matches(provided: str) -> bool:
    expected = configured_api_key()
    if not expected or not provided:
        return False
    return hmac.compare_digest(provided, expected)
