from fastapi.testclient import TestClient

from app.core.config import settings
from app.ui.demo_cases import CASES, payload_from_fields, tone_for_quote
from app.core.quote import quote_policy
from app.core.ratelimit import limiter
from app.core.submissions import submission_store
from app.core.underwriting import uw_store
from app.main import app

LOW = {
    "policy_id": "POL-UW-LOW",
    "hard_brakes_per_100mi": 0,
    "night_miles_pct": 0,
    "speed_violations": 0,
    "total_miles": 100,
    "previous_premium": 120,
}
REFER = {
    "policy_id": "POL-UW-REFER",
    "hard_brakes_per_100mi": 6,
    "night_miles_pct": 0,
    "speed_violations": 3,
    "total_miles": 100,
    "previous_premium": 120,
}
DECLINE = {
    "policy_id": "POL-UW-DECLINE",
    "hard_brakes_per_100mi": 6,
    "night_miles_pct": 0.35,
    "speed_violations": 3,
    "total_miles": 100,
    "previous_premium": 120,
}


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "UW_LOG_PATH", str(tmp_path / "uw.jsonl"))
    monkeypatch.setattr(settings, "SUBMISSIONS_LOG_PATH", str(tmp_path / "subs.jsonl"))
    uw_store.reset()
    submission_store.reset()
    limiter.reset()


def test_appetite_accept_refer_decline():
    assert quote_policy(dict(LOW))["uw_recommendation"] == "accept"
    refer = quote_policy(dict(REFER))
    assert refer["uw_recommendation"] == "refer"
    assert refer["risk_score"] >= 80
    decline = quote_policy(dict(DECLINE))
    assert decline["uw_recommendation"] == "decline"
    assert decline["risk_score"] >= 95
    assert any(
        item["layer"] == "underwriting" and item["name"] == "appetite"
        for item in decline["decisions"]
    )


def test_decision_override_and_packet(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    with TestClient(app) as client:
        quoted = client.post("/api/v1/reprice", json=REFER)
        assert quoted.status_code == 200
        body = quoted.json()
        assert body["uw_recommendation"] == "refer"
        referrals = client.get("/api/v1/uw/referrals").json()["referrals"]
        assert any(item["policy_id"] == "POL-UW-REFER" for item in referrals)

        decided = client.post(
            "/api/v1/uw/decision",
            json={
                "policy_id": "POL-UW-REFER",
                "quote_trace_id": body["trace_id"],
                "action": "accept",
                "underwriter": "Demo UW",
                "note": "Reviewed referral",
            },
        )
        assert decided.status_code == 200
        assert decided.json()["override"] is True
        assert decided.json()["uw_status"] == "bound"

        packet = client.get("/api/v1/uw/packet/POL-UW-REFER")
        assert packet.status_code == 200
        packet_body = packet.json()
        assert packet_body["quote"]["quote_trace_id"] == body["trace_id"]
        assert packet_body["uw_status"] == "bound"
        assert packet_body["notes"]


def test_multiline_account_premium_is_sum():
    result = quote_policy(
        {
            "policy_id": "POL-UW-MULTI",
            "previous_premium": 120,
            "lines": {
                "auto": dict(
                    {k: v for k, v in LOW.items() if k != "policy_id"}
                ),
                "home": {"previous_premium": 150, "iot_moisture": 0.2},
            },
        }
    )
    assert set(result["lines"]) == {"auto", "home"}
    expected = round(
        result["lines"]["auto"]["final_bounded_premium"]
        + result["lines"]["home"]["final_bounded_premium"],
        2,
    )
    assert result["account_premium"] == expected
    assert result["final_bounded_premium"] == expected
    assert result["account_risk"] == max(
        result["lines"]["auto"]["risk_score"], result["lines"]["home"]["risk_score"]
    )


def test_excluded_occupancy_declines():
    result = quote_policy(
        {
            "policy_id": "POL-UW-COMM",
            "previous_premium": 300,
            "lines": {
                "commercial": {
                    "previous_premium": 300,
                    "tiv": 100000,
                    "occupancy": "excluded",
                }
            },
        }
    )
    assert result["uw_recommendation"] == "decline"
    assert "excluded" in " ".join(result["uw_reasons"]).lower()


def test_submission_missing_docs_blocks_bind_not_quote(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/submissions",
            json={
                "policy_id": "POL-UW-SUB",
                "broker": {"name": "Broker A", "agency": "Agency", "aor": True},
                "effective_date": "2026-01-01",
                "lines": {
                    "auto": {k: v for k, v in LOW.items() if k != "policy_id"}
                },
                "documents": [
                    {"name": "acord_125", "status": "received"},
                    {"name": "loss_runs", "status": "missing"},
                    {"name": "sov", "status": "received"},
                ],
                "losses": [{"year": 2024, "amount": 1000, "cause": "water"}],
            },
        )
        assert created.status_code == 200
        submission = created.json()
        assert submission["status"] == "incomplete"
        assert submission["can_bind"] is False
        sid = submission["submission_id"]

        quoted = client.post(f"/api/v1/submissions/{sid}/quote")
        assert quoted.status_code == 200
        assert quoted.json()["quote"]["policy_id"] == "POL-UW-SUB"

        blocked = client.post(
            "/api/v1/uw/decision",
            json={
                "policy_id": "POL-UW-SUB",
                "action": "accept",
                "underwriter": "Demo UW",
                "submission_id": sid,
            },
        )
        assert blocked.status_code == 422
        assert "documents_incomplete" in blocked.json()["detail"]


def test_demo_book_covers_appetite_tones():
    tones = {item["tone"] for item in CASES}
    assert {"accept", "refer", "decline", "clamp", "fault"} <= tones
    payload = payload_from_fields(CASES[0]["fields"])
    result = quote_policy(payload)
    assert result["uw_recommendation"] == "accept"
    assert tone_for_quote(result) == "accept"
    excluded = next(item for item in CASES if item["id"] == "POL-EXCL-01")
    declined = quote_policy(payload_from_fields(excluded["fields"]))
    assert declined["uw_recommendation"] == "decline"
