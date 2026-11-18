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
from app.core.appetite import evaluate_appetite
from app.core.lines import price_commercial, price_home
from app.core.routing import quote_cost_usd, resolve_route
from app.core.satellite_processor import SentinelSatelliteRiskProcessor, should_use_live_sentinel


def _bbox_key(bbox) -> tuple:
    return tuple(round(float(value), 6) for value in bbox)


def quote_policy(
    payload: Dict[str, Any],
    memory: Optional[PolicyMemoryManager] = None,
    hooks: Optional[Sequence[Any]] = None,
    circuit: Optional[CircuitBreaker] = None,
) -> Dict[str, Any]:
    """Run guardrails, risk math, optional signals, evals, hooks, and memory write."""
    if isinstance(payload.get("lines"), dict) and payload.get("lines"):
        return _quote_multi_line(payload, memory, hooks, circuit)
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
    want_live = should_use_live_sentinel(payload.get("sentinel_live"))
    if bbox:
        if breaker.is_open() and not want_live:
            decisions.append(decision("runtime", "satellite_circuit", "open"))
        else:
            live_now = want_live and not breaker.is_open()
            if want_live and breaker.is_open():
                decisions.append(decision("runtime", "satellite_circuit", "open"))
            cache_key = ("sat", _bbox_key(bbox), "live" if live_now else "local")
            satellite = satellite_cache.get(cache_key)
            if satellite is None:
                try:
                    satellite = satellite_processor.evaluate_property_crop_risk(
                        tuple(bbox), live=live_now
                    )
                    if live_now and satellite.get("sentinel_live_error"):
                        breaker.record_failure()
                        if breaker.is_open():
                            decisions.append(decision("runtime", "satellite_circuit", "open"))
                    else:
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
    uw_recommendation, uw_reasons = evaluate_appetite(
        risk_score=float(score),
        rate_clamped=clamped,
        satellite=satellite,
        anomalies=anomalies,
    )
    decisions.append(decision("underwriting", "appetite", uw_recommendation))
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
        "uw_recommendation": uw_recommendation,
        "uw_reasons": uw_reasons,
        "uw_status": "quoted",
    }


def _quote_multi_line(
    payload: Dict[str, Any],
    memory: Optional[PolicyMemoryManager] = None,
    hooks: Optional[Sequence[Any]] = None,
    circuit: Optional[CircuitBreaker] = None,
) -> Dict[str, Any]:
    policy_id = str(payload.get("policy_id") or "").strip()
    if not policy_id:
        raise ValueError("policy_id is required")
    lines_payload = payload.get("lines") or {}
    known = {"auto", "home", "commercial"}
    unknown = sorted(set(lines_payload) - known)
    if unknown:
        raise ValueError(f"Unknown line(s): {', '.join(unknown)}")

    guardrails = ActuarialGuardrailEnforcer()
    guardrails.reject_prohibited_keys(payload)
    results: Dict[str, Any] = {}
    hard_decline: List[str] = []
    auto_result: Optional[Dict[str, Any]] = None

    if "auto" in lines_payload:
        auto_payload = dict(lines_payload.get("auto") or {})
        auto_payload["policy_id"] = policy_id
        if payload.get("model_route") and not auto_payload.get("model_route"):
            auto_payload["model_route"] = payload["model_route"]
        if payload.get("sentinel_live") is not None and auto_payload.get("sentinel_live") is None:
            auto_payload["sentinel_live"] = payload["sentinel_live"]
        auto_result = quote_policy(auto_payload, memory, hooks, circuit)
        results["auto"] = {
            "line": "auto",
            "risk_score": auto_result["risk_score"],
            "raw_premium": auto_result["raw_premium"],
            "final_bounded_premium": auto_result["final_bounded_premium"],
            "rate_clamped": auto_result["rate_clamped"],
            "attribution_reasons": auto_result["attribution_reasons"],
            "satellite": auto_result.get("satellite"),
        }
    if "home" in lines_payload:
        results["home"] = price_home(
            policy_id,
            dict(lines_payload.get("home") or {}),
            guardrails,
            live=should_use_live_sentinel(payload.get("sentinel_live")),
        )
    if "commercial" in lines_payload:
        commercial = price_commercial(
            policy_id, dict(lines_payload.get("commercial") or {}), guardrails
        )
        hard_decline.extend(commercial.pop("hard_decline_reasons", []) or [])
        results["commercial"] = commercial
    if not results:
        raise ValueError("lines must include at least one of: auto, home, commercial")

    account_premium = round(
        sum(float(item["final_bounded_premium"]) for item in results.values()), 2
    )
    account_raw = round(sum(float(item["raw_premium"]) for item in results.values()), 2)
    account_risk = max(float(item["risk_score"]) for item in results.values())
    clamped_any = any(bool(item["rate_clamped"]) for item in results.values())
    first_satellite = next(
        (item.get("satellite") for item in results.values() if item.get("satellite")),
        None,
    )
    reasons_all: List[str] = []
    for item in results.values():
        reasons_all.extend(item.get("attribution_reasons") or [])

    uw_recommendation, uw_reasons = evaluate_appetite(
        risk_score=account_risk,
        rate_clamped=clamped_any,
        satellite=first_satellite,
        anomalies=(auto_result or {}).get("anomalies") or [],
        hard_decline_reasons=hard_decline,
    )
    decisions = [decision("underwriting", "appetite", uw_recommendation)]
    base = auto_result or {}
    return {
        "policy_id": policy_id,
        "risk_score": account_risk,
        "raw_premium": account_raw,
        "final_bounded_premium": account_premium,
        "rate_clamped": clamped_any,
        "regulatory_status": base.get(
            "regulatory_status", "Each line stays inside its filing band."
        ),
        "attribution_reasons": reasons_all,
        "explanation": base.get("explanation", ""),
        "recommendations": base.get("recommendations") or [],
        "anomalies": base.get("anomalies") or [],
        "satellite": first_satellite,
        "evals": base.get("evals") or {},
        "decisions": decisions,
        "policy_version": settings.VERSION,
        "environment": settings.DMUE_ENV,
        "model_route": base.get("model_route", settings.DEFAULT_MODEL_ROUTE),
        "model_route_label": base.get("model_route_label", ""),
        "cost": base.get("cost") or {"usd": 0.0},
        "trace_id": base.get("trace_id", ""),
        "observability": base.get("observability", "local"),
        "uw_recommendation": uw_recommendation,
        "uw_reasons": uw_reasons,
        "uw_status": "quoted",
        "lines": results,
        "account_premium": account_premium,
        "account_risk": account_risk,
    }
