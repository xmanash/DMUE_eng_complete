# Dynamic Micro-Underwriting Engine (DMUE)

## Executive summary

Traditional actuarial underwriting prices policies from static demographic proxies such as age, gender, credit score, and ZIP code, usually once a year. That lags real behavior and makes the price hard to explain.

DMUE prices from behavior instead. It accepts telematics, home moisture, weather, and a satellite bounding box, scores risk from 0 to 100, and reprices the monthly premium inside state filing limits. Each quote records why the price moved, checks the explanation for prohibited factors and plain language, and stores the event for later recall.

The product spec is [PRD.md](PRD.md). The request path is [Architecture.md](Architecture.md). Month-over-month premiums stay inside **+25% / −20%** of the prior premium.

## Run from GitHub (external URL)

Open this repo in GitHub Codespaces. After the container starts, GitHub forwards HTTPS URLs for the API (`8000`) and the console (`8501`). The console tab usually opens on its own.

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/xmanash/DMUE_eng_complete?quickstart=1)

Or: **Code → Codespaces → Create codespace on main**. Wait for `postStart` to finish, then open the **Ports** panel and the `8501` URL (set visibility to **Public** if the page asks you to sign in).

The dashboard still calls the API on `http://127.0.0.1:8000` inside the codespace. You do not paste a Hub token for a basic demo. This is a forwarded demo URL, not a production bind. See [DEPLOY.md](DEPLOY.md).

## What you can run

- HTTP API on port **8000**
- Streamlit workbench on port **8501**
- MCP stdio server (`python -m app.mcp_server.server`)
- Evaluation harness (`python -m app.harness`)
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
python -m app.harness
```

The dashboard calls `DMUE_API_URL`, which defaults to `http://127.0.0.1:8000`. Start the API before the workbench.

A guided customer walkthrough is in [DEMO.md](DEMO.md). Seeded payloads are in `fixtures/demo/`. A public URL or carrier bind needs [DEPLOY.md](DEPLOY.md) (API key, TLS, loopback ports).

## Workbench

`streamlit run app/ui/dashboard.py` opens the underwriter screen on port **8501**.

The console is a dark operations layout. The sidebar is the control plane: API target, `DMUE_ENV` chip, model route, and process-level quote cost.

| Button | Color | Action |
| --- | --- | --- |
| Re-underwrite | Teal | Prices the current form on the selected model route |
| Refresh trend | Blue | Reloads quote history for the policy id |
| Reset inputs | Slate | Restores the sample policy `POL-98234` |

The Quote tab shows premium, risk, filing cap, per-quote cost, factors, and the premium/risk trend. Check **Include home line** or **Include commercial line** to price an account; the account premium is the sum of bounded line premiums. The **Desk** tab holds the appetite recommendation (accept/refer/decline), human decision with override, referrals, and the packet download. The **Intake** tab creates ACORD-like submissions — missing documents block bind, not quoting. The Operations tab lists routes, unit costs, traces, and the in-process cost ledger. The Controls tab runs ingest and a prohibited-key rejection. Cost and traces are **this API process only** — run one uvicorn worker in a demo.

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

The API process uses `--workers ${UVICORN_WORKERS:-1}` so the Operations tab matches the quote you just ran. Do not raise workers or `--scale dmue-api` for a demo. Rate limit, cache, ingest jobs, cost, and traces are per process. MCP is opt-in: `docker compose --profile mcp up`. Do not scale `dmue-mcp`.

Single-node production (loopback ports, API key required):

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build -d
```

Put TLS in front. See [DEPLOY.md](DEPLOY.md) and [deploy/Caddyfile](deploy/Caddyfile).

## Controls

Quotes run three in-process layers, then a local audit hook.

| Layer | What it does |
| --- | --- |
| Input | Rejects prohibited keys and impossible sensor values. Flags a hard-brake rate above 20 per 100 miles. |
| Output | Stores a quote only when leaks are 0, factor coverage is at least 0.50, reading ease is at least 60, and grade is at most 8. |
| Policy | Clamps the premium at +25% / −20% of the prior premium. |

The API and MCP server log one JSON line per quote on logger `dmue.quote` and append the same event to `./data/audit/quotes.jsonl` (`AUDIT_LOG_PATH`). A hook that raises blocks the save. `python -m app.harness` prints a JSON report for the PRD cases and exits 1 if a case fails.

## Quote endpoints

`POST /api/v1/reprice` accepts one object and prices it in the request. `POST /api/v1/ingest` accepts a JSON list and returns **202** `{job_id, status: queued}`. Poll `GET /api/v1/jobs/{job_id}` for `done` or `failed`. A full queue returns **503**. `/api/v1/*` returns **429** when the token bucket is empty (`RATE_LIMIT_PER_MINUTE`, default 60). Health `GET /` is not limited.

Required fields are `policy_id` and `previous_premium`. Optional fields are telematics, `iot_moisture`, `weather_precip_mm`, `weather_wind_mph`, `bbox`, `model_route` (`dmue-rules-v1`, `dmue-full-v1`, `dmue-explain-v1`), and `lines` (`auto`/`home`/`commercial` on one policy). Every quote carries `uw_recommendation`. `POST /api/v1/uw/decision`, `GET /api/v1/uw/referrals`, `GET /api/v1/uw/packet/{policy_id}`, and `POST`/`GET /api/v1/submissions` run the desk and intake. Thresholds are `UW_REFER_SCORE` (80) and `UW_DECLINE_SCORE` (95). `GET /api/v1/ops/status`, `GET /api/v1/ops/costs`, and `GET /api/v1/ops/traces` report environment, routes, process cost, and recent traces. When `DMUE_API_KEY` is set, every `/api/v1/*` path (including ops) needs `X-API-Key` or `Authorization: Bearer`. Staging and production refuse to start without a key. `GET /` stays open for health checks. `/api/v1/*` is rate limited.

A hard-brake rate above 20 per 100 miles is recorded as a sensor fault and is not scored. Keys such as `gender`, `race`, `zip_code`, and `credit_score` are rejected.

`GET /api/v1/policy/{policy_id}/context` returns prior quotes for that policy. Repeat reads within `CACHE_TTL_SECONDS` (default 30) are served from the process cache.

## Configuration

Optional environment variables, also read from `.env`:

Copy [env.example](env.example) to `.env`. Set `DMUE_ENV` to `local`, `staging`, or `production`. Do not point staging or production at a local Chroma directory.

Every quote writes a local trace to `TRACE_LOG_PATH` (free, no account). `GET /api/v1/ops/traces` and the Operations tab list recent runs. To also send traces to LangSmith’s free developer tier, set `LANGSMITH_TRACING=true` and `LANGSMITH_API_KEY` from https://smith.langchain.com. Local traces still write when LangSmith is on.

GitHub Actions (`.github/workflows/ci.yml`) sets `DMUE_ENV=ci` and runs `pytest` plus `python -m app.harness` on each push and pull request to `main`.

| Variable | Default | Purpose |
| --- | --- | --- |
| `DMUE_ENV` | `local` | Environment name on ops status and the console chip |
| `DEFAULT_MODEL_ROUTE` | `dmue-full-v1` | Route used when the payload omits `model_route` |
| `BASE_MONTHLY_AUTO_PREMIUM` | `120` | Base used in the multiplier |
| `MAX_PREMIUM_INCREASE_PCT` | `0.25` | Month-over-month cap |
| `MAX_PREMIUM_DECREASE_PCT` | `0.20` | Month-over-month floor |
| `CHROMA_PERSIST_DIR` | `./data/chroma_db` | Chroma path |
| `AUDIT_LOG_PATH` | `./data/audit/quotes.jsonl` | Quote audit JSONL |
| `RATE_LIMIT_PER_MINUTE` | `60` | API token bucket per client IP |
| `INGEST_QUEUE_MAX` | `100` | In-process ingest queue cap |
| `CACHE_TTL_SECONDS` | `30` | Context and satellite cache TTL |
| `CIRCUIT_FAILURES` | `3` | Satellite errors before the breaker opens |
| `CIRCUIT_COOLDOWN_SECONDS` | `30` | Seconds to skip satellite while open |
| `TRACE_LOG_PATH` | `./data/observability/traces.jsonl` | Local quote traces (always on, free) |
| `LANGSMITH_TRACING` | `false` | Set true to export traces to LangSmith |
| `LANGSMITH_API_KEY` | empty | LangSmith developer-tier key |
| `LANGSMITH_PROJECT` | `dmue` | LangSmith project name |
| `DMUE_API_URL` | `http://127.0.0.1:8000` | Dashboard target |
| `DMUE_API_KEY` | empty | Bearer / `X-API-Key` for `/api/v1/*`. Required in staging and production |
| `AUTH_REQUIRED` | `false` | Force API-key checks even in `local` |
| `CORS_ALLOW_ORIGINS` | empty | Comma-separated browser origins |
| `SENTINEL_LIVE_FETCH` | `false` | Allow live Sentinel Hub when credentials are set |
| `SENTINEL_CLIENT_ID` | empty | Sentinel Hub OAuth client id |
| `SENTINEL_CLIENT_SECRET` | empty | Sentinel Hub OAuth client secret |
| `SENTINEL_API_TOKEN` | empty | Alias for the client secret when `SENTINEL_CLIENT_ID` is set |

Vegetation indices default to local bands. Live Sentinel-2 statistics run only when live is requested and credentials are present. A Hub failure falls back to local NDVI/NDWI. The drought fixture box is `(30.0, 14.0, 31.0, 15.0)`.
