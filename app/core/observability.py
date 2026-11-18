"""Local JSONL traces always on. LangSmith export is optional and never blocks a quote."""

import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import settings

TRACE_LOGGER = logging.getLogger("dmue.trace")
LANGSMITH_RUNS_URL = "https://api.smith.langchain.com/runs"


class TraceStore:
    """Local JSONL traces. Always on. No vendor required."""

    def __init__(self, path: Optional[str] = None, keep: int = 200):
        self.path = Path(path or settings.TRACE_LOG_PATH)
        self.keep = keep
        self._lock = threading.Lock()
        self.recent: List[Dict[str, Any]] = []

    def record(self, event: Dict[str, Any]) -> Dict[str, Any]:
        trace = {
            "trace_id": event.get("trace_id") or str(uuid.uuid4()),
            "ts": event.get("ts") or datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "name": "quote_policy",
            "run_type": "chain",
            "policy_id": event.get("policy_id"),
            "action": event.get("action"),
            "duration_ms": event.get("duration_ms"),
            "route_id": event.get("route_id"),
            "cost_usd": event.get("cost_usd"),
            "eval_passed": event.get("eval_passed"),
            "rate_clamped": event.get("rate_clamped"),
            "environment": settings.DMUE_ENV,
            "decisions": event.get("decisions") or [],
        }
        with self._lock:
            self.recent.append(trace)
            self.recent = self.recent[-self.keep :]
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(trace, default=str) + "\n")
        except OSError as exc:
            TRACE_LOGGER.warning("Could not write local trace: %s", exc)
        TRACE_LOGGER.info(json.dumps({"trace_id": trace["trace_id"], "action": trace["action"]}))
        return trace

    def list_recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self.recent[-max(1, int(limit)) :])

    def reset(self) -> None:
        with self._lock:
            self.recent.clear()


trace_store = TraceStore()


def langsmith_enabled() -> bool:
    return bool((settings.LANGSMITH_API_KEY or "").strip()) and settings.LANGSMITH_TRACING


def observability_status() -> Dict[str, Any]:
    remote = "langsmith" if langsmith_enabled() else None
    return {
        "local": True,
        "local_path": settings.TRACE_LOG_PATH,
        "langsmith": langsmith_enabled(),
        "langsmith_project": settings.LANGSMITH_PROJECT if langsmith_enabled() else None,
        "backend": "langsmith+local" if remote else "local",
    }


def _post_langsmith(trace: Dict[str, Any]) -> None:
    if not langsmith_enabled():
        return
    payload = {
        "id": trace["trace_id"],
        "name": "quote_policy",
        "run_type": "chain",
        "inputs": {"policy_id": trace.get("policy_id"), "route_id": trace.get("route_id")},
        "outputs": {
            "action": trace.get("action"),
            "eval_passed": trace.get("eval_passed"),
            "cost_usd": trace.get("cost_usd"),
        },
        "extra": {
            "metadata": {
                "environment": settings.DMUE_ENV,
                "project": settings.LANGSMITH_PROJECT,
            }
        },
        "start_time": trace.get("ts"),
        "end_time": trace.get("ts"),
        "session_name": settings.LANGSMITH_PROJECT,
    }
    headers = {
        "x-api-key": settings.LANGSMITH_API_KEY,
        "Content-Type": "application/json",
    }
    try:
        httpx.post(LANGSMITH_RUNS_URL, json=payload, headers=headers, timeout=3.0)
    except Exception as exc:
        TRACE_LOGGER.warning("LangSmith export skipped: %s", exc)


def record_trace(event: Dict[str, Any]) -> Dict[str, Any]:
    if "trace_id" not in event:
        event["trace_id"] = str(uuid.uuid4())
    trace = trace_store.record(event)
    _post_langsmith(trace)
    return trace


class ObservabilityHook:
    def review(self, event: Dict[str, Any]) -> None:
        record_trace(event)
