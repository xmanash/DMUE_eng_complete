"""Offline acceptance cases. No network. Exit 0 only if every case passes."""

import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List

from app.core.evals import evaluate_explanation, policyholder_text
from app.core.guardrails import ActuarialGuardrailEnforcer
from app.core.memory import PolicyMemoryManager
from app.core.risk_engine import DynamicRiskEngine
from app.core.satellite_processor import DISTRESSED_BBOX, SentinelSatelliteRiskProcessor
from app.mcp_server.server import handle_mcp_request


def _case(case_id: str, fn: Callable[[], None]) -> Dict[str, Any]:
    try:
        fn()
        return {"id": case_id, "passed": True}
    except Exception as exc:
        return {"id": case_id, "passed": False, "error": str(exc)}


def _tc01() -> None:
    engine = DynamicRiskEngine(base_premium=120.0)
    score, raw, _reasons = engine.calculate_auto_telemetry_score(
        {"hard_brakes_per_100mi": 6, "night_miles_pct": 0.35, "speed_violations": 3}
    )
    if score <= 50.0:
        raise AssertionError(f"score {score} is not above 50")
    if raw <= 120.0:
        raise AssertionError(f"raw premium {raw} is not above 120")
    expected = 120.0 * (0.7 + (score / 100.0) * 0.8)
    if abs(raw - expected) > 1e-9:
        raise AssertionError(f"raw premium {raw} != {expected}")


def _tc02() -> None:
    final, clamped, _reason = ActuarialGuardrailEnforcer().enforce_rate_caps(150.0, 100.0)
    if final != 125.0 or clamped is not True:
        raise AssertionError(f"expected 125 clamped, got {final} {clamped}")


def _tc03() -> None:
    drought = SentinelSatelliteRiskProcessor().evaluate_property_crop_risk(DISTRESSED_BBOX)
    if drought["ndvi_index"] >= 0.30:
        raise AssertionError(f"ndvi {drought['ndvi_index']} is not below 0.30")
    if abs(drought["risk_delta"] - 25.0) > 1e-9:
        raise AssertionError(f"risk_delta {drought['risk_delta']} is not +25")
    if "ndwi_index" not in drought:
        raise AssertionError("ndwi_index missing")


def _tc04() -> None:
    tmp = tempfile.mkdtemp(prefix="dmue-harness-")
    manager = PolicyMemoryManager(persist_dir=str(Path(tmp) / "chroma"))
    manager.record_underwriting_event(
        "POL-98234",
        65.0,
        134.40,
        ["Hard braking is frequent at 6 events per 100 miles."],
    )
    context = manager.get_policy_context("POL-98234")
    if not context["metadatas"] or context["metadatas"][0]["policy_id"] != "POL-98234":
        raise AssertionError("policy recall did not match POL-98234")
    other = manager.get_policy_context("POL-00000")
    if other["ids"]:
        raise AssertionError("other policy id returned history")


def _tc05() -> None:
    request = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {
                "name": "reprice_policy_micro_underwrite",
                "arguments": {
                    "policy_id": "POL-HARNESS",
                    "hard_brakes_per_100mi": 6,
                    "night_miles_pct": 0.35,
                    "speed_violations": 3,
                    "previous_premium": 120,
                },
            },
        }
    )
    response = json.loads(handle_mcp_request(request))
    if response.get("jsonrpc") != "2.0" or "error" in response:
        raise AssertionError(f"unexpected MCP response: {response}")
    body = json.loads(response["result"]["content"][0]["text"])
    if "final_bounded_premium" not in body:
        raise AssertionError("premium payload missing")


def _eval_thresholds() -> None:
    _score, _raw, reasons = DynamicRiskEngine(base_premium=120.0).calculate_auto_telemetry_score(
        {"hard_brakes_per_100mi": 6, "night_miles_pct": 0.35, "speed_violations": 3}
    )
    result = evaluate_explanation(policyholder_text(reasons), reasons)
    if result["prohibited_term_leaks"] != 0:
        raise AssertionError("leaks must be 0")
    if result["factor_coverage"] < 0.50:
        raise AssertionError("coverage below 0.50")
    if result["flesch_reading_ease"] < 60:
        raise AssertionError("reading ease below 60")
    if result["flesch_grade_level"] > 8:
        raise AssertionError("grade above 8")
    if result["passed"] is not True:
        raise AssertionError("eval did not pass")


def _prohibited_key() -> None:
    try:
        ActuarialGuardrailEnforcer().reject_prohibited_keys(
            {"policy_id": "POL-1", "previous_premium": 100, "gender": "ignored"}
        )
    except ValueError:
        return
    raise AssertionError("prohibited key was accepted")


def run_harness() -> Dict[str, Any]:
    cases: List[Dict[str, Any]] = [
        _case("TC-01", _tc01),
        _case("TC-02", _tc02),
        _case("TC-03", _tc03),
        _case("TC-04", _tc04),
        _case("TC-05", _tc05),
        _case("eval_thresholds", _eval_thresholds),
        _case("prohibited_key", _prohibited_key),
    ]
    passed = all(item["passed"] for item in cases)
    return {"passed": passed, "cases": cases}


def main() -> int:
    report = run_harness()
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
