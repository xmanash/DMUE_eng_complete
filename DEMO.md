# Guided demo (30–40 minutes)

DMUE is an underwriting **core**, not a filed rating product. Vegetation indices default to local bands. Live Sentinel Hub is optional. Scores are deterministic telematics math plus those indices.

Use **one API worker** so the Operations tab matches the quote you just ran.

## Start

```bash
copy env.example .env
docker compose up --build
```

Or locally: API first (`uvicorn app.main:app --reload --port 8000`), then `streamlit run app/ui/dashboard.py`.

- API: http://127.0.0.1:8000
- Console: http://127.0.0.1:8501

Do not publish these ports past the laptop or VPN.

## Script

1. Open the console on **POL-98234**. Point at the banner: behavior scoring, +25% / −20% filing band, simulated satellite. In the sidebar, **Load case** walks 15 synthetic policies (green accept, yellow refer, red decline, orange clamp, purple sensor). **Price all** fills the colored book table.
2. **Re-underwrite** on Full. Show premium, risk, factors, eval caption, and `decisions`.
3. Switch the sidebar to **Rules** and price again (no weather or satellite).
4. Switch back to **Full**, enable the Sahel box, price again. NDVI is under 0.30.
5. Push hard brakes past **20**. Sensor fault, not a risk factor.
6. Drop prior premium toward **$80** and price. Filing cap applies.
7. Open **Controls**. Ingest the current form; wait for `done`. Then **Try prohibited key** and show the human 422.
8. Open **Operations**. Cost ledger and traces are this process only.
9. Open **Desk**. POL-98234 scores high, so appetite recommends **decline** (score at or above 95). Price the good-driver fixture for **accept**, or the night/speed payload for **refer** (80–94), then Accept with a note and show `override`. Download the packet JSON.
10. On **Quote**, check **Include home line** (and optionally commercial). Account premium is the sum of line premiums. Set commercial occupancy to `excluded` and reprice — appetite declines.
11. Open **Intake**. Leave loss runs unchecked, create a submission (`incomplete`), quote it (allowed), then in Desk try Accept — bind is blocked with `documents_incomplete`. This is a simulated appetite, not AIG production.

## Fixtures (curl)

If `DMUE_API_KEY` is set, add `-H "X-API-Key: $DMUE_API_KEY"`.

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/reprice -H "content-type: application/json" -d @fixtures/demo/good_driver.json
curl -s -X POST http://127.0.0.1:8000/api/v1/reprice -H "content-type: application/json" -d @fixtures/demo/night_speed_spike.json
curl -s -X POST http://127.0.0.1:8000/api/v1/reprice -H "content-type: application/json" -d @fixtures/demo/sahel_bbox.json
curl -s -X POST http://127.0.0.1:8000/api/v1/reprice -H "content-type: application/json" -d @fixtures/demo/prohibited.json
```

The last call returns HTTP 422.

Proof off-stage: `pytest tests/` and `python -m app.harness`.

## Do not say

- That Sentinel Hub is always called. Live fetch is off unless credentials and the sidebar checkbox (or `SENTINEL_LIVE_FETCH`) are set. On failure the quote still uses local bands.
- That this is a production bind or a state-filed rate.
- That MCP Compose is a live carrier integration (stdio only).
