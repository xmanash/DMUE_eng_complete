#!/usr/bin/env bash
# Start API + console inside a GitHub Codespace so forwarded HTTPS URLs work.
set -euo pipefail
cd "$(dirname "$0")/.."

export DMUE_ENV="${DMUE_ENV:-demo}"
export DMUE_API_URL="${DMUE_API_URL:-http://127.0.0.1:8000}"

if ! curl -sf "http://127.0.0.1:8000/" >/dev/null 2>&1; then
  nohup python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 \
    >> /tmp/dmue-api.log 2>&1 &
fi

if ! curl -sf "http://127.0.0.1:8501/_stcore/health" >/dev/null 2>&1 \
  && ! curl -sf "http://127.0.0.1:8501/" >/dev/null 2>&1; then
  nohup python -m streamlit run app/ui/dashboard.py \
    --server.port 8501 \
    --server.address 0.0.0.0 \
    --server.headless true \
    --server.enableCORS false \
    --server.enableXsrfProtection false \
    >> /tmp/dmue-ui.log 2>&1 &
fi
