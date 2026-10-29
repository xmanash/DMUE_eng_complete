import os
from urllib.parse import quote

import altair as alt
import pandas as pd
import requests
import streamlit as st

API_URL = os.getenv("DMUE_API_URL", "http://127.0.0.1:8000").rstrip("/")

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
}

st.set_page_config(page_title="DMUE Policy Workbench", layout="wide")
st.markdown(
    """
    <style>
    .stApp { background: #F4F7FB; }
    h1, h2, h3 { color: #0F172A; letter-spacing: -0.02em; }
    div[data-testid="stMetric"] {
        background: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 12px;
        padding: 12px 16px;
    }
    .st-key-reprice button {
        background: #0F766E !important;
        color: #FFFFFF !important;
        border: 1px solid #0F766E !important;
        border-radius: 8px !important;
        font-weight: 600 !important;
    }
    .st-key-reprice button:hover { background: #115E59 !important; border-color: #115E59 !important; }
    .st-key-refresh button {
        background: #1D4ED8 !important;
        color: #FFFFFF !important;
        border: 1px solid #1D4ED8 !important;
        border-radius: 8px !important;
        font-weight: 600 !important;
    }
    .st-key-refresh button:hover { background: #1E40AF !important; border-color: #1E40AF !important; }
    .st-key-reset button {
        background: #B45309 !important;
        color: #FFFFFF !important;
        border: 1px solid #B45309 !important;
        border-radius: 8px !important;
        font-weight: 600 !important;
    }
    .st-key-reset button:hover { background: #92400E !important; border-color: #92400E !important; }
    </style>
    """,
    unsafe_allow_html=True,
)

def reset_inputs():
    for key, value in DEFAULTS.items():
        st.session_state[key] = value
    st.session_state.last_quote = None
    st.session_state.quote_error = ""
    st.session_state.history_loaded_for = None


for key, value in DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = value

st.title("Dynamic Micro-Underwriting Engine")
st.caption("Underwriter workbench for behavioral pricing, filing caps, and quote history.")


def fetch_history(policy_id: str):
    response = requests.get(
        f"{API_URL}/api/v1/policy/{quote(policy_id, safe='')}/context",
        params={"limit": 12},
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
        rows.insert(
            0,
            {"recorded_at": "", "premium": float(previous_premium), "risk_score": None},
        )

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
        .mark_line(point=True, color="#0F766E", strokeWidth=2.5)
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
        .mark_line(point=True, color="#1D4ED8", strokeWidth=2.5)
        .encode(
            x=alt.X("Quote:N", sort=None, title=None),
            y=alt.Y("risk_score:Q", title="Risk score", scale=alt.Scale(domain=[0, 100])),
        )
    )
    chart = (
        alt.layer(premium, risk)
        .resolve_scale(y="independent")
        .properties(height=320)
        .configure_view(strokeWidth=0)
        .configure_axis(labelColor="#334155", titleColor="#0F172A", gridColor="#E2E8F0")
    )
    st.altair_chart(chart, width="stretch")
    st.caption("Teal is the bounded monthly premium. Blue is the behavioral risk score.")


if st.session_state.get("history_loaded_for") != st.session_state.policy_id:
    load_history(st.session_state.policy_id)

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

    reprice_col, refresh_col, reset_col = st.columns(3)
    with reprice_col:
        do_reprice = st.button("Re-underwrite", key="reprice", type="primary", width="stretch")
    with refresh_col:
        do_refresh = st.button("Refresh trend", key="refresh", type="primary", width="stretch")
    with reset_col:
        st.button(
            "Reset inputs",
            key="reset",
            type="primary",
            width="stretch",
            on_click=reset_inputs,
        )

if do_refresh:
    load_history(policy_id)

if do_reprice:
    payload = {
        "policy_id": policy_id,
        "hard_brakes_per_100mi": hard_brakes,
        "night_miles_pct": night_pct_ui / 100.0,
        "speed_violations": int(speed_violations),
        "total_miles": total_miles,
        "previous_premium": prev_premium,
        "iot_moisture": moisture_pct / 100.0,
        "weather_precip_mm": precip_mm,
        "weather_wind_mph": wind_mph,
        "bbox": bbox,
    }
    try:
        response = requests.post(f"{API_URL}/api/v1/reprice", json=payload, timeout=30)
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
            st.session_state.quote_error = f"The engine rejected the quote: {detail}"
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
        premium_col, risk_col, status_col = st.columns(3)
        premium_col.metric(
            "Monthly premium",
            f"${data['final_bounded_premium']:.2f}",
            delta=f"{data['final_bounded_premium'] - anchor:.2f}",
        )
        risk_col.metric("Risk score", f"{data['risk_score']:.1f}")
        status_col.metric("Rate cap", "Applied" if data["rate_clamped"] else "Clear")
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
            st.info(
                f"NDVI {satellite['ndvi_index']} · NDWI {satellite['ndwi_index']} · "
                f"{satellite['satellite_source']}"
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
