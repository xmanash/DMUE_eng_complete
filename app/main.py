from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, model_validator

from app.core.config import PROHIBITED_FACTOR_KEYS, settings
from app.core.memory import PolicyMemoryManager
from app.core.quote import quote_policy

app = FastAPI(title="Dynamic Micro-Underwriting Engine API", version=settings.VERSION)

_memory: Optional[PolicyMemoryManager] = None


def get_memory() -> PolicyMemoryManager:
    global _memory
    if _memory is None:
        _memory = PolicyMemoryManager()
    return _memory


class TelemetryIngestPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    policy_id: str
    hard_brakes_per_100mi: float = 0
    night_miles_pct: float = 0
    speed_violations: int = 0
    total_miles: float = 0
    previous_premium: float
    iot_moisture: Optional[float] = None
    weather_precip_mm: Optional[float] = None
    weather_wind_mph: Optional[float] = None
    bbox: Optional[List[float]] = None

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
        return quote_policy(payload, get_memory())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/")
def read_root():
    return {"status": "online", "system": "Dynamic Micro-Underwriting Engine (DMUE)"}


@app.post("/api/v1/reprice")
def reprice_policy(payload: TelemetryIngestPayload):
    return _quote_or_http(_payload_dict(payload))


@app.post("/api/v1/ingest")
def ingest_events(events: List[TelemetryIngestPayload]):
    if not events:
        raise HTTPException(status_code=422, detail="At least one telemetry event is required")
    return {
        "count": len(events),
        "results": [_quote_or_http(_payload_dict(event)) for event in events],
    }


@app.get("/api/v1/policy/{policy_id}/context")
def policy_context(policy_id: str, limit: int = 3):
    try:
        context = get_memory().get_policy_context(policy_id, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"policy_id": policy_id, **context}
