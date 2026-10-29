import json

import pytest

from app.core.evals import evaluate_explanation, policyholder_text, prohibited_term_leak_count
from app.core.guardrails import ActuarialGuardrailEnforcer
from app.core.quote import quote_policy
from app.core.risk_engine import DynamicRiskEngine
from app.core.satellite_processor import DISTRESSED_BBOX, HEALTHY_BBOX, SentinelSatelliteRiskProcessor
from app.mcp_server.server import handle_mcp_request


def test_tc01_moderate_risk_premium_matches_multiplier():
    engine = DynamicRiskEngine(base_premium=120.0)
    telemetry = {
        "hard_brakes_per_100mi": 6,
        "night_miles_pct": 0.35,
        "speed_violations": 3,
    }
    score, raw_prem, reasons = engine.calculate_auto_telemetry_score(telemetry)
    assert score > 50.0
    assert raw_prem > 120.0
    expected = 120.0 * (0.7 + (score / 100.0) * 0.8)
    assert raw_prem == pytest.approx(expected)
    assert len(reasons) == 3


def test_tc02_actuarial_guardrail_cap():
    guardrails = ActuarialGuardrailEnforcer()
    final_prem, clamped, reason = guardrails.enforce_rate_caps(150.0, 100.0)
    assert final_prem == 125.0
    assert clamped is True
    assert "Capped at max" in reason


def test_tc03_satellite_drought_and_healthy_canopy():
    processor = SentinelSatelliteRiskProcessor()
    drought = processor.evaluate_property_crop_risk(DISTRESSED_BBOX)
    assert drought["ndvi_index"] < 0.30
    assert drought["crop_risk_score"] == pytest.approx(75.0)
    assert drought["risk_delta"] == pytest.approx(25.0)
    assert "ndwi_index" in drought

    healthy = processor.evaluate_property_crop_risk(HEALTHY_BBOX)
    assert healthy["ndvi_index"] >= 0.45
    assert healthy["sentinel_live_fetch"] is False


def test_guardrail_excludes_hard_brake_spike():
    guardrails = ActuarialGuardrailEnforcer()
    cleaned, anomalies = guardrails.filter_anomalies(
        {
            "policy_id": "POL-1",
            "hard_brakes_per_100mi": 25,
            "night_miles_pct": 0.1,
            "speed_violations": 0,
            "total_miles": 10,
            "previous_premium": 100,
        }
    )
    assert cleaned["hard_brakes_per_100mi"] <= 20
    assert any("malfunction" in item.lower() for item in anomalies)

    engine = DynamicRiskEngine()
    _score, _prem, reasons = engine.calculate_auto_telemetry_score(cleaned)
    assert not any("hard braking" in reason.lower() for reason in reasons)


def test_guardrail_rejects_impossible_night_ratio():
    guardrails = ActuarialGuardrailEnforcer()
    with pytest.raises(ValueError):
        guardrails.filter_anomalies(
            {
                "policy_id": "POL-1",
                "hard_brakes_per_100mi": 1,
                "night_miles_pct": 1.5,
                "speed_violations": 0,
                "total_miles": 10,
                "previous_premium": 100,
            }
        )


def test_guardrail_rejects_prohibited_key_and_word():
    guardrails = ActuarialGuardrailEnforcer()
    with pytest.raises(ValueError, match="Prohibited factor"):
        guardrails.reject_prohibited_keys(
            {"policy_id": "POL-1", "previous_premium": 100, "gender": "ignored"}
        )
    with pytest.raises(ValueError, match="leaked"):
        guardrails.assert_no_prohibited_language(
            "The rate uses gender and a credit score."
        )
    assert prohibited_term_leak_count("zip code and zipcode") == 2


def test_evals_on_standard_reason_text():
    engine = DynamicRiskEngine(base_premium=120.0)
    _score, _raw, reasons = engine.calculate_auto_telemetry_score(
        {
            "hard_brakes_per_100mi": 6,
            "night_miles_pct": 0.35,
            "speed_violations": 3,
        }
    )
    text = policyholder_text(reasons)
    result = evaluate_explanation(text, reasons)
    assert result["prohibited_term_leaks"] == 0
    assert result["factor_coverage"] >= 0.50
    assert result["flesch_reading_ease"] >= 60
    assert result["flesch_grade_level"] <= 8
    assert result["passed"] is True


def test_quote_keeps_auto_score_without_optional_signals():
    result = quote_policy(
        {
            "policy_id": "POL-98234",
            "hard_brakes_per_100mi": 6,
            "night_miles_pct": 0.35,
            "speed_violations": 3,
            "total_miles": 450,
            "previous_premium": 120,
        }
    )
    assert result["risk_score"] > 50
    assert result["raw_premium"] > 120
    assert result["satellite"] is None
    assert result["evals"]["passed"] is True
    assert result["recommendations"]


def test_environment_signals_raise_score():
    engine = DynamicRiskEngine(base_premium=120.0)
    base_score, _raw, reasons = engine.calculate_auto_telemetry_score(
        {"hard_brakes_per_100mi": 0, "night_miles_pct": 0, "speed_violations": 0}
    )
    score, raw, updated = engine.apply_environment_signals(
        base_score,
        {"iot_moisture": 0.9, "weather_wind_mph": 45, "weather_precip_mm": 60},
        reasons,
    )
    assert score == pytest.approx(base_score + 8 + 8 + 6)
    assert raw > _raw
    assert len(updated) == len(reasons) + 3


def test_tc04_memory_persists_and_filters_policy(tmp_path):
    from app.core.memory import PolicyMemoryManager

    manager = PolicyMemoryManager(persist_dir=str(tmp_path / "chroma"))
    manager.record_underwriting_event(
        "POL-98234",
        65.0,
        134.40,
        ["Hard braking is frequent at 6 events per 100 miles."],
    )
    context = manager.get_policy_context("POL-98234")
    assert context["metadatas"]
    assert context["metadatas"][0]["policy_id"] == "POL-98234"
    assert "POL-98234" in context["documents"][0]
    assert context["ids"][0].startswith("POL-98234_")

    other = manager.get_policy_context("POL-00000")
    assert other["ids"] == []


def test_tc05_mcp_reprice_returns_jsonrpc_premium():
    request = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {
                "name": "reprice_policy_micro_underwrite",
                "arguments": {
                    "policy_id": "POL-98234",
                    "hard_brakes_per_100mi": 6,
                    "night_miles_pct": 0.35,
                    "speed_violations": 3,
                    "previous_premium": 120,
                },
            },
        }
    )
    response = json.loads(handle_mcp_request(request))
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == 7
    assert "error" not in response
    body = json.loads(response["result"]["content"][0]["text"])
    assert "final_bounded_premium" in body
    assert body["raw_calculated_premium"] > 120
    assert body["policy_id"] == "POL-98234"
