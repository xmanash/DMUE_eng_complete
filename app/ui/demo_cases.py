"""Synthetic book of business for a guided demo. Not live policy data."""

from copy import deepcopy
from typing import Any, Dict, List

BASE = {
    "prev_premium": 120.0,
    "hard_brakes": 1,
    "night_pct_ui": 10,
    "speed_violations": 0,
    "total_miles": 400.0,
    "moisture_pct": 20,
    "precip_mm": 0.0,
    "wind_mph": 0.0,
    "use_bbox": False,
    "min_lon": 30.0,
    "min_lat": 14.0,
    "max_lon": 31.0,
    "max_lat": 15.0,
    "model_route": "dmue-full-v1",
    "include_home": False,
    "home_prev_premium": 150.0,
    "home_moisture_pct": 20,
    "include_commercial": False,
    "commercial_prev_premium": 300.0,
    "commercial_tiv": 500000.0,
    "commercial_occupancy": "office",
}


def _case(case_id: str, label: str, tone: str, blurb: str, **fields) -> Dict[str, Any]:
    """Merge overrides onto BASE and stamp policy_id."""
    merged = deepcopy(BASE)
    merged.update(fields)
    merged["policy_id"] = case_id
    return {
        "id": case_id,
        "label": label,
        "tone": tone,
        "blurb": blurb,
        "fields": merged,
    }


CASES: List[Dict[str, Any]] = [
    _case(
        "POL-ACCEPT-01",
        "Accept · smooth auto",
        "accept",
        "Low telematics score. Inside appetite.",
        hard_brakes=1,
        night_pct_ui=8,
        speed_violations=0,
    ),
    _case(
        "POL-ACCEPT-02",
        "Accept · daylight only",
        "accept",
        "No night miles, no speeding, gentle braking.",
        hard_brakes=0,
        night_pct_ui=0,
        speed_violations=0,
        total_miles=220.0,
    ),
    _case(
        "POL-REFER-01",
        "Refer · speeding",
        "refer",
        "Score in the 80s. Appetite refers; UW may override.",
        hard_brakes=6,
        night_pct_ui=0,
        speed_violations=3,
    ),
    _case(
        "POL-REFER-02",
        "Refer · night driving",
        "refer",
        "Night share above 25% plus frequent hard braking.",
        hard_brakes=6,
        night_pct_ui=40,
        speed_violations=0,
    ),
    _case(
        "POL-REFER-03",
        "Refer · drought box",
        "refer",
        "Sahel fixture. NDVI under 0.30 triggers refer even if score is moderate.",
        hard_brakes=1,
        night_pct_ui=10,
        speed_violations=0,
        use_bbox=True,
    ),
    _case(
        "POL-DECLINE-01",
        "Decline · stacked auto",
        "decline",
        "Hard brakes, night, and speeding. Score at or above 95.",
        hard_brakes=6,
        night_pct_ui=35,
        speed_violations=3,
        total_miles=450.0,
    ),
    _case(
        "POL-CLAMP-01",
        "Clamp · prior $80",
        "clamp",
        "High risk vs a low prior premium. Filing cap applies.",
        prev_premium=80.0,
        hard_brakes=6,
        night_pct_ui=35,
        speed_violations=3,
    ),
    _case(
        "POL-FAULT-01",
        "Fault · brake sensor",
        "fault",
        "Hard-brake rate above 20 is a sensor fault, not a risk factor.",
        hard_brakes=25,
        night_pct_ui=10,
        speed_violations=0,
    ),
    _case(
        "POL-WX-01",
        "Weather · wind and rain",
        "refer",
        "High wind and heavy rain add environment risk on Full.",
        hard_brakes=1,
        precip_mm=60.0,
        wind_mph=48.0,
    ),
    _case(
        "POL-MOIST-01",
        "Home moisture spike",
        "refer",
        "Moisture at 90% adds home risk on Full.",
        moisture_pct=90,
        hard_brakes=1,
    ),
    _case(
        "POL-HOME-01",
        "Account · auto + home",
        "accept",
        "Two lines. Account premium is the sum of bounded line premiums.",
        include_home=True,
        home_prev_premium=160.0,
        home_moisture_pct=18,
        hard_brakes=1,
        night_pct_ui=5,
    ),
    _case(
        "POL-HOME-02",
        "Account · wet home",
        "refer",
        "Clean auto with a high-moisture home line.",
        include_home=True,
        home_prev_premium=180.0,
        home_moisture_pct=92,
        hard_brakes=0,
        night_pct_ui=5,
        speed_violations=0,
    ),
    _case(
        "POL-COMM-01",
        "Commercial · office",
        "accept",
        "Thin commercial stub, office occupancy, modest TIV.",
        include_commercial=True,
        commercial_occupancy="office",
        commercial_tiv=250000.0,
        commercial_prev_premium=280.0,
        hard_brakes=1,
    ),
    _case(
        "POL-COMM-02",
        "Commercial · warehouse",
        "refer",
        "Warehouse load plus high TIV.",
        include_commercial=True,
        commercial_occupancy="warehouse",
        commercial_tiv=1_250_000.0,
        commercial_prev_premium=400.0,
        hard_brakes=1,
    ),
    _case(
        "POL-EXCL-01",
        "Decline · excluded occupancy",
        "decline",
        "Commercial occupancy excluded from appetite. Hard decline.",
        include_commercial=True,
        commercial_occupancy="excluded",
        commercial_tiv=100000.0,
        commercial_prev_premium=300.0,
        hard_brakes=1,
        night_pct_ui=5,
        speed_violations=0,
    ),
]

CASES_BY_ID = {item["id"]: item for item in CASES}

TONE_COLORS = {
    "accept": {"bg": "#14532D", "fg": "#BBF7D0", "bar": "#4ADE80", "label": "ACCEPT"},
    "refer": {"bg": "#713F12", "fg": "#FEF08A", "bar": "#FACC15", "label": "REFER"},
    "decline": {"bg": "#7F1D1D", "fg": "#FECACA", "bar": "#F87171", "label": "DECLINE"},
    "clamp": {"bg": "#7C2D12", "fg": "#FFEDD5", "bar": "#FB923C", "label": "CLAMP"},
    "fault": {"bg": "#4C1D95", "fg": "#E9D5FF", "bar": "#C084FC", "label": "SENSOR"},
    "incomplete": {"bg": "#831843", "fg": "#FBCFE8", "bar": "#F472B6", "label": "DOCS"},
}


def payload_from_fields(fields: Dict[str, Any]) -> Dict[str, Any]:
    auto = {
        "policy_id": fields["policy_id"],
        "hard_brakes_per_100mi": fields["hard_brakes"],
        "night_miles_pct": fields["night_pct_ui"] / 100.0,
        "speed_violations": int(fields["speed_violations"]),
        "total_miles": fields["total_miles"],
        "previous_premium": fields["prev_premium"],
        "iot_moisture": fields["moisture_pct"] / 100.0,
        "weather_precip_mm": fields["precip_mm"],
        "weather_wind_mph": fields["wind_mph"],
        "model_route": fields.get("model_route") or "dmue-full-v1",
    }
    bbox = None
    if fields.get("use_bbox"):
        bbox = [
            fields["min_lon"],
            fields["min_lat"],
            fields["max_lon"],
            fields["max_lat"],
        ]
        auto["bbox"] = bbox
    if not fields.get("include_home") and not fields.get("include_commercial"):
        return auto
    lines: Dict[str, Any] = {
        "auto": {k: v for k, v in auto.items() if k != "policy_id"}
    }
    if fields.get("include_home"):
        home = {
            "previous_premium": fields["home_prev_premium"],
            "iot_moisture": fields["home_moisture_pct"] / 100.0,
            "weather_precip_mm": fields["precip_mm"],
            "weather_wind_mph": fields["wind_mph"],
        }
        if bbox:
            home["bbox"] = bbox
        lines["home"] = home
    if fields.get("include_commercial"):
        lines["commercial"] = {
            "previous_premium": fields["commercial_prev_premium"],
            "tiv": fields["commercial_tiv"],
            "occupancy": fields["commercial_occupancy"],
        }
    return {
        "policy_id": fields["policy_id"],
        "previous_premium": fields["prev_premium"],
        "model_route": fields.get("model_route") or "dmue-full-v1",
        "lines": lines,
    }


def tone_for_quote(data: Dict[str, Any]) -> str:
    """UI color: decline > clamp > sensor > refer/accept."""
    rec = str((data or {}).get("uw_recommendation") or "")
    if rec == "decline":
        return "decline"
    if data.get("rate_clamped"):
        return "clamp"
    anomalies = " ".join(data.get("anomalies") or []).lower()
    if "malfunction" in anomalies or "fault" in anomalies:
        return "fault"
    if rec == "refer":
        return "refer"
    if rec == "accept":
        return "accept"
    return "refer"


def banner_html(title: str, body: str, tone: str) -> str:
    colors = TONE_COLORS.get(tone, TONE_COLORS["refer"])
    return (
        f'<div class="uw-banner" style="background:{colors["bg"]};color:{colors["fg"]};'
        f'border-left:8px solid {colors["bar"]};padding:14px 16px;border-radius:10px;'
        f'margin:8px 0 14px 0;">'
        f'<div style="font-weight:700;letter-spacing:0.06em;font-size:0.78rem;">'
        f'{colors["label"]}</div>'
        f'<div style="font-size:1.05rem;font-weight:600;margin-top:4px;">{title}</div>'
        f'<div style="margin-top:4px;opacity:0.95;">{body}</div></div>'
    )
