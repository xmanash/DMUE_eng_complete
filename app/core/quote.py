from time import perf_counter
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from app.core.cache import context_cache, satellite_cache
from app.core.circuit import CircuitBreaker, satellite_circuit
from app.core.config import settings
from app.core.cost import cost_tracker
from app.core.evals import evaluate_explanation, policyholder_text
from app.core.governance import AuditLogHook, log_quote, quote_event, decision
from app.core.observability import record_trace
from app.core.guardrails import ActuarialGuardrailEnforcer
from app.core.memory import PolicyMemoryManager
from app.core.risk_engine import DynamicRiskEngine, recommendations_for
from app.core.routing import quote_cost_usd, resolve_route
from app.core.satellite_processor import SentinelSatelliteRiskProcessor


def _bbox_key(bbox) -> tuple:
    return tuple(round(float(value), 6) for value in bbox)


def quote_policy(
    payload: Dict[str, Any],
    memory: Optional[PolicyMemoryManager] = None,
    hooks: Optional[Sequence[Any]] = None,
    circuit: Optional[CircuitBreaker] = None,
) -> Dict[str, Any]:
    """Run guardrails, risk math, optional signals, evals, hooks, and memory write."""
    started = perf_counter()
    hook_list = list(hooks or [])
    guardrails = ActuarialGuardrailEnforcer()
    engine = DynamicRiskEngine(base_premium=settings.BASE_MONTHLY_AUTO_PREMIUM)
    satellite_processor = SentinelSatelliteRiskProcessor()
    breaker = circuit or satellite_circuit
    decisions: List[Dict[str, str]] = []
    policy_id = str(payload.get("policy_id") or "").strip() or "unknown"

    def emit_block(
        *,
        eval_passed: Optional[bool] = None,
        risk_score: Optional[float] = None,
        premium: Optional[float] = None,
        clamped: Optional[bool] = None,
    ) -> Dict[str, Any]:
        event = quote_event(
            policy_id=policy_id,
            action="block",
            risk_score=risk_score,
            premium=premium,
            clamped=clamped,
            eval_passed=eval_passed,
            decisions=decisions,
            duration_ms=(perf_counter() - started) * 1000,
        )
        log_quote(event)
        record_trace(event)
        for hook in hook_list:
            hook.review(event)
        return event

    try:
        guardrails.reject_prohibited_keys(payload)
        decisions.append(decision("input", "prohibited_keys", "allow"))
        cleaned, anomalies = guardrails.filter_anomalies(payload)
        policy_id = cleaned["policy_id"]
        anomaly_action = "flag" if anomalies else "allow"
        decisions.append(
            decision(
                "input",
                "anomaly_filter",
                anomaly_action,
                "; ".join(anomalies) if anomalies else "",
            )
        )
    except ValueError:
        if any(item["name"] == "prohibited_keys" and item["action"] == "allow" for item in decisions):
            decisions.append(decision("input", "anomaly_filter", "reject"))
        else:
            decisions.append(decision("input", "prohibited_keys", "reject"))
        emit_block()
        raise

    try:
        route = resolve_route(payload.get("model_route"))
    except ValueError:
        decisions.append(decision("runtime", "model_route", "reject"))
        emit_block()
        raise
    decisions.append(decision("runtime", "model_route", route["id"]))

    score, _raw, reasons = engine.calculate_auto_telemetry_score(cleaned)
    if route["use_environment"]:
        score, raw_premium, reasons = engine.apply_environment_signals(score, cleaned, reasons)
    else:
        raw_premium = engine.premium_for_score(score)

    satellite = None
    bbox = cleaned.get("bbox") if route["use_satellite"] else None
    if bbox:
        if breaker.is_open():
            decisions.append(decision("runtime", "satellite_circuit", "open"))
        else:
            cache_key = ("sat", _bbox_key(bbox))
            satellite = satellite_cache.get(cache_key)
            if satellite is None:
                try:
                    satellite = satellite_processor.evaluate_property_crop_risk(tuple(bbox))
                    breaker.record_success()
                    satellite_cache.set(cache_key, satellite)
                except Exception:
                    breaker.record_failure()
                    if breaker.is_open():
                        decisions.append(decision("runtime", "satellite_circuit", "open"))
                    satellite = None
            if satellite is not None:
                score = float(np.clip(score + satellite["risk_delta"], 0.0, 100.0))
                reasons = list(reasons) + list(satellite["risk_factors"])
                raw_premium = engine.premium_for_score(score)

    explanation = policyholder_text(reasons)
    try:
        guardrails.assert_no_prohibited_language(explanation)
        evals = evaluate_explanation(explanation, reasons)
        if not evals["passed"]:
            raise ValueError("Explanation failed evaluation gates")
        decisions.append(decision("output", "explanation_eval", "allow"))
    except ValueError:
        decisions.append(decision("output", "explanation_eval", "block"))
        emit_block(eval_passed=False, risk_score=float(score))
        raise

    final_premium, clamped, cap_reason = guardrails.enforce_rate_caps(
        raw_premium, cleaned["previous_premium"]
    )
    decisions.append(
        decision("policy", "rate_cap", "clamp" if clamped else "allow", cap_reason)
    )
    advice = recommendations_for(reasons)
    if any("malfunction" in item.lower() for item in anomalies):
        advice.append(
            "Check the braking sensor. A reading above 20 events per 100 miles was treated as a fault."
        )

    duration_ms = (perf_counter() - started) * 1000
    usd = quote_cost_usd(route, satellite is not None)
    cost = cost_tracker.record(
        policy_id=policy_id,
        route_id=route["id"],
        usd=usd,
        duration_ms=duration_ms,
    )
    event = quote_event(
        policy_id=policy_id,
        action="allow",
        risk_score=float(score),
        premium=final_premium,
        clamped=clamped,
        eval_passed=True,
        decisions=decisions,
        duration_ms=duration_ms,
    )
    event["route_id"] = route["id"]
    event["cost_usd"] = usd
    log_quote(event)
    trace = record_trace(event)
    try:
        for hook in hook_list:
            hook.review(event)
    except Exception:
        blocked = dict(event)
        blocked["action"] = "block"
        log_quote(blocked)
        record_trace(blocked)
        for hook in hook_list:
            if isinstance(hook, AuditLogHook):
                hook.review(blocked)
        raise

    if memory is not None:
        memory.record_underwriting_event(
            policy_id=cleaned["policy_id"],
            risk_score=float(score),
            premium=final_premium,
            reasons=reasons,
        )
    context_cache.invalidate_policy(cleaned["policy_id"])

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
        "decisions": decisions,
        "policy_version": settings.VERSION,
        "environment": settings.DMUE_ENV,
        "model_route": route["id"],
        "model_route_label": route["label"],
        "cost": cost,
        "trace_id": trace["trace_id"],
        "observability": "langsmith+local" if settings.LANGSMITH_TRACING and settings.LANGSMITH_API_KEY else "local",
    }
