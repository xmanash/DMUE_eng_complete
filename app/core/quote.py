from typing import Any, Dict, List, Optional

import numpy as np

from app.core.evals import evaluate_explanation, policyholder_text
from app.core.guardrails import ActuarialGuardrailEnforcer
from app.core.memory import PolicyMemoryManager
from app.core.risk_engine import DynamicRiskEngine, recommendations_for
from app.core.satellite_processor import SentinelSatelliteRiskProcessor
from app.core.config import settings


def quote_policy(
    payload: Dict[str, Any], memory: Optional[PolicyMemoryManager] = None
) -> Dict[str, Any]:
    """Run guardrails, risk math, optional signals, evals, and memory write."""
    guardrails = ActuarialGuardrailEnforcer()
    engine = DynamicRiskEngine(base_premium=settings.BASE_MONTHLY_AUTO_PREMIUM)
    satellite_processor = SentinelSatelliteRiskProcessor()

    guardrails.reject_prohibited_keys(payload)
    cleaned, anomalies = guardrails.filter_anomalies(payload)

    score, _raw, reasons = engine.calculate_auto_telemetry_score(cleaned)
    score, raw_premium, reasons = engine.apply_environment_signals(score, cleaned, reasons)

    satellite = None
    bbox = cleaned.get("bbox")
    if bbox:
        satellite = satellite_processor.evaluate_property_crop_risk(tuple(bbox))
        score = float(np.clip(score + satellite["risk_delta"], 0.0, 100.0))
        reasons = list(reasons) + list(satellite["risk_factors"])
        raw_premium = engine.premium_for_score(score)

    explanation = policyholder_text(reasons)
    guardrails.assert_no_prohibited_language(explanation)
    evals = evaluate_explanation(explanation, reasons)

    final_premium, clamped, cap_reason = guardrails.enforce_rate_caps(
        raw_premium, cleaned["previous_premium"]
    )
    advice = recommendations_for(reasons)
    if any("malfunction" in item.lower() for item in anomalies):
        advice.append(
            "Check the braking sensor. A reading above 20 events per 100 miles was treated as a fault."
        )

    if memory is not None:
        memory.record_underwriting_event(
            policy_id=cleaned["policy_id"],
            risk_score=float(score),
            premium=final_premium,
            reasons=reasons,
        )

    return {
        "policy_id": cleaned["policy_id"],
        "risk_score": float(score),
        "raw_premium": round(float(raw_premium), 2),
        "final_bounded_premium": final_premium,
        "rate_clamped": clamped,
        "regulatory_status": cap_reason,
        "attribution_reasons": reasons,
        "explanation": explanation,
        "recommendations": advice,
        "anomalies": anomalies,
        "satellite": satellite,
        "evals": evals,
    }
