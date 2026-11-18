import asyncio
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, model_validator
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.auth import (
    OPEN_PATHS,
    auth_required,
    configured_api_key,
    cors_origins,
    extract_api_key,
    key_matches,
)
from app.core.cache import context_cache
from app.core.config import PROHIBITED_FACTOR_KEYS, settings
from app.core.cost import CostHook, cost_tracker
from app.core.governance import AuditLogHook, configure_logging
from app.core.observability import observability_status, trace_store
from app.core.routing import catalog
from app.core.satellite_processor import sentinel_status
from app.core.jobs import JobManager, JobQueueFull
from app.core.memory import PolicyMemoryManager
from app.core.quote import quote_policy
from app.core.ratelimit import limiter
from app.core.submissions import missing_documents, submission_store
from app.core.underwriting import uw_store

configure_logging()

_memory: Optional[PolicyMemoryManager] = None
_hooks = [AuditLogHook(), CostHook()]


def get_memory() -> PolicyMemoryManager:
    global _memory
    if _memory is None:
        _memory = PolicyMemoryManager()
    return _memory


def _run_quote(payload: Dict[str, Any]) -> Dict[str, Any]:
    result = quote_policy(payload, get_memory(), hooks=_hooks)
    try:
        uw_store.record_quote(result)
    except Exception:
        pass
    return result


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith("/api/v1/"):
            host = request.client.host if request.client else "unknown"
            if not limiter.allow(host):
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Rate limit exceeded"},
                    headers={"Retry-After": "60"},
                )
        return await call_next(request)


class ApiKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in OPEN_PATHS or not path.startswith("/api/v1/"):
            return await call_next(request)
        expected = configured_api_key()
        if not expected:
            if auth_required():
                return JSONResponse(
                    status_code=503,
                    content={"detail": "DMUE_API_KEY is required in this environment"},
                )
            return await call_next(request)
        provided = extract_api_key(
            request.headers.get("authorization"),
            request.headers.get("x-api-key"),
        )
        if not key_matches(provided):
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing API key"},
                headers={"WWW-Authenticate": "Bearer"},
            )
        return await call_next(request)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if auth_required() and not configured_api_key():
        raise RuntimeError(
            "DMUE_API_KEY is required when AUTH_REQUIRED is true "
            "or DMUE_ENV is staging or production"
        )
    manager = JobManager()
    app.state.jobs = manager
    worker = asyncio.create_task(manager.run_worker(_run_quote))
    try:
        yield
    finally:
        manager.stop()
        worker.cancel()
        try:
            await worker
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="Dynamic Micro-Underwriting Engine API",
    version=settings.VERSION,
    lifespan=lifespan,
)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(ApiKeyMiddleware)
_origins = cors_origins()
if _origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-API-Key"],
    )


class TelemetryIngestPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    policy_id: str
    hard_brakes_per_100mi: float = 0
    night_miles_pct: float = 0
    speed_violations: int = 0
    total_miles: float = 0
    previous_premium: Optional[float] = None
    iot_moisture: Optional[float] = None
    weather_precip_mm: Optional[float] = None
    weather_wind_mph: Optional[float] = None
    bbox: Optional[List[float]] = None
    model_route: Optional[str] = None
    sentinel_live: Optional[bool] = None
    lines: Optional[Dict[str, Any]] = None

    @model_validator(mode="before")
    @classmethod
    def block_prohibited_factors(cls, data: Any) -> Any:
        if isinstance(data, dict):
            found = sorted(
                str(key)
                for key in data
                if str(key).lower() in PROHIBITED_FACTOR_KEYS
            )
            if found:
                raise ValueError(f"Prohibited factor present: {', '.join(found)}")
        return data


def _payload_dict(model: TelemetryIngestPayload) -> Dict[str, Any]:
    data = model.model_dump()
    if model.model_extra:
        data.update(model.model_extra)
    return data


def _quote_or_http(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return _run_quote(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/")
def read_root():
    return {
        "status": "online",
        "system": "Dynamic Micro-Underwriting Engine (DMUE)",
        "environment": settings.DMUE_ENV,
        "version": settings.VERSION,
    }


@app.get("/api/v1/ops/status")
def ops_status():
    return {
        "status": "online",
        "environment": settings.DMUE_ENV,
        "version": settings.VERSION,
        "default_model_route": settings.DEFAULT_MODEL_ROUTE,
        "routes": catalog(),
        "cost": cost_tracker.summary(),
        "observability": observability_status(),
        "traces": trace_store.list_recent(10),
        "sentinel": sentinel_status(),
    }


@app.get("/api/v1/ops/costs")
def ops_costs():
    return cost_tracker.summary()


@app.get("/api/v1/ops/traces")
def ops_traces(limit: int = 50):
    return {
        "observability": observability_status(),
        "traces": trace_store.list_recent(limit),
    }


@app.post("/api/v1/reprice")
def reprice_policy(payload: TelemetryIngestPayload):
    return _quote_or_http(_payload_dict(payload))


@app.post("/api/v1/ingest", status_code=202)
def ingest_events(events: List[TelemetryIngestPayload], request: Request):
    if not events:
        raise HTTPException(status_code=422, detail="At least one telemetry event is required")
    try:
        job_id = request.app.state.jobs.enqueue([_payload_dict(event) for event in events])
    except JobQueueFull as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"job_id": job_id, "status": "queued"}


@app.get("/api/v1/jobs/{job_id}")
def job_status(job_id: str, request: Request):
    job = request.app.state.jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job_id")
    return job


class UWDecisionPayload(BaseModel):
    policy_id: str
    quote_trace_id: str = ""
    action: str
    underwriter: str = ""
    note: str = ""
    submission_id: str = ""


class UWNotePayload(BaseModel):
    policy_id: str
    quote_trace_id: str = ""
    underwriter: str = ""
    note: str


@app.post("/api/v1/uw/decision")
def uw_decision(payload: UWDecisionPayload):
    action = payload.action.strip().lower()
    if action not in {"accept", "refer", "decline"}:
        raise HTTPException(status_code=422, detail="action must be accept, refer, or decline")
    submission = None
    if payload.submission_id:
        submission = submission_store.get(payload.submission_id)
        if submission is None:
            raise HTTPException(status_code=404, detail="Unknown submission_id")
        if action == "accept":
            missing = missing_documents(submission)
            if missing:
                raise HTTPException(
                    status_code=422,
                    detail=f"documents_incomplete: {', '.join(missing)}",
                )
    latest = uw_store.latest_quote(payload.policy_id)
    recommendation = ""
    if latest and (
        not payload.quote_trace_id
        or latest.get("quote_trace_id") == payload.quote_trace_id
    ):
        recommendation = str(latest.get("uw_recommendation") or "")
    try:
        entry = uw_store.record_decision(
            policy_id=payload.policy_id,
            quote_trace_id=payload.quote_trace_id,
            action=action,
            underwriter=payload.underwriter,
            note=payload.note,
            recommendation=recommendation,
            submission_id=payload.submission_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if submission is not None:
        status = {"accept": "bound", "refer": "referred", "decline": "declined"}[action]
        submission_store.update_status(payload.submission_id, status)
    return entry


@app.post("/api/v1/uw/notes")
def uw_note(payload: UWNotePayload):
    try:
        return uw_store.record_note(
            policy_id=payload.policy_id,
            quote_trace_id=payload.quote_trace_id,
            underwriter=payload.underwriter,
            note=payload.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/v1/uw/referrals")
def uw_referrals():
    return {"referrals": uw_store.referrals()}


@app.get("/api/v1/uw/packet/{policy_id}")
def uw_packet(policy_id: str):
    return uw_store.packet(policy_id)


@app.post("/api/v1/submissions")
def create_submission(payload: Dict[str, Any]):
    try:
        return submission_store.create(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/v1/submissions/{submission_id}")
def get_submission(submission_id: str):
    submission = submission_store.get(submission_id)
    if submission is None:
        raise HTTPException(status_code=404, detail="Unknown submission_id")
    return submission


@app.post("/api/v1/submissions/{submission_id}/quote")
def quote_submission(submission_id: str):
    submission = submission_store.get(submission_id)
    if submission is None:
        raise HTTPException(status_code=404, detail="Unknown submission_id")
    lines = submission.get("lines")
    if isinstance(lines, dict) and lines:
        payload: Dict[str, Any] = {
            "policy_id": submission["policy_id"],
            "lines": lines,
        }
    elif isinstance(lines, dict):
        payload = {"policy_id": submission["policy_id"], **lines}
    else:
        raise HTTPException(status_code=422, detail="Submission has no lines to quote")
    if submission.get("model_route"):
        payload["model_route"] = submission["model_route"]
    result = _quote_or_http(payload)
    recommendation = result.get("uw_recommendation")
    status = {"refer": "referred", "decline": "declined"}.get(
        recommendation, "quoted"
    )
    updated = submission_store.update_status(submission_id, status)
    return {"submission": updated, "quote": result}


@app.get("/api/v1/policy/{policy_id}/context")
def policy_context(policy_id: str, limit: int = 3):
    key = (policy_id, int(limit))
    cached = context_cache.get(key)
    if cached is not None:
        return {"policy_id": policy_id, "cache_hit": True, **cached}
    try:
        context = get_memory().get_policy_context(policy_id, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    context_cache.set(key, context)
    return {"policy_id": policy_id, "cache_hit": False, **context}
