import json
from pathlib import Path

import pytest

from app.core.governance import AuditLogHook
from app.core.quote import quote_policy
from app.harness import run_harness


SAMPLE = {
    "policy_id": "POL-GOV",
    "hard_brakes_per_100mi": 6,
    "night_miles_pct": 0.35,
    "speed_violations": 3,
    "total_miles": 450,
    "previous_premium": 120,
}


class FakeMemory:
    def __init__(self):
        self.writes = 0

    def record_underwriting_event(self, **kwargs):
        self.writes += 1


class VetoHook:
    def review(self, event):
        raise RuntimeError("governance veto")


def _read_jsonl(path: Path):
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    return [json.loads(line) for line in lines]


def test_passing_quote_records_allow_and_audit(tmp_path):
    memory = FakeMemory()
    audit = tmp_path / "quotes.jsonl"
    hook = AuditLogHook(path=str(audit))
    result = quote_policy(SAMPLE, memory=memory, hooks=[hook])
    names = {item["name"]: item["action"] for item in result["decisions"]}
    assert names["prohibited_keys"] == "allow"
    assert names["anomaly_filter"] == "allow"
    assert names["explanation_eval"] == "allow"
    assert names["rate_cap"] in {"allow", "clamp"}
    assert memory.writes == 1
    events = _read_jsonl(audit)
    assert len(events) == 1
    assert events[0]["action"] == "allow"
    assert events[0]["policy_id"] == "POL-GOV"


def test_eval_failure_blocks_memory_and_audits(tmp_path, monkeypatch):
    memory = FakeMemory()
    audit = tmp_path / "quotes.jsonl"
    hook = AuditLogHook(path=str(audit))

    def fail_eval(_text, _drivers):
        return {
            "prohibited_term_leaks": 1,
            "factor_coverage": 0.0,
            "flesch_reading_ease": 10.0,
            "flesch_grade_level": 20.0,
            "passed": False,
        }

    monkeypatch.setattr("app.core.quote.evaluate_explanation", fail_eval)
    with pytest.raises(ValueError, match="evaluation gates"):
        quote_policy(SAMPLE, memory=memory, hooks=[hook])
    assert memory.writes == 0
    events = _read_jsonl(audit)
    assert events[-1]["action"] == "block"
    assert any(item["name"] == "explanation_eval" and item["action"] == "block" for item in events[-1]["decisions"])


def test_hook_raise_prevents_memory_write():
    memory = FakeMemory()
    with pytest.raises(RuntimeError, match="veto"):
        quote_policy(SAMPLE, memory=memory, hooks=[VetoHook()])
    assert memory.writes == 0


def test_harness_all_cases_pass():
    report = run_harness()
    failed = [item["id"] for item in report["cases"] if not item["passed"]]
    assert report["passed"] is True, failed
