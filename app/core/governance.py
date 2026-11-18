"""Quote JSONL audit and structured decision records."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.config import settings

QUOTE_LOGGER = logging.getLogger("dmue.quote")


def configure_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(level=level, format="%(message)s")


def decision(layer: str, name: str, action: str, detail: str = "") -> Dict[str, str]:
    item = {"layer": layer, "name": name, "action": action}
    if detail:
        item["detail"] = detail
    return item


def quote_event(
    *,
    policy_id: str,
    action: str,
    risk_score: Optional[float],
    premium: Optional[float],
    clamped: Optional[bool],
    eval_passed: Optional[bool],
    decisions: List[Dict[str, str]],
    duration_ms: float,
) -> Dict[str, Any]:
    return {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "policy_id": policy_id,
        "action": action,
        "risk_score": risk_score,
        "final_bounded_premium": premium,
        "rate_clamped": clamped,
        "eval_passed": eval_passed,
        "decisions": decisions,
        "duration_ms": round(duration_ms, 2),
        "policy_version": settings.VERSION,
    }


def log_quote(event: Dict[str, Any]) -> None:
    QUOTE_LOGGER.info(json.dumps(event, default=str))


class AuditLogHook:
    """Appends quote events to a local JSONL file. May be placed with other hooks."""

    def __init__(self, path: Optional[str] = None):
        self.path = Path(path or settings.AUDIT_LOG_PATH)

    def review(self, event: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, default=str) + "\n")
