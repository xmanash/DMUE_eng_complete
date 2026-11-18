"""UW desk JSONL: quote snapshots, human decisions, notes, packets."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.config import settings

STATUS_BY_ACTION = {"accept": "bound", "refer": "referred", "decline": "declined"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class UnderwritingStore:
    """Append-only JSONL for quote snapshots, UW decisions, and notes."""

    def __init__(self, path: Optional[str] = None):
        self._path = path

    @property
    def path(self) -> Path:
        return Path(self._path or settings.UW_LOG_PATH)

    def _append(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, default=str) + "\n")
        return entry

    def _read(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        rows: List[Dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows

    def reset(self) -> None:
        if self.path.exists():
            self.path.write_text("", encoding="utf-8")

    def record_quote(self, result: Dict[str, Any]) -> Dict[str, Any]:
        entry = {
            "kind": "quote",
            "ts": _now(),
            "policy_id": result.get("policy_id"),
            "quote_trace_id": result.get("trace_id", ""),
            "risk_score": result.get("risk_score"),
            "raw_premium": result.get("raw_premium"),
            "final_bounded_premium": result.get("final_bounded_premium"),
            "account_premium": result.get("account_premium"),
            "rate_clamped": result.get("rate_clamped"),
            "uw_recommendation": result.get("uw_recommendation", "accept"),
            "uw_reasons": result.get("uw_reasons") or [],
            "decisions": result.get("decisions") or [],
            "lines": result.get("lines"),
            "model_route": result.get("model_route"),
        }
        return self._append(entry)

    def latest_quote(self, policy_id: str) -> Optional[Dict[str, Any]]:
        found = None
        for row in self._read():
            if row.get("kind") == "quote" and row.get("policy_id") == policy_id:
                found = row
        return found

    def record_decision(
        self,
        *,
        policy_id: str,
        quote_trace_id: str = "",
        action: str,
        underwriter: str = "",
        note: str = "",
        recommendation: str = "",
        submission_id: str = "",
    ) -> Dict[str, Any]:
        if action not in STATUS_BY_ACTION:
            raise ValueError("action must be accept, refer, or decline")
        override = action == "accept" and recommendation in {"refer", "decline"}
        entry = {
            "kind": "decision",
            "ts": _now(),
            "policy_id": policy_id,
            "quote_trace_id": quote_trace_id,
            "action": action,
            "uw_status": STATUS_BY_ACTION[action],
            "underwriter": underwriter,
            "note": note,
            "recommendation": recommendation,
            "override": override,
            "submission_id": submission_id,
        }
        return self._append(entry)

    def record_note(
        self, *, policy_id: str, underwriter: str = "", note: str, quote_trace_id: str = ""
    ) -> Dict[str, Any]:
        if not str(note or "").strip():
            raise ValueError("note is required")
        entry = {
            "kind": "note",
            "ts": _now(),
            "policy_id": policy_id,
            "quote_trace_id": quote_trace_id,
            "underwriter": underwriter,
            "note": note,
        }
        return self._append(entry)

    def actions_for(self, policy_id: str) -> List[Dict[str, Any]]:
        return [
            row
            for row in self._read()
            if row.get("kind") in {"decision", "note"} and row.get("policy_id") == policy_id
        ]

    def latest_decision(self, policy_id: str) -> Optional[Dict[str, Any]]:
        found = None
        for row in self._read():
            if row.get("kind") == "decision" and row.get("policy_id") == policy_id:
                found = row
        return found

    def referrals(self) -> List[Dict[str, Any]]:
        rows = self._read()
        decided_traces = {
            row.get("quote_trace_id")
            for row in rows
            if row.get("kind") == "decision"
            and row.get("action") in {"accept", "decline"}
            and row.get("quote_trace_id")
        }
        open_items: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            trace = row.get("quote_trace_id") or ""
            if trace and trace in decided_traces:
                open_items.pop(trace, None)
                continue
            if row.get("kind") == "quote" and row.get("uw_recommendation") == "refer":
                open_items[trace or row.get("policy_id")] = {
                    "policy_id": row.get("policy_id"),
                    "quote_trace_id": trace,
                    "uw_recommendation": "refer",
                    "uw_reasons": row.get("uw_reasons") or [],
                    "risk_score": row.get("risk_score"),
                    "source": "appetite",
                    "ts": row.get("ts"),
                }
            elif row.get("kind") == "decision" and row.get("action") == "refer":
                open_items[trace or row.get("policy_id")] = {
                    "policy_id": row.get("policy_id"),
                    "quote_trace_id": trace,
                    "uw_recommendation": "refer",
                    "uw_reasons": [],
                    "risk_score": None,
                    "source": "underwriter",
                    "underwriter": row.get("underwriter", ""),
                    "ts": row.get("ts"),
                }
        return list(open_items.values())

    def packet(self, policy_id: str) -> Dict[str, Any]:
        quote = self.latest_quote(policy_id)
        decision_row = self.latest_decision(policy_id)
        actions = self.actions_for(policy_id)
        notes = [row for row in actions if row.get("kind") == "note"]
        if decision_row and decision_row.get("note"):
            notes = notes + [
                {
                    "kind": "note",
                    "ts": decision_row.get("ts"),
                    "underwriter": decision_row.get("underwriter", ""),
                    "note": decision_row["note"],
                    "quote_trace_id": decision_row.get("quote_trace_id", ""),
                }
            ]
        return {
            "policy_id": policy_id,
            "quote": quote,
            "uw_recommendation": (quote or {}).get("uw_recommendation"),
            "uw_reasons": (quote or {}).get("uw_reasons") or [],
            "uw_status": (decision_row or {}).get("uw_status", "quoted"),
            "override": bool((decision_row or {}).get("override", False)),
            "decisions": (quote or {}).get("decisions") or [],
            "actions": actions,
            "notes": notes,
        }


uw_store = UnderwritingStore()
