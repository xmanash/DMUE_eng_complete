import time

from fastapi.testclient import TestClient

from app.core.cache import satellite_cache
from app.core.circuit import CircuitBreaker
from app.core.quote import quote_policy
from app.core.ratelimit import limiter
from app.core.satellite_processor import DISTRESSED_BBOX
from app.main import app


SAMPLE = {
    "policy_id": "POL-RT",
    "hard_brakes_per_100mi": 6,
    "night_miles_pct": 0.35,
    "speed_violations": 3,
    "total_miles": 450,
    "previous_premium": 120,
}


def test_rate_limit_returns_429():
    limiter.reset()
    limiter.per_minute = 1
    try:
        with TestClient(app) as client:
            first = client.get("/api/v1/jobs/does-not-exist")
            second = client.get("/api/v1/jobs/does-not-exist")
        assert first.status_code == 404
        assert second.status_code == 429
        assert second.headers.get("retry-after") == "60"
    finally:
        limiter.per_minute = 60
        limiter.reset()


def test_ingest_returns_202_then_job_done():
    limiter.reset()
    with TestClient(app) as client:
        posted = client.post("/api/v1/ingest", json=[SAMPLE])
        assert posted.status_code == 202
        job_id = posted.json()["job_id"]
        assert posted.json()["status"] == "queued"
        payload = None
        for _ in range(50):
            status = client.get(f"/api/v1/jobs/{job_id}")
            payload = status.json()
            if payload.get("status") in {"done", "failed"}:
                break
            time.sleep(0.05)
        assert payload is not None
        assert payload["status"] == "done"
        assert payload["count"] == 1
        assert payload["results"][0]["policy_id"] == "POL-RT"


def test_context_cache_hit():
    limiter.reset()
    with TestClient(app) as client:
        priced = client.post("/api/v1/reprice", json=SAMPLE)
        assert priced.status_code == 200
        first = client.get("/api/v1/policy/POL-RT/context")
        second = client.get("/api/v1/policy/POL-RT/context")
        assert first.status_code == 200
        assert first.json().get("cache_hit") is False
        assert second.json().get("cache_hit") is True


def test_open_circuit_skips_satellite(monkeypatch):
    satellite_cache.clear()
    calls = {"n": 0}

    def boom(self, bbox, crop_type="corn", live=False):
        calls["n"] += 1
        raise RuntimeError("satellite unavailable")

    monkeypatch.setattr(
        "app.core.quote.SentinelSatelliteRiskProcessor.evaluate_property_crop_risk",
        boom,
    )
    breaker = CircuitBreaker(failures=3, cooldown_seconds=60)
    payload = {**SAMPLE, "policy_id": "POL-CB", "bbox": list(DISTRESSED_BBOX)}
    for _ in range(3):
        quoted = quote_policy(payload, circuit=breaker)
        assert quoted["satellite"] is None
    assert calls["n"] == 3
    fourth = quote_policy(payload, circuit=breaker)
    assert fourth["satellite"] is None
    assert calls["n"] == 3
    assert any(
        item["name"] == "satellite_circuit" and item["action"] == "open"
        for item in fourth["decisions"]
    )
