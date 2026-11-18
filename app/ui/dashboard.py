import os
import sys
import time
from pathlib import Path
from urllib.parse import quote

import altair as alt
import pandas as pd
import requests
import streamlit as st

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.ui.demo_cases import (
    CASES,
    CASES_BY_ID,
    TONE_COLORS,
    banner_html,
    payload_from_fields,
    tone_for_quote,
)

API_URL = os.getenv("DMUE_API_URL", "http://127.0.0.1:8000").rstrip("/")
LOCAL_ENV = os.getenv("DMUE_ENV", "local")
API_KEY = os.getenv("DMUE_API_KEY", "").strip()

DEFAULTS = {
    "policy_id": "POL-98234",
    "prev_premium": 120.0,
    "hard_brakes": 6,
    "night_pct_ui": 35,
    "speed_violations": 3,
    "total_miles": 450.0,
    "moisture_pct": 20,
    "precip_mm": 0.0,
    "wind_mph": 0.0,
    "use_bbox": False,
    "min_lon": 30.0,
    "min_lat": 14.0,
    "max_lon": 31.0,
    "max_lat": 15.0,
    "model_route": "dmue-full-v1",
    "sentinel_live": False,
    "include_home": False,
    "home_prev_premium": 150.0,
    "home_moisture_pct": 20,
    "include_commercial": False,
    "commercial_prev_premium": 300.0,
    "commercial_tiv": 500000.0,
    "commercial_occupancy": "office",
    "uw_underwriter": "",
    "uw_note": "",
    "broker_name": "",
    "broker_agency": "",
    "broker_aor": False,
    "effective_date": "2026-01-01",
    "doc_acord_125": True,
    "doc_loss_runs": False,
    "doc_sov": False,
}

st.set_page_config(
    page_title="DMUE Underwriting Console",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown(
    """
    <style>
    @import url("https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&display=swap");
    html, body, [class*="css"] { font-family: "IBM Plex Sans", "Segoe UI", sans-serif; }
    .stApp { background: #0B1220; }
    .stApp, .stApp p, .stApp span, .stApp label, .stApp h1, .stApp h2, .stApp h3 {
        color: #E8EEF7;
    }
    [data-testid="stHeader"], [data-testid="stToolbar"], #MainMenu, footer {
        visibility: hidden; height: 0;
    }
    [data-testid="stSidebar"] {
        background: #111A2E;
        border-right: 1px solid #243049;
    }
    [data-testid="stSidebar"] * { color: #D7E0EE !important; }
    div[data-testid="stMetric"] {
        background: #151F35;
        border: 1px solid #2A3A58;
        border-radius: 10px;
        padding: 12px 16px;
    }
    .hero {
        background: linear-gradient(90deg, #151F35 0%, #1A2744 100%);
        border: 1px solid #2A3A58;
        border-radius: 12px;
        padding: 18px 22px;
        margin-bottom: 16px;
    }
    .hero h1 { margin: 0; font-size: 1.45rem; letter-spacing: -0.03em; color: #F8FAFC; }
    .hero p { margin: 6px 0 0 0; color: #9AA8C2; font-size: 0.92rem; }
    .chip {
        display: inline-block;
        padding: 2px 10px;
        border-radius: 999px;
        font-size: 0.75rem;
        font-weight: 600;
        letter-spacing: 0.04em;
        margin-right: 8px;
        background: #0F766E;
        color: #ECFDF5;
    }
    .chip.staging { background: #B45309; }
    .chip.prod, .chip.production { background: #BE123C; }
    .chip.ci { background: #1D4ED8; }
    .chip.demo { background: #0F766E; }
    .st-key-reprice button {
        background: #0F766E !important; color: #fff !important;
        border: 1px solid #14B8A6 !important; border-radius: 8px !important; font-weight: 600 !important;
    }
    .st-key-refresh button {
        background: #1D4ED8 !important; color: #fff !important;
        border: 1px solid #3B82F6 !important; border-radius: 8px !important; font-weight: 600 !important;
    }
    .st-key-reset button {
        background: #334155 !important; color: #fff !important;
        border: 1px solid #64748B !important; border-radius: 8px !important; font-weight: 600 !important;
    }
    .st-key-load_case button, .st-key-price_book button {
        background: #FACC15 !important; color: #1C1917 !important;
        border: 1px solid #CA8A04 !important; border-radius: 8px !important; font-weight: 700 !important;
    }
    .st-key-uw_accept button {
        background: #16A34A !important; color: #052E16 !important;
        border: 1px solid #4ADE80 !important; border-radius: 8px !important; font-weight: 700 !important;
    }
    .st-key-uw_refer button {
        background: #EAB308 !important; color: #1C1917 !important;
        border: 1px solid #FDE047 !important; border-radius: 8px !important; font-weight: 700 !important;
    }
    .st-key-uw_decline button {
        background: #DC2626 !important; color: #FEF2F2 !important;
        border: 1px solid #F87171 !important; border-radius: 8px !important; font-weight: 700 !important;
    }
    .chip.accept { background: #16A34A; color: #052E16; }
    .chip.refer { background: #EAB308; color: #1C1917; }
    .chip.decline { background: #DC2626; color: #FEF2F2; }
    .chip.clamp { background: #EA580C; color: #FFF7ED; }
    .chip.fault { background: #7C3AED; color: #F5F3FF; }
    .chip.live { background: #0D9488; color: #ECFDF5; }
    .chip.local { background: #475569; color: #F8FAFC; }
    .chip.fallback { background: #D97706; color: #FFFBEB; }
    </style>
    """,
    unsafe_allow_html=True,
)


def api_headers():
    if not API_KEY:
        return {}
    return {"X-API-Key": API_KEY}


def format_api_detail(detail) -> str:
    if isinstance(detail, str):
        text = detail
    elif isinstance(detail, list):
        parts = []
        for item in detail:
            if isinstance(item, dict):
                loc = ".".join(str(part) for part in item.get("loc", []) if part != "body")
                msg = str(item.get("msg", item))
                parts.append(f"{loc}: {msg}" if loc else msg)
            else:
                parts.append(str(item))
        text = "; ".join(parts)
    else:
        text = str(detail)
    lower = text.lower()
    if "documents_incomplete" in lower:
        return (
            "This submission cannot bind yet: required documents are missing "
            "(ACORD 125, loss runs, or SOV). Quoting is still allowed."
        )
    if "prohibited factor" in lower:
        return (
            "This quote was rejected because it includes a prohibited rating factor "
            "(for example gender, ZIP, or credit). DMUE prices from behavior only."
        )
    if "explanation failed" in lower or ("eval" in lower and "gate" in lower):
        return (
            "The explanation failed the eval gates (leaks, coverage, or reading level). "
            "The quote was not stored."
        )
    if "invalid or missing api key" in lower:
        return "The API requires an API key. Set DMUE_API_KEY on both the API and this console."
    if "rate limit" in lower:
        return "The API rate limit was reached. Wait a minute and try again."
    return text


def reset_inputs():
    for key, value in DEFAULTS.items():
        st.session_state[key] = value
    st.session_state.last_quote = None
    st.session_state.quote_error = ""
    st.session_state.history_loaded_for = None
    st.session_state.job_status = None
    st.session_state.controls_error = ""


for key, value in DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = value

if st.session_state.get("pending_case"):
    case = CASES_BY_ID.get(st.session_state.pop("pending_case"))
    if case:
        for key, value in case["fields"].items():
            st.session_state[key] = value
        st.session_state.last_quote = None
        st.session_state.quote_error = ""
        st.session_state.history_loaded_for = None
        st.session_state.desk_message = ""
        st.session_state.active_tone = case["tone"]


def fetch_ops():
    try:
        response = requests.get(
            f"{API_URL}/api/v1/ops/status", headers=api_headers(), timeout=8
        )
        response.raise_for_status()
        return response.json()
    except Exception:
        return {
            "environment": LOCAL_ENV,
            "version": "offline",
            "default_model_route": DEFAULTS["model_route"],
            "routes": [],
            "cost": {"quotes": 0, "total_usd": 0.0, "by_route": {}, "recent": []},
            "traces": [],
            "observability": {},
        }


def build_quote_payload():
    auto = {
        "policy_id": st.session_state.policy_id,
        "hard_brakes_per_100mi": st.session_state.hard_brakes,
        "night_miles_pct": st.session_state.night_pct_ui / 100.0,
        "speed_violations": int(st.session_state.speed_violations),
        "total_miles": st.session_state.total_miles,
        "previous_premium": st.session_state.prev_premium,
        "iot_moisture": st.session_state.moisture_pct / 100.0,
        "weather_precip_mm": st.session_state.precip_mm,
        "weather_wind_mph": st.session_state.wind_mph,
        "model_route": st.session_state.model_route,
        "sentinel_live": bool(st.session_state.get("sentinel_live")),
    }
    bbox = None
    if st.session_state.use_bbox:
        bbox = [
            st.session_state.min_lon,
            st.session_state.min_lat,
            st.session_state.max_lon,
            st.session_state.max_lat,
        ]
        auto["bbox"] = bbox
    if not st.session_state.include_home and not st.session_state.include_commercial:
        return auto
    lines = {"auto": {k: v for k, v in auto.items() if k != "policy_id"}}
    if st.session_state.include_home:
        home = {
            "previous_premium": st.session_state.home_prev_premium,
            "iot_moisture": st.session_state.home_moisture_pct / 100.0,
            "weather_precip_mm": st.session_state.precip_mm,
            "weather_wind_mph": st.session_state.wind_mph,
        }
        if bbox:
            home["bbox"] = bbox
        lines["home"] = home
    if st.session_state.include_commercial:
        lines["commercial"] = {
            "previous_premium": st.session_state.commercial_prev_premium,
            "tiv": st.session_state.commercial_tiv,
            "occupancy": st.session_state.commercial_occupancy,
        }
    return {
        "policy_id": st.session_state.policy_id,
        "previous_premium": st.session_state.prev_premium,
        "model_route": st.session_state.model_route,
        "sentinel_live": bool(st.session_state.get("sentinel_live")),
        "lines": lines,
    }


def fetch_history(policy_id: str):
    response = requests.get(
        f"{API_URL}/api/v1/policy/{quote(policy_id, safe='')}/context",
        params={"limit": 12},
        headers=api_headers(),
        timeout=15,
    )
    response.raise_for_status()
    return response.json().get("metadatas") or []


def load_history(policy_id: str):
    try:
        st.session_state.history_rows = fetch_history(policy_id)
        st.session_state.history_loaded_for = policy_id
        st.session_state.history_error = ""
    except Exception as exc:
        st.session_state.history_rows = st.session_state.get("history_rows") or []
        st.session_state.history_error = str(exc)


def chart_frame(history, previous_premium, latest):
    rows = []
    for meta in history or []:
        if not meta or "premium" not in meta:
            continue
        rows.append(
            {
                "recorded_at": str(meta.get("recorded_at") or ""),
                "premium": float(meta["premium"]),
                "risk_score": float(meta.get("risk_score") or 0),
            }
        )
    rows.sort(key=lambda row: row["recorded_at"])
    if latest:
        point = {
            "recorded_at": "latest",
            "premium": float(latest["final_bounded_premium"]),
            "risk_score": float(latest["risk_score"]),
        }
        already = any(
            abs(row["premium"] - point["premium"]) < 0.01
            and abs(row["risk_score"] - point["risk_score"]) < 0.01
            for row in rows
        )
        if not already:
            rows.append(point)
    if len(rows) == 1:
        rows.insert(0, {"recorded_at": "", "premium": float(previous_premium), "risk_score": None})

    labels = []
    seen = {}
    for index, row in enumerate(rows, start=1):
        if row["risk_score"] is None:
            label = "Prior"
        elif row["recorded_at"] not in ("", "latest"):
            label = row["recorded_at"][5:16].replace("T", " ")
        else:
            label = f"Quote {index}"
        seen[label] = seen.get(label, 0) + 1
        labels.append(label if seen[label] == 1 else f"{label} ({seen[label]})")

    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame["Quote"] = labels
    return frame


def render_trend(frame):
    st.subheader("Premium and risk trend")
    if frame.empty:
        st.info("Re-underwrite a policy or refresh the trend to plot quote history.")
        return
    premium = (
        alt.Chart(frame)
        .mark_line(point=True, color="#2DD4BF", strokeWidth=2.5)
        .encode(
            x=alt.X("Quote:N", sort=None, title=None),
            y=alt.Y("premium:Q", title="Premium ($)", scale=alt.Scale(zero=False)),
            tooltip=[
                alt.Tooltip("Quote:N"),
                alt.Tooltip("premium:Q", title="Premium ($)", format=".2f"),
                alt.Tooltip("risk_score:Q", title="Risk score", format=".1f"),
            ],
        )
    )
    scored = frame.dropna(subset=["risk_score"])
    risk = (
        alt.Chart(scored)
        .mark_line(point=True, color="#60A5FA", strokeWidth=2.5)
        .encode(
            x=alt.X("Quote:N", sort=None, title=None),
            y=alt.Y("risk_score:Q", title="Risk score", scale=alt.Scale(domain=[0, 100])),
        )
    )
    chart = (
        alt.layer(premium, risk)
        .resolve_scale(y="independent")
        .properties(height=300)
        .configure_view(strokeWidth=0)
        .configure_axis(labelColor="#94A3B8", titleColor="#E2E8F0", gridColor="#1E293B")
    )
    st.altair_chart(chart, width="stretch")
    st.caption("Teal is the bounded monthly premium. Blue is the behavioral risk score.")


ops = fetch_ops()
env_name = str(ops.get("environment") or LOCAL_ENV).lower()
routes = ops.get("routes") or [
    {"id": "dmue-rules-v1", "label": "Rules", "description": "Telemetry only"},
    {"id": "dmue-full-v1", "label": "Full", "description": "All signals"},
    {"id": "dmue-explain-v1", "label": "Explain", "description": "Full plus reserved explanation cost"},
]
route_ids = [item["id"] for item in routes]
if st.session_state.model_route not in route_ids:
    st.session_state.model_route = ops.get("default_model_route") or DEFAULTS["model_route"]

with st.sidebar:
    st.markdown("**Control plane**")
    st.caption(f"API `{API_URL}`")
    st.caption(f"Release `{ops.get('version', 'unknown')}`")
    labels = {item["id"]: f"{item.get('label', item['id'])} · {item['id']}" for item in routes}
    st.selectbox(
        "Model route",
        options=route_ids,
        format_func=lambda item: labels.get(item, item),
        key="model_route",
        help="Rules is cheapest. Full uses weather, moisture, and satellite. Explain reserves a higher unit cost.",
    )
    selected = next((item for item in routes if item["id"] == st.session_state.model_route), {})
    st.caption(selected.get("description") or "")
    if selected.get("cost_usd") is not None:
        sat = selected.get("use_satellite")
        extra = " plus $0.0005 if satellite runs" if sat else ""
        st.caption(f"Unit cost ${selected['cost_usd']:.4f}{extra}")
    cost = ops.get("cost") or {}
    st.metric("Process quote cost", f"${float(cost.get('total_usd') or 0):.4f}")
    st.caption(f"{cost.get('quotes', 0)} quotes on this API process")
    sentinel_ops = ops.get("sentinel") or {}
    creds_ok = bool(sentinel_ops.get("credentials_configured"))
    st.checkbox(
        "Live Sentinel Hub",
        key="sentinel_live",
        disabled=not creds_ok,
        help="Opt-in Sentinel-2 NDVI/NDWI. Falls back to local bands on failure.",
    )
    if not creds_ok:
        st.caption(
            "Live fetch needs SENTINEL_CLIENT_ID and SENTINEL_CLIENT_SECRET "
            "(SENTINEL_API_TOKEN can stand in for the secret)."
        )
    elif sentinel_ops.get("live_enabled"):
        st.caption("SENTINEL_LIVE_FETCH is on for this API process. Uncheck to force local bands.")
    st.markdown("**Demo book**")
    st.caption("Synthetic cases. Colors: green accept, yellow refer, red decline, orange clamp, purple sensor.")
    case_ids = [item["id"] for item in CASES]
    st.selectbox(
        "Synthetic case",
        options=case_ids,
        format_func=lambda item: CASES_BY_ID[item]["label"],
        key="demo_pick",
    )
    picked = CASES_BY_ID.get(st.session_state.demo_pick)
    if picked:
        st.caption(picked["blurb"])
    load_col, book_col = st.columns(2)
    with load_col:
        if st.button("Load case", key="load_case", type="primary", width="stretch"):
            st.session_state.pending_case = st.session_state.demo_pick
            st.rerun()
    with book_col:
        if st.button("Price all", key="price_book", type="primary", width="stretch"):
            book = []
            for item in CASES:
                try:
                    posted = requests.post(
                        f"{API_URL}/api/v1/reprice",
                        json=payload_from_fields(item["fields"]),
                        headers=api_headers(),
                        timeout=20,
                    )
                    if posted.status_code == 200:
                        body = posted.json()
                        book.append(
                            {
                                "policy_id": body.get("policy_id"),
                                "tone": tone_for_quote(body),
                                "uw": body.get("uw_recommendation"),
                                "score": body.get("risk_score"),
                                "premium": body.get("final_bounded_premium"),
                            }
                        )
                    else:
                        book.append(
                            {
                                "policy_id": item["id"],
                                "tone": item["tone"],
                                "uw": "error",
                                "score": None,
                                "premium": None,
                            }
                        )
                except Exception:
                    book.append(
                        {
                            "policy_id": item["id"],
                            "tone": "fault",
                            "uw": "offline",
                            "score": None,
                            "premium": None,
                        }
                    )
            st.session_state.demo_book = book
            st.session_state.book_message = f"Priced {len(book)} synthetic policies."

chip_class = (
    env_name if env_name in {"local", "staging", "prod", "production", "ci", "demo"} else "local"
)
quote_tone = tone_for_quote(st.session_state.get("last_quote") or {})
if st.session_state.get("last_quote"):
    rec_chip = f'<span class="chip {quote_tone}">{quote_tone.upper()}</span>'
else:
    rec_chip = ""
st.markdown(
    f"""
    <div class="hero">
      <span class="chip {chip_class}">{env_name.upper()}</span>
      <span class="chip">{st.session_state.model_route}</span>
      {rec_chip}
      <h1>DMUE underwriting console</h1>
      <p>Behavioral pricing inside a +25% / −20% filing band. Satellite indices default to local bands. Live Sentinel Hub is opt-in in the sidebar when credentials are set. This console is an underwriting core, not a production bind.</p>
      <p class="legend">
        <span class="chip accept">ACCEPT</span>
        <span class="chip refer">REFER</span>
        <span class="chip decline">DECLINE</span>
        <span class="chip clamp">CLAMP</span>
        <span class="chip fault">SENSOR</span>
      </p>
    </div>
    """,
    unsafe_allow_html=True,
)
if st.session_state.get("demo_book"):
    book_frame = pd.DataFrame(st.session_state.demo_book)

    def _style_tone(val):
        colors = TONE_COLORS.get(str(val), {})
        if not colors:
            return ""
        return f"background-color: {colors['bg']}; color: {colors['fg']}; font-weight: 700;"

    try:
        styled = book_frame.style.map(_style_tone, subset=["tone", "uw"])
    except Exception:
        styled = book_frame
    st.dataframe(styled, width="stretch", hide_index=True)
    if st.session_state.get("book_message"):
        st.caption(st.session_state.book_message)
if ops.get("version") == "offline":
    st.error(
        f"The API at {API_URL} is not reachable. Start uvicorn (or docker compose) before using the console."
    )

if st.session_state.get("history_loaded_for") != st.session_state.policy_id:
    load_history(st.session_state.policy_id)

quote_tab, desk_tab, intake_tab, controls_tab, ops_tab = st.tabs(
    ["Quote", "Desk", "Intake", "Controls", "Operations"]
)

with quote_tab:
    left, right = st.columns([1, 1], gap="large")
    with left:
        st.subheader("Telemetry")
        policy_id = st.text_input("Policy ID", key="policy_id")
        prev_premium = st.number_input(
            "Current base premium ($)", min_value=0.01, step=1.0, key="prev_premium"
        )
        hard_brakes = st.slider("Hard brakes / 100 miles", 0, 30, key="hard_brakes")
        night_pct_ui = st.slider("Night driving (%)", 0, 100, key="night_pct_ui")
        speed_violations = st.number_input(
            "Speeding violations", min_value=0, step=1, key="speed_violations"
        )
        total_miles = st.number_input("Total miles", min_value=0.0, step=10.0, key="total_miles")
        moisture_pct = st.slider("Home moisture (%)", 0, 100, key="moisture_pct")
        precip_mm = st.number_input("Rainfall (mm)", min_value=0.0, step=1.0, key="precip_mm")
        wind_mph = st.number_input("Wind (mph)", min_value=0.0, step=1.0, key="wind_mph")
        use_bbox = st.checkbox("Include satellite bounding box", key="use_bbox")
        bbox = None
        if use_bbox:
            st.caption("The default box is the Sahel drought fixture. NDVI there is under 0.30.")
            lon_col, lat_col = st.columns(2)
            with lon_col:
                min_lon = st.number_input("Min longitude", key="min_lon")
                max_lon = st.number_input("Max longitude", key="max_lon")
            with lat_col:
                min_lat = st.number_input("Min latitude", key="min_lat")
                max_lat = st.number_input("Max latitude", key="max_lat")
            bbox = [min_lon, min_lat, max_lon, max_lat]

        st.checkbox("Include home line", key="include_home")
        if st.session_state.include_home:
            st.number_input("Home prior premium ($)", min_value=0.01, step=1.0, key="home_prev_premium")
            st.slider("Home moisture for home line (%)", 0, 100, key="home_moisture_pct")
        st.checkbox("Include commercial line", key="include_commercial")
        if st.session_state.include_commercial:
            st.number_input(
                "Commercial prior premium ($)", min_value=0.01, step=1.0, key="commercial_prev_premium"
            )
            st.number_input("Commercial TIV ($)", min_value=0.0, step=10000.0, key="commercial_tiv")
            st.selectbox(
                "Commercial occupancy",
                options=["office", "retail", "warehouse", "excluded"],
                key="commercial_occupancy",
            )

        reprice_col, refresh_col, reset_col = st.columns(3)
        with reprice_col:
            do_reprice = st.button("Re-underwrite", key="reprice", type="primary", width="stretch")
        with refresh_col:
            do_refresh = st.button("Refresh trend", key="refresh", type="primary", width="stretch")
        with reset_col:
            st.button("Reset inputs", key="reset", type="primary", width="stretch", on_click=reset_inputs)

    if do_refresh:
        load_history(policy_id)

    if do_reprice:
        payload = build_quote_payload()
        try:
            response = requests.post(
                f"{API_URL}/api/v1/reprice",
                json=payload,
                headers=api_headers(),
                timeout=30,
            )
            if response.status_code == 200:
                st.session_state.last_quote = response.json()
                st.session_state.quote_anchor = prev_premium
                st.session_state.quote_error = ""
                load_history(policy_id)
            else:
                detail = response.text
                try:
                    detail = response.json().get("detail", detail)
                except Exception:
                    pass
                st.session_state.quote_error = (
                    f"The engine rejected the quote: {format_api_detail(detail)}"
                )
        except Exception as exc:
            st.session_state.quote_error = f"The workbench could not reach the API at {API_URL}: {exc}"

    with right:
        st.subheader("Pricing")
        quote_error = st.session_state.get("quote_error") or ""
        data = st.session_state.get("last_quote")
        anchor = st.session_state.get("quote_anchor", prev_premium)
        if quote_error:
            st.error(quote_error)
        elif not data:
            st.info("Run Re-underwrite to price the current telemetry.")
        else:
            premium_col, risk_col, status_col, cost_col = st.columns(4)
            premium_col.metric(
                "Monthly premium",
                f"${data['final_bounded_premium']:.2f}",
                delta=f"{data['final_bounded_premium'] - anchor:.2f}",
            )
            risk_col.metric("Risk score", f"{data['risk_score']:.1f}")
            status_col.metric("Rate cap", "Applied" if data["rate_clamped"] else "Clear")
            cost_info = data.get("cost") or {}
            cost_col.metric("Quote cost", f"${float(cost_info.get('usd') or 0):.4f}")
            st.caption(
                f"Route {data.get('model_route_label', data.get('model_route', ''))} · "
                f"env {data.get('environment', env_name)}"
            )
            st.markdown(
                banner_html(
                    f"{data.get('policy_id')} · {str(data.get('uw_recommendation', '')).upper()}",
                    "; ".join(data.get("uw_reasons") or []) or "Inside appetite.",
                    tone_for_quote(data),
                ),
                unsafe_allow_html=True,
            )
            st.progress(
                min(max(data["risk_score"] / 100.0, 0.0), 1.0),
                text=f"Behavioral risk score {data['risk_score']}/100",
            )
            if data["rate_clamped"]:
                st.warning(data["regulatory_status"])
            else:
                st.success("Rate is inside the +25% / -20% filing band.")
            for anomaly in data.get("anomalies") or []:
                st.warning(anomaly)
            satellite = data.get("satellite")
            if satellite:
                source = str(satellite.get("satellite_source") or "local")
                if satellite.get("sentinel_live_fetch"):
                    chip = "live"
                    label = "LIVE"
                elif source == "local_fallback":
                    chip = "fallback"
                    label = "FALLBACK"
                else:
                    chip = "local"
                    label = "LOCAL"
                extra = satellite.get("sentinel_live_error") or ""
                st.markdown(
                    f'<p><span class="chip {chip}">{label}</span> '
                    f'NDVI {satellite["ndvi_index"]} · NDWI {satellite["ndwi_index"]} · '
                    f'{source}'
                    f'{(" · " + extra) if extra else ""}</p>',
                    unsafe_allow_html=True,
                )
            st.markdown("**Factor attribution**")
            reasons = data.get("attribution_reasons") or []
            if reasons:
                for reason in reasons:
                    st.write(f"- {reason}")
            else:
                st.write("No extra risk factors were found.")
            if data.get("recommendations"):
                st.markdown("**Actions for the policyholder**")
                for tip in data["recommendations"]:
                    st.write(f"- {tip}")
            lines = data.get("lines") or {}
            if lines:
                st.markdown("**Lines**")
                st.dataframe(
                    [
                        {
                            "line": item.get("line"),
                            "risk": item.get("risk_score"),
                            "premium": item.get("final_bounded_premium"),
                            "clamped": item.get("rate_clamped"),
                        }
                        for item in lines.values()
                    ],
                    width="stretch",
                    hide_index=True,
                )
                st.caption(f"Account premium ${data.get('account_premium', data['final_bounded_premium']):.2f}")
            decisions = data.get("decisions") or []
            if decisions:
                st.markdown("**Decisions**")
                st.dataframe(
                    [
                        {
                            "layer": item.get("layer"),
                            "name": item.get("name"),
                            "action": item.get("action"),
                        }
                        for item in decisions
                    ],
                    width="stretch",
                    hide_index=True,
                )
            evals = data.get("evals") or {}
            if evals:
                st.caption(
                    f"Leaks {evals.get('prohibited_term_leaks', 0)} · "
                    f"coverage {evals.get('factor_coverage', 0)} · "
                    f"reading ease {evals.get('flesch_reading_ease', 0)} · "
                    f"grade {evals.get('flesch_grade_level', 0)}"
                )

    history_error = st.session_state.get("history_error") or ""
    if history_error:
        st.warning(f"Quote history is unavailable: {history_error}")
    render_trend(
        chart_frame(
            st.session_state.get("history_rows") or [],
            prev_premium,
            st.session_state.get("last_quote"),
        )
    )

with desk_tab:
    st.subheader("Underwriter decision desk")
    desk_quote = st.session_state.get("last_quote")
    if not desk_quote:
        st.info("Price a policy on the Quote tab first. The appetite recommendation appears here.")
    else:
        st.markdown(
            banner_html(
                f"{desk_quote.get('policy_id')} · {str(desk_quote.get('uw_recommendation', '')).upper()}",
                f"Trace {desk_quote.get('trace_id', '')}. "
                + "; ".join(desk_quote.get("uw_reasons") or []),
                tone_for_quote(desk_quote),
            ),
            unsafe_allow_html=True,
        )
        for reason in desk_quote.get("uw_reasons") or []:
            st.write(f"- {reason}")
        st.text_input("Underwriter", key="uw_underwriter")
        st.text_area("Note", key="uw_note")
        accept_col, refer_col, decline_col = st.columns(3)
        desk_action = None
        with accept_col:
            if st.button("Accept / bind", key="uw_accept", type="primary", width="stretch"):
                desk_action = "accept"
        with refer_col:
            if st.button("Refer", key="uw_refer", type="primary", width="stretch"):
                desk_action = "refer"
        with decline_col:
            if st.button("Decline", key="uw_decline", type="primary", width="stretch"):
                desk_action = "decline"
        if desk_action:
            try:
                resp = requests.post(
                    f"{API_URL}/api/v1/uw/decision",
                    json={
                        "policy_id": desk_quote.get("policy_id"),
                        "quote_trace_id": desk_quote.get("trace_id", ""),
                        "action": desk_action,
                        "underwriter": st.session_state.uw_underwriter,
                        "note": st.session_state.uw_note,
                        "submission_id": (st.session_state.get("submission") or {}).get(
                            "submission_id", ""
                        )
                        if desk_quote.get("policy_id")
                        == (st.session_state.get("submission") or {}).get("policy_id")
                        else "",
                    },
                    headers=api_headers(),
                    timeout=15,
                )
                if resp.status_code == 200:
                    entry = resp.json()
                    st.session_state.desk_message = (
                        f"Decision {entry['action']} recorded. Status {entry['uw_status']}."
                        + (" Override of appetite." if entry.get("override") else "")
                    )
                else:
                    detail = resp.text
                    try:
                        detail = resp.json().get("detail", detail)
                    except Exception:
                        pass
                    st.session_state.desk_message = format_api_detail(detail)
            except Exception as exc:
                st.session_state.desk_message = f"Could not reach the API: {exc}"
        if st.session_state.get("desk_message"):
            st.info(st.session_state.desk_message)
        try:
            packet_resp = requests.get(
                f"{API_URL}/api/v1/uw/packet/{quote(str(desk_quote.get('policy_id')), safe='')}",
                headers=api_headers(),
                timeout=10,
            )
            if packet_resp.status_code == 200:
                import json as _json

                st.download_button(
                    "Download quote packet (JSON)",
                    data=_json.dumps(packet_resp.json(), indent=2),
                    file_name=f"packet-{desk_quote.get('policy_id')}.json",
                    mime="application/json",
                )
        except Exception:
            pass
    st.subheader("Open referrals")
    try:
        refs = requests.get(
            f"{API_URL}/api/v1/uw/referrals", headers=api_headers(), timeout=10
        )
        referrals = refs.json().get("referrals") or [] if refs.status_code == 200 else []
    except Exception:
        referrals = []
    if referrals:
        st.dataframe(referrals, width="stretch", hide_index=True)
    else:
        st.info("No open referrals on this process yet.")

with intake_tab:
    st.subheader("Submission intake")
    st.write("ACORD-like JSON intake (not ACORD XML). Missing required documents block bind, not quoting.")
    st.text_input("Broker name", key="broker_name")
    st.text_input("Agency", key="broker_agency")
    st.checkbox("Agent of record (AOR)", key="broker_aor")
    st.text_input("Effective date", key="effective_date")
    st.markdown("**Documents**")
    st.checkbox("ACORD 125 received", key="doc_acord_125")
    st.checkbox("Loss runs received", key="doc_loss_runs")
    st.checkbox("SOV received", key="doc_sov")
    create_col, quote_col = st.columns(2)
    with create_col:
        do_create_sub = st.button("Create submission", key="create_sub", type="primary", width="stretch")
    with quote_col:
        do_quote_sub = st.button("Quote submission", key="quote_sub", type="primary", width="stretch")
    if do_create_sub:
        current = build_quote_payload()
        sub_lines = current.get("lines") or {
            "auto": {k: v for k, v in current.items() if k != "policy_id"}
        }
        docs = [
            {"name": "acord_125", "status": "received" if st.session_state.doc_acord_125 else "missing"},
            {"name": "loss_runs", "status": "received" if st.session_state.doc_loss_runs else "missing"},
            {"name": "sov", "status": "received" if st.session_state.doc_sov else "missing"},
        ]
        try:
            resp = requests.post(
                f"{API_URL}/api/v1/submissions",
                json={
                    "policy_id": st.session_state.policy_id,
                    "broker": {
                        "name": st.session_state.broker_name,
                        "agency": st.session_state.broker_agency,
                        "aor": st.session_state.broker_aor,
                    },
                    "effective_date": st.session_state.effective_date,
                    "lines": sub_lines,
                    "model_route": st.session_state.model_route,
                    "documents": docs,
                    "losses": [],
                },
                headers=api_headers(),
                timeout=15,
            )
            if resp.status_code == 200:
                st.session_state.submission = resp.json()
                st.session_state.intake_message = (
                    f"Submission {resp.json()['submission_id']} is {resp.json()['status']}."
                )
            else:
                detail = resp.text
                try:
                    detail = resp.json().get("detail", detail)
                except Exception:
                    pass
                st.session_state.intake_message = format_api_detail(detail)
        except Exception as exc:
            st.session_state.intake_message = f"Could not reach the API: {exc}"
    if do_quote_sub:
        sub = st.session_state.get("submission") or {}
        if not sub.get("submission_id"):
            st.session_state.intake_message = "Create a submission first."
        else:
            try:
                resp = requests.post(
                    f"{API_URL}/api/v1/submissions/{quote(sub['submission_id'], safe='')}/quote",
                    headers=api_headers(),
                    timeout=30,
                )
                if resp.status_code == 200:
                    body = resp.json()
                    st.session_state.submission = body["submission"]
                    st.session_state.last_quote = body["quote"]
                    st.session_state.intake_message = (
                        f"Quoted. Submission is {body['submission']['status']}."
                    )
                else:
                    detail = resp.text
                    try:
                        detail = resp.json().get("detail", detail)
                    except Exception:
                        pass
                    st.session_state.intake_message = format_api_detail(detail)
            except Exception as exc:
                st.session_state.intake_message = f"Could not reach the API: {exc}"
    if st.session_state.get("intake_message"):
        st.info(st.session_state.intake_message)
    if st.session_state.get("submission"):
        st.json(st.session_state.submission)

with controls_tab:
    st.subheader("Guardrails and ingest")
    st.write(
        "These paths used to live only on HTTP. Use them here so a guided demo never leaves the console."
    )
    ingest_col, reject_col = st.columns(2)
    with ingest_col:
        do_ingest = st.button("Ingest current form", key="ingest", type="primary", width="stretch")
    with reject_col:
        do_prohibited = st.button(
            "Try prohibited key", key="prohibited", type="primary", width="stretch"
        )

    form_payload = build_quote_payload()

    if do_ingest:
        try:
            posted = requests.post(
                f"{API_URL}/api/v1/ingest",
                json=[form_payload],
                headers=api_headers(),
                timeout=15,
            )
            if posted.status_code != 202:
                detail = posted.text
                try:
                    detail = posted.json().get("detail", detail)
                except Exception:
                    pass
                st.session_state.controls_error = format_api_detail(detail)
                st.session_state.job_status = None
            else:
                job_id = posted.json()["job_id"]
                payload = None
                for _ in range(40):
                    status = requests.get(
                        f"{API_URL}/api/v1/jobs/{job_id}",
                        headers=api_headers(),
                        timeout=10,
                    )
                    payload = status.json() if status.status_code == 200 else None
                    if payload and payload.get("status") in {"done", "failed"}:
                        break
                    time.sleep(0.1)
                st.session_state.job_status = payload or {
                    "job_id": job_id,
                    "status": "queued",
                }
                st.session_state.controls_error = ""
                load_history(st.session_state.policy_id)
        except Exception as exc:
            st.session_state.controls_error = (
                f"The workbench could not reach the API at {API_URL}: {exc}"
            )

    if do_prohibited:
        blocked = dict(form_payload)
        blocked["gender"] = "not-used"
        try:
            response = requests.post(
                f"{API_URL}/api/v1/reprice",
                json=blocked,
                headers=api_headers(),
                timeout=15,
            )
            detail = response.text
            try:
                detail = response.json().get("detail", detail)
            except Exception:
                pass
            if response.status_code == 422:
                st.session_state.controls_error = format_api_detail(detail)
            else:
                st.session_state.controls_error = (
                    f"Expected HTTP 422, got {response.status_code}: {format_api_detail(detail)}"
                )
        except Exception as exc:
            st.session_state.controls_error = (
                f"The workbench could not reach the API at {API_URL}: {exc}"
            )

    controls_error = st.session_state.get("controls_error") or ""
    if controls_error:
        st.error(controls_error)
    job = st.session_state.get("job_status")
    if job:
        st.success(f"Ingest job `{job.get('job_id')}` is **{job.get('status')}**.")
        if job.get("results"):
            st.caption(f"{job.get('count', 0)} event(s) priced.")

with ops_tab:
    st.subheader("Environment")
    st.write(
        f"This console is pointed at **{API_URL}**. "
        f"The API reports environment **{ops.get('environment')}** and version **{ops.get('version')}**."
    )
    st.caption("Set DMUE_ENV and copy from env.example. Staging and production should not share a Chroma volume with local.")
    st.subheader("Model routes")
    st.dataframe(
        [
            {
                "Route": item.get("id"),
                "Label": item.get("label"),
                "Environment signals": item.get("use_environment"),
                "Satellite": item.get("use_satellite"),
                "Unit USD": item.get("cost_usd"),
            }
            for item in routes
        ],
        width="stretch",
        hide_index=True,
    )
    st.subheader("Cost ledger (this API process)")
    by_route = (ops.get("cost") or {}).get("by_route") or {}
    if by_route:
        st.bar_chart(pd.Series(by_route, name="usd"))
    recent = (ops.get("cost") or {}).get("recent") or []
    if recent:
        st.dataframe(pd.DataFrame(recent), width="stretch", hide_index=True)
    else:
        st.info("No priced quotes on this process yet.")
    st.subheader("Observability")
    obs = ops.get("observability") or {}
    st.write(
        f"Backend **{obs.get('backend', 'local')}**. "
        "Local JSONL traces are always on (no vendor). "
        "LangSmith is optional and uses the free developer tier when `LANGSMITH_API_KEY` is set."
    )
    if obs.get("langsmith"):
        st.caption(
            f"LangSmith project `{obs.get('langsmith_project')}`. "
            "Open https://smith.langchain.com to inspect runs."
        )
    else:
        st.caption(f"Local file `{obs.get('local_path', './data/observability/traces.jsonl')}`.")
    traces = ops.get("traces") or []
    if traces:
        st.dataframe(
            [
                {
                    "trace_id": item.get("trace_id"),
                    "action": item.get("action"),
                    "policy_id": item.get("policy_id"),
                    "ms": item.get("duration_ms"),
                    "route": item.get("route_id"),
                    "usd": item.get("cost_usd"),
                }
                for item in traces
            ],
            width="stretch",
            hide_index=True,
        )
    else:
        st.info("No traces on this process yet. Re-underwrite a policy to emit one.")
    st.caption("CI runs pytest and python -m app.harness on GitHub Actions. See .github/workflows/ci.yml.")
