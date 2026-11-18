import httpx
import pytest

from app.core.cache import satellite_cache
from app.core.config import settings
from app.core.quote import quote_policy
from app.core.satellite_processor import (
    DISTRESSED_BBOX,
    SentinelSatelliteRiskProcessor,
    reset_oauth_cache,
    should_use_live_sentinel,
)


def _json_response(url: str, payload: dict, status: int = 200) -> httpx.Response:
    request = httpx.Request("POST", url)
    return httpx.Response(status, json=payload, request=request)


def _stats_body(ndvi: float, ndwi: float) -> dict:
    return {
        "data": [
            {
                "outputs": {
                    "ndvi": {"bands": {"B0": {"stats": {"mean": ndvi, "sampleCount": 12}}}},
                    "ndwi": {"bands": {"B0": {"stats": {"mean": ndwi, "sampleCount": 12}}}},
                }
            }
        ]
    }


@pytest.fixture
def live_settings(monkeypatch):
    monkeypatch.setattr(settings, "SENTINEL_LIVE_FETCH", True)
    monkeypatch.setattr(settings, "SENTINEL_CLIENT_ID", "demo-client")
    monkeypatch.setattr(settings, "SENTINEL_CLIENT_SECRET", "demo-secret")
    reset_oauth_cache()
    satellite_cache.clear()
    yield
    reset_oauth_cache()
    satellite_cache.clear()


def test_live_fetch_uses_hub_means(monkeypatch, live_settings):
    calls = []

    def fake_post(url, **kwargs):
        calls.append(url)
        if "openid-connect" in url or "/token" in url:
            return _json_response(url, {"access_token": "hub-token", "expires_in": 3600})
        return _json_response(url, _stats_body(0.12, -0.05))

    monkeypatch.setattr("app.core.satellite_processor.httpx.post", fake_post)
    result = SentinelSatelliteRiskProcessor().evaluate_property_crop_risk(
        DISTRESSED_BBOX, live=True
    )
    assert result["sentinel_live_fetch"] is True
    assert result["satellite_source"] == "sentinel_hub_s2l2a"
    assert result["ndvi_index"] == pytest.approx(0.12)
    assert result["ndwi_index"] == pytest.approx(-0.05)
    assert result["risk_delta"] == pytest.approx(25.0)
    assert any("statistics" in url for url in calls)
    quoted = quote_policy(
        {
            "policy_id": "POL-LIVE",
            "hard_brakes_per_100mi": 1,
            "night_miles_pct": 0.1,
            "speed_violations": 0,
            "previous_premium": 120,
            "bbox": list(DISTRESSED_BBOX),
            "sentinel_live": True,
        }
    )
    assert quoted["satellite"]["sentinel_live_fetch"] is True
    assert quoted["satellite"]["ndvi_index"] == pytest.approx(0.12)


def test_hub_401_falls_back_to_local(monkeypatch, live_settings):
    def fake_post(url, **kwargs):
        request = httpx.Request("POST", url)
        return httpx.Response(401, json={"error": "invalid_client"}, request=request)

    monkeypatch.setattr("app.core.satellite_processor.httpx.post", fake_post)
    result = SentinelSatelliteRiskProcessor().evaluate_property_crop_risk(
        DISTRESSED_BBOX, live=True
    )
    assert result["sentinel_live_fetch"] is False
    assert result["satellite_source"] == "local_fallback"
    assert result["sentinel_live_error"] == "unauthorized"
    assert result["ndvi_index"] < 0.30
    quoted = quote_policy(
        {
            "policy_id": "POL-LIVE-401",
            "hard_brakes_per_100mi": 1,
            "night_miles_pct": 0.1,
            "speed_violations": 0,
            "previous_premium": 120,
            "bbox": list(DISTRESSED_BBOX),
            "sentinel_live": True,
        }
    )
    assert quoted["satellite"]["satellite_source"] == "local_fallback"
    assert quoted["satellite"]["ndvi_index"] < 0.30


def test_hub_timeout_falls_back_to_local(monkeypatch, live_settings):
    def fake_post(url, **kwargs):
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr("app.core.satellite_processor.httpx.post", fake_post)
    result = SentinelSatelliteRiskProcessor().evaluate_property_crop_risk(
        DISTRESSED_BBOX, live=True
    )
    assert result["satellite_source"] == "local_fallback"
    assert result["sentinel_live_error"] == "timeout"
    assert result["ndvi_index"] < 0.30


def test_default_stays_local_without_live_flag():
    assert should_use_live_sentinel(None) is False
    drought = SentinelSatelliteRiskProcessor().evaluate_property_crop_risk(DISTRESSED_BBOX)
    assert drought["sentinel_live_fetch"] is False
    assert drought["satellite_source"] == "deterministic_bbox_bands"
