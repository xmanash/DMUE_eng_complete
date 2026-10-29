# Dynamic Micro-Underwriting Engine (DMUE)

DMUE scores driving, home moisture, weather, and vegetation health, then bounds the monthly premium at **+25% / −20%** versus the prior premium. The product spec is [PRD.md](PRD.md). The request path is [Architecture.md](Architecture.md).

## What you can run

- HTTP API on port **8000**
- Streamlit workbench on port **8501**
- MCP stdio server (`python -m app.mcp_server.server`)
- `pytest tests/`

## Local setup

### Windows

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### macOS or Linux

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### API, dashboard, and tests

```bash
uvicorn app.main:app --reload --port 8000
```

In a second terminal, with the same virtualenv active:

```bash
streamlit run app/ui/dashboard.py
pytest tests/
```

The dashboard calls `DMUE_API_URL`, which defaults to `http://127.0.0.1:8000`. Start the API before the workbench.

## Workbench

`streamlit run app/ui/dashboard.py` opens the underwriter screen on port **8501**.

The left side is the telemetry form. Three actions sit under it:

| Button | Color | Action |
| --- | --- | --- |
| Re-underwrite | Teal | Prices the current form and stores the quote |
| Refresh trend | Blue | Reloads quote history for the policy id |
| Reset inputs | Amber | Restores the sample policy `POL-98234` |

The right side shows the bounded premium, risk score, filing-cap status, factor lines, and policyholder actions. Below both columns, the trend chart plots stored quotes for that policy. Teal is the bounded premium and blue is the risk score (0–100). Each new quote is timestamped, so later quotes sit to the right. The first scored quote is drawn from the prior premium so the direction of the change is visible. History comes from `GET /api/v1/policy/{policy_id}/context`.

MCP, if you want to drive the tools from stdin:

```bash
python -m app.mcp_server.server
```

Send one JSON-RPC object per line. `tools/call` with `reprice_policy_micro_underwrite` returns the premium payload. `get_policy_context` reads history for a `policy_id`.

## Docker

From the repository root:

```bash
docker-compose up --build
```

- API: http://localhost:8000
- Dashboard: http://localhost:8501

The dashboard service is pointed at `http://dmue-api:8000`. Quote history for the API container is stored under `./data` (`CHROMA_PERSIST_DIR=/app/data/chroma_db`).

## Quote endpoints

`POST /api/v1/reprice` accepts one object. `POST /api/v1/ingest` accepts a JSON list. Required fields are `policy_id` and `previous_premium`. Optional fields are telematics, `iot_moisture`, `weather_precip_mm`, `weather_wind_mph`, and `bbox` as `[min_lon, min_lat, max_lon, max_lat]`.

A hard-brake rate above 20 per 100 miles is recorded as a sensor fault and is not scored. Keys such as `gender`, `race`, `zip_code`, and `credit_score` are rejected.

`GET /api/v1/policy/{policy_id}/context` returns prior quotes for that policy.

## Configuration

Optional environment variables, also read from `.env`:

| Variable | Default | Purpose |
| --- | --- | --- |
| `BASE_MONTHLY_AUTO_PREMIUM` | `120` | Base used in the multiplier |
| `MAX_PREMIUM_INCREASE_PCT` | `0.25` | Month-over-month cap |
| `MAX_PREMIUM_DECREASE_PCT` | `0.20` | Month-over-month floor |
| `CHROMA_PERSIST_DIR` | `./data/chroma_db` | Chroma path |
| `DMUE_API_URL` | `http://127.0.0.1:8000` | Dashboard target |
| `SENTINEL_API_TOKEN` | empty | Recorded on the satellite result. Indices still come from local bands. |

Vegetation indices do not call the network. The drought fixture box is `(30.0, 14.0, 31.0, 15.0)`.
