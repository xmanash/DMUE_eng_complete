from typing import Any, Dict, Optional

from app.core.config import settings

ROUTES: Dict[str, Dict[str, Any]] = {
    "dmue-rules-v1": {
        "label": "Rules",
        "description": "Telemetry math only. Lowest cost. No weather, moisture, or satellite.",
        "use_environment": False,
        "use_satellite": False,
        "cost_usd": 0.0002,
    },
    "dmue-full-v1": {
        "label": "Full",
        "description": "Telemetry, environment signals, and satellite when a bbox is present.",
        "use_environment": True,
        "use_satellite": True,
        "cost_usd": 0.0010,
    },
    "dmue-explain-v1": {
        "label": "Explain",
        "description": "Full scoring with the same factors and a higher reserved explanation cost.",
        "use_environment": True,
        "use_satellite": True,
        "cost_usd": 0.0015,
    },
}

SATELLITE_SURCHARGE_USD = 0.0005


def catalog() -> list[dict]:
    return [{"id": route_id, **spec} for route_id, spec in ROUTES.items()]


def resolve_route(name: Optional[str] = None) -> Dict[str, Any]:
    route_id = (name or settings.DEFAULT_MODEL_ROUTE or "dmue-full-v1").strip()
    spec = ROUTES.get(route_id)
    if spec is None:
        raise ValueError(f"Unknown model_route: {route_id}")
    return {"id": route_id, **spec}


def quote_cost_usd(route: Dict[str, Any], used_satellite: bool) -> float:
    amount = float(route["cost_usd"])
    if used_satellite:
        amount += SATELLITE_SURCHARGE_USD
    return round(amount, 6)
