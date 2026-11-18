"""API-key checks for /api/v1. Health and OpenAPI stay open."""

import hmac
import os
from typing import Optional

from app.core.config import settings


OPEN_PATHS = frozenset({"/", "/docs", "/redoc", "/openapi.json"})


def configured_api_key() -> str:
    return (settings.DMUE_API_KEY or "").strip()


def auth_required() -> bool:
    if settings.AUTH_REQUIRED:
        return True
    return settings.DMUE_ENV.lower() in {"staging", "production"}


def github_codespace_origins() -> list[str]:
    """HTTPS origins GitHub forwards for this Codespace (API and console ports)."""
    name = (os.getenv("CODESPACE_NAME") or "").strip()
    domain = (os.getenv("GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN") or "").strip()
    if not name or not domain:
        return []
    return [f"https://{name}-{port}.{domain}" for port in (8000, 8501)]


def cors_origins() -> list[str]:
    raw = (settings.CORS_ALLOW_ORIGINS or "").strip()
    items = [item.strip() for item in raw.split(",") if item.strip()] if raw else []
    seen = set(items)
    for origin in github_codespace_origins():
        if origin not in seen:
            items.append(origin)
            seen.add(origin)
    return items


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
