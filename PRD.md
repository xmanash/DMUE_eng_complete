# Dynamic Micro-Underwriting Engine (DMUE)

Product requirement document  
Status: Approved / production specification  
Version: 1.0.0  
Target release: Open source AI underwriting core

## Repository layout

```text
dmue-engine/
├── PRD.md                            # Product requirement document
├── Architecture.md                   # System architecture
├── README.md                         # Setup for local and Docker runs
├── requirements.txt                  # Python dependencies
├── docker-compose.yml                # API, dashboard, and MCP services
├── Dockerfile                        # Multi-stage image
├── app/
│   ├── main.py                       # FastAPI gateway
│   ├── core/
│   │   ├── config.py                 # Rate caps, bounds, and signal weights
│   │   ├── quote.py                  # Shared underwriting pipeline
│   │   ├── risk_engine.py            # Behavioral risk math
│   │   ├── guardrails.py             # Anomaly filter, rate clamp, factor audit
│   │   ├── evals.py                  # Leakage, coverage, and reading-ease checks
│   │   ├── memory.py                 # ChromaDB episodic store
│   │   └── satellite_processor.py    # Deterministic NDVI / NDWI
│   ├── mcp_server/
│   │   └── server.py                 # MCP stdio server
│   └── ui/
│       └── dashboard.py              # Streamlit underwriter workbench
└── tests/
    └── test_risk_engine.py           # TC-01 through TC-05 and guardrail tests
```

## 1. Executive summary

Traditional actuarial underwriting prices policies from static demographic proxies such as age, gender, credit score, and ZIP code, usually once a year. That lags real behavior and makes the price hard to explain.

DMUE prices from behavior instead. It accepts telematics, home moisture, weather, and a satellite bounding box, scores risk from 0 to 100, and reprices the monthly premium inside state filing limits. Each quote records why the price moved, checks the explanation for prohibited factors and plain language, and stores the event for later recall.

## 2. Personas

- **Pricing actuary.** Sets the base monthly premium and the month-over-month filing caps: maximum increase **+25%**, maximum decrease **−20%**.
- **Compliance officer.** Reviews factor attributions and the eval block. Rate math and explanations reject gender, race, sex, ethnicity, ZIP code, and credit score.
- **Policyholder.** Sees the monthly risk score, the price drivers, and a short action for each driver.

## 3. Functional requirements

| ID | Area | Description | Priority | Where it lives |
| --- | --- | --- | --- | --- |
| FR-01 | Telemetry ingestion | Accept telematics, IoT moisture, weather, and a satellite bounding box, one event or a batch. | P0 | `POST /api/v1/reprice`, `POST /api/v1/ingest` |
| FR-02 | Deterministic risk math | Score behavior from 0 to 100 and apply the premium multiplier. | P0 | `app/core/risk_engine.py` |
| FR-03 | Regulatory guardrails | Keep the premium inside the prior premium's +25% / −20% band. | P0 | `ActuarialGuardrailEnforcer.enforce_rate_caps` |
| FR-04 | Vector episodic memory | Store each quote and recall it by `policy_id`. | P1 | `app/core/memory.py` |
| FR-05 | Agentic MCP interface | Expose repricing and recall as MCP tools over JSON-RPC 2.0. | P1 | `app/mcp_server/server.py` |
| FR-06 | Satellite processor | Compute NDVI and NDWI and add vegetation stress to the score. | P1 | `app/core/satellite_processor.py` |

Ingestion is an HTTP request. `POST /api/v1/reprice` takes one event. `POST /api/v1/ingest` takes a JSON list of events. There is no separate message broker.

### Ingest fields

| Field | Required | Meaning |
| --- | --- | --- |
| `policy_id` | yes | Policy identifier |
| `previous_premium` | yes | Last month's premium, must be greater than 0 |
| `hard_brakes_per_100mi` | no | Hard-brake events per 100 miles |
| `night_miles_pct` | no | Night miles as a fraction from 0 to 1 |
| `speed_violations` | no | Whole-number speeding count |
| `total_miles` | no | Miles in the period, must be 0 or greater |
| `iot_moisture` | no | Home moisture as a fraction from 0 to 1 |
| `weather_precip_mm` | no | Rainfall in millimeters, 0 or greater |
| `weather_wind_mph` | no | Wind speed in miles per hour, 0 or greater |
| `bbox` | no | `[min_lon, min_lat, max_lon, max_lat]` |

Prohibited keys are rejected before scoring: `gender`, `race`, `sex`, `ethnicity`, `zipcode`, `zip_code`, `credit_score`.

## 4. Guardrails

```text
Sensor / satellite signal
        |
        v
Guardrail 1: input anomaly filter
        |
        v
Behavioral risk math
        |
        v
Guardrail 2: actuarial rate clamp (+25% / -20%)
        |
        v
Guardrail 3: prohibited-factor audit
        |
        v
Eval checks, then final premium and memory write
```

1. **Input range and anomaly filter.** Non-finite numbers, negative miles, a night ratio outside 0–1, and a non-positive prior premium are rejected. Hard braking above **20 events per 100 miles** is treated as a hardware fault: the reading is dropped and replaced with a neutral 3.0 so it neither adds the frequent-braking load nor the smooth-braking credit. The response lists the fault in `anomalies`.
2. **Actuarial rate-cap clamp.** Month-over-month change cannot exceed **+25%** or **−20%** of `previous_premium`. A raw premium of $150 after a $100 prior becomes $125 with `rate_clamped: true`.
3. **Prohibited-factor isolation.** Those keys cannot be submitted. Generated text is scanned for gender, race, sex, ethnicity, zipcode, zip code, and credit score. A leak fails the quote before anything is stored.

## 5. Risk math

Auto score starts at 50 and is clipped to 0–100.

| Signal | Rule | Score change |
| --- | --- | --- |
| Hard brakes | greater than 5 per 100 miles | +15 |
| Hard brakes | less than 2 per 100 miles | −10 |
| Night miles | greater than 25% | +12 |
| Speeding | more than 2 violations | +20 |

Raw premium uses the base monthly premium (default **$120**):

```text
multiplier = 0.7 + (risk_score / 100) * 0.8
raw_premium = base_premium * multiplier
```

Optional signals add to the score only when they are present and above the configured threshold, then the premium is recomputed from the same multiplier:

| Signal | Threshold | Score change |
| --- | --- | --- |
| `iot_moisture` | 0.85 or higher | +8 |
| `weather_wind_mph` | 40 or higher | +8 |
| `weather_precip_mm` | 50 mm or higher | +6 |

Satellite stress is applied after those deltas. See section 6.

TC-01 inputs (6 hard brakes, 35% night miles, 3 speeding events) score **97** and a raw premium above $120. The raw premium equals `base * multiplier`.

## 6. Satellite indices

NDVI and NDWI are computed from reflectance, not from a random draw:

```text
NDVI = (NIR - Red) / (NIR + Red)
NDWI = (Green - NIR) / (Green + NIR)
```

Band values are a deterministic function of the bounding-box center. The drought anchor is longitude 30.5, latitude 14.5. The TC-03 distressed box is `(30.0, 14.0, 31.0, 15.0)`. At that box NDVI is below 0.30 and the crop risk score is the 50 baseline **plus 25**. A box far from the anchor, such as `(-105.0, 40.0, -104.0, 41.0)`, stays at or above 0.45 NDVI.

| NDVI | Score change | Policyholder line |
| --- | --- | --- |
| below 0.30 | +25 | Plant health is poor |
| below 0.45 | +10 | Plant health is moderate |
| 0.45 or higher | −15 | Plant health is strong |

`SENTINEL_API_TOKEN` is read from the environment when a deployment has one. This build still uses the local bands and sets `sentinel_live_fetch` to false. Pricing does not depend on a network call.

## 7. Memory

ChromaDB persists at `CHROMA_PERSIST_DIR` (default `./data/chroma_db`) in collection `policy_telemetry_history`. Embeddings are a local SHA-256 hash, so the store does not download an ONNX model.

Each write stores:

```json
{
  "document": "Policy POL-98234 scored risk 65.0 with premium $134.40. Key factors: ...",
  "metadata": {
    "policy_id": "POL-98234",
    "risk_score": 65.0,
    "premium": 134.40
  },
  "id": "POL-98234_<16 hex chars of sha256>"
}
```

The id includes a unique suffix so a second quote for the same policy does not collide.

- **Write.** Every successful reprice logs the summary, score, bounded premium, and factor text.
- **Read.** `get_policy_context(policy_id)` runs a semantic query restricted with `where policy_id`. The HTTP form is `GET /api/v1/policy/{policy_id}/context`. The MCP tool name is `get_policy_context`.

## 8. AI evaluation

Every quote evaluates the policyholder paragraph:

1. **Prohibited-term leaks** must be **0**. Terms: gender, race, sex, ethnicity, zipcode, zip code, credit score.
2. **Factor coverage** must be **at least 0.50**. Coverage is the share of math-engine drivers whose text appears in the explanation.
3. **Flesch-Kincaid reading ease** must be **at least 60**, and the grade level must be **at most 8**.

Scores are returned on the quote as `evals`. Reason lines are short sentences so the standard TC-01 text passes.

## 9. Test matrix

| ID | Scenario | Expectation |
| --- | --- | --- |
| TC-01 | Hard brakes 6, night miles 0.35, speeding 3, base $120 | Score above 50, raw premium above $120, raw premium equals the multiplier formula |
| TC-02 | Raw premium $150, previous $100 | Final premium $125 and `clamped` true |
| TC-03 | Distressed bounding box | `ndvi_index` below 0.30, risk score +25, `ndwi_index` present |
| TC-04 | Write and query `POL-98234` | Recall metadata `policy_id` matches; another policy id returns nothing |
| TC-05 | MCP `tools/call` `reprice_policy_micro_underwrite` | JSON-RPC 2.0 result whose text payload includes `final_bounded_premium` |

`tests/test_risk_engine.py` also covers the hard-brake fault, impossible night ratio, prohibited key and prohibited wording, and the three eval thresholds.

## 10. Development and quickstart

Local execution:

```bash
pip install -r requirements.txt

# API
uvicorn app.main:app --reload --port 8000

# Underwriter dashboard (second terminal)
streamlit run app/ui/dashboard.py

# Tests
pytest tests/
```

On Windows, activate a virtualenv with `venv\Scripts\activate`. On macOS or Linux, use `source venv/bin/activate`.

Containerized execution:

```bash
docker-compose up --build
```

- API: http://localhost:8000
- Dashboard: http://localhost:8501
- MCP service: `python -m app.mcp_server.server` on stdin/stdout inside the `dmue-mcp` container

The dashboard container calls the API at `http://dmue-api:8000`. A local dashboard uses `DMUE_API_URL`, defaulting to `http://127.0.0.1:8000`.

See [README.md](README.md) for the full setup and [Architecture.md](Architecture.md) for the request path.
