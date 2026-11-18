from typing import Any, Dict, List, Optional

import numpy as np

from app.core.config import settings
from app.core.guardrails import ActuarialGuardrailEnforcer
from app.core.risk_engine import DynamicRiskEngine
from app.core.satellite_processor import SentinelSatelliteRiskProcessor

OCCUPANCY_LOADS = {
    "office": 0.0,
    "retail": 10.0,
    "warehouse": 20.0,
    "excluded": 0.0,
}


def _satellite_delta(
    bbox, reasons: List[str], live: bool = False
) -> tuple[float, Optional[Dict[str, Any]]]:
    if not bbox:
        return 0.0, None
    satellite = SentinelSatelliteRiskProcessor().evaluate_property_crop_risk(
        tuple(bbox), live=live
    )
    reasons.extend(satellite["risk_factors"])
    return float(satellite["risk_delta"]), satellite


def _validate_line(
    guardrails: ActuarialGuardrailEnforcer,
    policy_id: str,
    line_payload: Dict[str, Any],
) -> Dict[str, Any]:
    merged = {"policy_id": policy_id, **dict(line_payload or {})}
    guardrails.reject_prohibited_keys(merged)
    cleaned, _anomalies = guardrails.filter_anomalies(merged)
    return cleaned


def price_home(
    policy_id: str,
    payload: Dict[str, Any],
    guardrails: ActuarialGuardrailEnforcer,
    live: bool = False,
) -> Dict[str, Any]:
    cleaned = _validate_line(guardrails, policy_id, payload)
    engine = DynamicRiskEngine(base_premium=float(cleaned["previous_premium"]))
    score, raw, reasons = engine.apply_environment_signals(50.0, cleaned, [])
    delta, satellite = _satellite_delta(cleaned.get("bbox"), reasons, live=live)
    if satellite is not None:
        score = float(np.clip(score + delta, 0.0, 100.0))
        raw = engine.premium_for_score(score)
    final, clamped, _cap = guardrails.enforce_rate_caps(raw, cleaned["previous_premium"])
    return {
        "line": "home",
        "risk_score": float(score),
        "raw_premium": round(float(raw), 2),
        "final_bounded_premium": final,
        "rate_clamped": clamped,
        "attribution_reasons": reasons,
        "satellite": satellite,
    }


def price_commercial(
    policy_id: str, payload: Dict[str, Any], guardrails: ActuarialGuardrailEnforcer
) -> Dict[str, Any]:
    cleaned = _validate_line(guardrails, policy_id, payload)
    occupancy = str((payload or {}).get("occupancy") or "office").strip().lower()
    if occupancy not in OCCUPANCY_LOADS:
        raise ValueError(
            "commercial occupancy must be one of: office, retail, warehouse, excluded"
        )
    try:
        tiv = float((payload or {}).get("tiv") or 0)
    except (TypeError, ValueError):
        raise ValueError("commercial tiv must be a finite number")
    if tiv < 0:
        raise ValueError("commercial tiv must be 0 or greater")

    score = 50.0 + OCCUPANCY_LOADS[occupancy]
    reasons = [f"Commercial occupancy is {occupancy}."]
    if tiv >= 1_000_000:
        score += 10.0
        reasons.append("Total insured value is at or above $1,000,000.")
    score = float(np.clip(score, 0.0, 100.0))

    engine = DynamicRiskEngine(base_premium=float(cleaned["previous_premium"]))
    raw = engine.premium_for_score(score)
    final, clamped, _cap = guardrails.enforce_rate_caps(raw, cleaned["previous_premium"])
    result: Dict[str, Any] = {
        "line": "commercial",
        "risk_score": float(score),
        "raw_premium": round(float(raw), 2),
        "final_bounded_premium": final,
        "rate_clamped": clamped,
        "attribution_reasons": reasons,
        "satellite": None,
        "occupancy": occupancy,
        "tiv": tiv,
    }
    if occupancy == "excluded":
        result["hard_decline_reasons"] = ["Commercial occupancy is excluded from appetite."]
    return result
