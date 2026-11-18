from fastapi.testclient import TestClient

from app.core.cost import cost_tracker
from app.core.observability import trace_store
from app.core.quote import quote_policy
from app.core.ratelimit import limiter
from app.core.satellite_processor import DISTRESSED_BBOX
from app.main import app


def test_ops_status_reports_environment_and_routes():
    limiter.reset()
    with TestClient(app) as client:
        response = client.get("/api/v1/ops/status")
    assert response.status_code == 200
    body = response.json()
    assert body["environment"]
    assert body["default_model_route"] == "dmue-full-v1"
    ids = {item["id"] for item in body["routes"]}
    assert {"dmue-rules-v1", "dmue-full-v1", "dmue-explain-v1"} <= ids
    assert body["observability"]["local"] is True
    assert body["observability"]["langsmith"] is False


def test_rules_route_skips_satellite():
    result = quote_policy(
        {
            "policy_id": "POL-RULES",
            "hard_brakes_per_100mi": 6,
            "night_miles_pct": 0.35,
            "speed_violations": 3,
            "total_miles": 10,
            "previous_premium": 120,
            "iot_moisture": 0.95,
            "bbox": list(DISTRESSED_BBOX),
            "model_route": "dmue-rules-v1",
        }
    )
    assert result["satellite"] is None
    assert result["model_route"] == "dmue-rules-v1"
    assert not any("Plant health" in line for line in result["attribution_reasons"])
    assert not any("moisture" in line.lower() for line in result["attribution_reasons"])
    assert result["cost"]["usd"] == 0.0002


def test_unknown_route_is_rejected():
    try:
        quote_policy(
            {
                "policy_id": "POL-BAD",
                "previous_premium": 120,
                "model_route": "not-a-route",
            }
        )
        raise AssertionError("unknown route was accepted")
    except ValueError as exc:
        assert "Unknown model_route" in str(exc)


def test_cost_tracker_records_quote():
    cost_tracker.reset()
    quote_policy(
        {
            "policy_id": "POL-COST",
            "hard_brakes_per_100mi": 0,
            "night_miles_pct": 0,
            "speed_violations": 0,
            "previous_premium": 120,
            "model_route": "dmue-full-v1",
        }
    )
    summary = cost_tracker.summary()
    assert summary["quotes"] >= 1
    assert summary["total_usd"] > 0
    assert "dmue-full-v1" in summary["by_route"]


def test_quote_emits_local_trace():
    trace_store.reset()
    result = quote_policy(
        {
            "policy_id": "POL-OBS",
            "hard_brakes_per_100mi": 0,
            "night_miles_pct": 0,
            "speed_violations": 0,
            "previous_premium": 120,
        }
    )
    assert result["trace_id"]
    recent = trace_store.list_recent(5)
    assert any(item["trace_id"] == result["trace_id"] for item in recent)
    assert any(item["policy_id"] == "POL-OBS" for item in recent)
