# Single-node deployment

This stack is one VM: FastAPI, Streamlit, and a Chroma directory. Rate limit, cost, traces, and ingest jobs are **per process**. Do not scale `dmue-api` until those stores are shared.

Chroma stays a local directory (`CHROMA_PERSIST_DIR`). That is enough for a demo VM. High availability needs a hosted store; that is a later change. The image runs as uid `10001`. The host `./data` bind mount must be writable by that user.

## Before you bind a public URL

1. Copy `env.example` to `.env`. Set `DMUE_ENV=production` and a long `DMUE_API_KEY`. Never commit `.env`.
2. Set the same `DMUE_API_KEY` for the dashboard so the console can call the API.
3. Leave `LANGSMITH_API_KEY` and `SENTINEL_API_TOKEN` empty unless you intend to use them. Sentinel still does not fetch imagery.
4. Put TLS in front of the process. Do not publish uvicorn or Streamlit on `0.0.0.0`.

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build -d
```

Production overlay:

- `DMUE_ENV=production` (API key required at startup)
- Ports bound to `127.0.0.1` only
- `env_file: .env`
- API healthcheck

Point Caddy or nginx at loopback. Example: [deploy/Caddyfile](deploy/Caddyfile).

```text
Internet --TLS--> Caddy :443 --> 127.0.0.1:8501 (console)
                              --> 127.0.0.1:8000 (API / and /api)
```

Callers send `X-API-Key` or `Authorization: Bearer <key>` on every `/api/v1/*` path, including ops. `GET /` stays open for the healthcheck.

## CORS

Set `CORS_ALLOW_ORIGINS` to the dashboard origin only, for example `https://dmue.example.com`. Streamlit talks to the API from the server, so a same-host reverse proxy often needs no extra origins.

## Secrets

Compose interpolates the project `.env` and, in the prod overlay, injects it with `env_file`. Do not bake keys into the image. Rotate `DMUE_API_KEY` by changing `.env` and recreating the containers.

## MCP

Leave `dmue-mcp` off a customer host unless they asked for a local stdio tool. It has no network auth.

## Checklist

- [ ] `DMUE_API_KEY` set; production process refuses to start without it
- [ ] TLS at the edge; Compose ports not on the public interface
- [ ] Ops traces not reachable without the key
- [ ] Data volume backed up if quotes must survive the VM
- [ ] `pytest` and `python -m app.harness` green on the image you ship
