import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.ratelimit import limiter
from app.main import app


def test_ops_open_without_api_key():
    limiter.reset()
    monkey_key = settings.DMUE_API_KEY
    try:
        settings.DMUE_API_KEY = ""
        with TestClient(app) as client:
            response = client.get("/api/v1/ops/status")
        assert response.status_code == 200
    finally:
        settings.DMUE_API_KEY = monkey_key


def test_api_key_required_when_configured():
    limiter.reset()
    previous = settings.DMUE_API_KEY
    try:
        settings.DMUE_API_KEY = "secret-demo"
        with TestClient(app) as client:
            denied = client.get("/api/v1/ops/status")
            allowed = client.get(
                "/api/v1/ops/status",
                headers={"X-API-Key": "secret-demo"},
            )
            bearer = client.get(
                "/api/v1/ops/status",
                headers={"Authorization": "Bearer secret-demo"},
            )
            health = client.get("/")
        assert denied.status_code == 401
        assert allowed.status_code == 200
        assert bearer.status_code == 200
        assert health.status_code == 200
        assert health.json()["status"] == "online"
    finally:
        settings.DMUE_API_KEY = previous


def test_production_startup_requires_key():
    previous_env = settings.DMUE_ENV
    previous_key = settings.DMUE_API_KEY
    previous_flag = settings.AUTH_REQUIRED
    try:
        settings.DMUE_ENV = "production"
        settings.DMUE_API_KEY = ""
        settings.AUTH_REQUIRED = False
        with pytest.raises(RuntimeError, match="DMUE_API_KEY"):
            with TestClient(app) as client:
                client.get("/")
    finally:
        settings.DMUE_ENV = previous_env
        settings.DMUE_API_KEY = previous_key
        settings.AUTH_REQUIRED = previous_flag
