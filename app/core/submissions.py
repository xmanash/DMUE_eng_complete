import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.config import settings

REQUIRED_DOCUMENTS = ["acord_125", "loss_runs", "sov"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_documents(documents: Optional[List[Dict[str, Any]]]) -> List[Dict[str, str]]:
    provided = {}
    for item in documents or []:
        if isinstance(item, dict) and item.get("name"):
            provided[str(item["name"])] = str(item.get("status") or "missing")
    return [
        {"name": name, "status": provided.get(name, "missing")}
        for name in REQUIRED_DOCUMENTS
    ]


def missing_documents(submission: Dict[str, Any]) -> List[str]:
    return [
        item["name"]
        for item in submission.get("documents") or []
        if item.get("status") != "received"
    ]


class SubmissionStore:
    """Append-only JSONL. Latest snapshot per submission_id wins."""

    def __init__(self, path: Optional[str] = None):
        self._path = path

    @property
    def path(self) -> Path:
        return Path(self._path or settings.SUBMISSIONS_LOG_PATH)

    def _append(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, default=str) + "\n")
        return entry

    def _read(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        rows = []
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

    def create(self, data: Dict[str, Any]) -> Dict[str, Any]:
        policy_id = str((data or {}).get("policy_id") or "").strip()
        if not policy_id:
            raise ValueError("policy_id is required")
        broker = dict((data or {}).get("broker") or {})
        losses = list((data or {}).get("losses") or [])
        for loss in losses:
            if not isinstance(loss, dict) or "year" not in loss or "amount" not in loss:
                raise ValueError("each loss needs year, amount, and cause")
        submission = {
            "kind": "submission",
            "ts": _now(),
            "submission_id": str((data or {}).get("submission_id") or uuid.uuid4().hex[:12]),
            "policy_id": policy_id,
            "broker": {
                "name": str(broker.get("name") or ""),
                "agency": str(broker.get("agency") or ""),
                "aor": bool(broker.get("aor", False)),
            },
            "effective_date": str((data or {}).get("effective_date") or ""),
            "lines": (data or {}).get("lines"),
            "model_route": (data or {}).get("model_route"),
            "documents": normalize_documents((data or {}).get("documents")),
            "losses": losses,
        }
        submission["missing_documents"] = missing_documents(submission)
        submission["status"] = "incomplete" if submission["missing_documents"] else "received"
        submission["can_bind"] = not submission["missing_documents"]
        return self._append(submission)

    def get(self, submission_id: str) -> Optional[Dict[str, Any]]:
        found = None
        for row in self._read():
            if row.get("submission_id") == submission_id:
                found = row
        return found

    def update_status(self, submission_id: str, status: str) -> Dict[str, Any]:
        current = self.get(submission_id)
        if current is None:
            raise ValueError("Unknown submission_id")
        updated = dict(current)
        updated["ts"] = _now()
        updated["status"] = status
        updated["missing_documents"] = missing_documents(updated)
        updated["can_bind"] = not updated["missing_documents"]
        return self._append(updated)


submission_store = SubmissionStore()
