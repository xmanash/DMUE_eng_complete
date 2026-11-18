"""Accept / refer / decline from score and flags. Never changes premium."""

from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings


def evaluate_appetite(
    *,
    risk_score: float,
    rate_clamped: bool = False,
    satellite: Optional[Dict[str, Any]] = None,
    anomalies: Optional[List[str]] = None,
    hard_decline_reasons: Optional[List[str]] = None,
) -> Tuple[str, List[str]]:
    """Return (recommendation, reasons). Does not change any premium."""
    reasons: List[str] = []
    hard = list(hard_decline_reasons or [])
    if hard:
        return "decline", hard

    score = float(risk_score)
    if satellite is not None:
        ndvi = satellite.get("ndvi_index")
        if ndvi is not None and float(ndvi) < 0.30:
            reasons.append(f"Satellite NDVI is low at {float(ndvi):.2f}.")
    if rate_clamped:
        reasons.append("Rate move was clamped by the filing cap.")
    if anomalies:
        reasons.append("Sensor fault was flagged on this quote.")
    if score >= settings.UW_REFER_SCORE:
        reasons.insert(0, f"Risk score {score:.0f} is at or above the refer threshold.")

    if score >= settings.UW_DECLINE_SCORE:
        return "decline", [
            f"Risk score {score:.0f} is at or above the decline threshold."
        ] + [r for r in reasons if "Risk score" not in r]
    # Clamp, low NDVI, or sensor fault refer even when score is below 80.
    if score >= settings.UW_REFER_SCORE or reasons:
        return "refer", reasons
    return "accept", ["Inside appetite."]
