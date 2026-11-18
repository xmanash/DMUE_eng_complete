import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.config import settings

COST_LOGGER_PATH_DEFAULT = "./data/audit/costs.jsonl"


class CostTracker:
    """In-process cost ledger. Totals are per process, not shared across workers."""

    def __init__(self):
        self._lock = threading.Lock()
        self.entries: List[Dict[str, Any]] = []
        self.total_usd = 0.0

    def record(
        self,
        *,
        policy_id: str,
        route_id: str,
        usd: float,
        duration_ms: float,
    ) -> Dict[str, Any]:
        item = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "policy_id": policy_id,
            "route_id": route_id,
            "usd": round(float(usd), 6),
            "duration_ms": round(float(duration_ms), 2),
        }
        with self._lock:
            self.entries.append(item)
            self.total_usd = round(self.total_usd + item["usd"], 6)
            total = self.total_usd
            count = len(self.entries)
        return {**item, "quotes": count, "total_usd": total}

    def summary(self) -> Dict[str, Any]:
        with self._lock:
            by_route: Dict[str, float] = {}
            for item in self.entries:
                by_route[item["route_id"]] = round(
                    by_route.get(item["route_id"], 0.0) + item["usd"], 6
                )
            return {
                "quotes": len(self.entries),
                "total_usd": self.total_usd,
                "by_route": by_route,
                "recent": list(self.entries[-20:]),
            }

    def reset(self) -> None:
        with self._lock:
            self.entries.clear()
            self.total_usd = 0.0


cost_tracker = CostTracker()


class CostHook:
    """Writes an allow-event cost line to JSONL after a successful quote."""

    def __init__(self, path: Optional[str] = None):
        self.path = Path(path or settings.AUDIT_LOG_PATH.replace("quotes.jsonl", "costs.jsonl"))

    def review(self, event: Dict[str, Any]) -> None:
        if event.get("action") != "allow":
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = {
            "ts": event.get("ts"),
            "policy_id": event.get("policy_id"),
            "usd": event.get("cost_usd"),
            "route_id": event.get("route_id"),
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line) + "\n")
