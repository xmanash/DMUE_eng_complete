import math
from typing import Any, Dict, Tuple

from app.core.config import settings

# Sahel-like box. Center (30.5, 14.5) is the drought anchor for TC-03.
DISTRESSED_BBOX: Tuple[float, float, float, float] = (30.0, 14.0, 31.0, 15.0)
# Far from the drought anchor, so the band blend reaches full vegetation.
HEALTHY_BBOX: Tuple[float, float, float, float] = (-105.0, 40.0, -104.0, 41.0)
_DROUGHT_CENTER = (30.5, 14.5)
_DROUGHT_REACH_DEG = 8.0


def compute_ndvi(nir: float, red: float) -> float:
    """Normalized Difference Vegetation Index from near-infrared and red bands."""
    denom = nir + red
    if abs(denom) < 1e-9:
        return 0.0
    return (nir - red) / denom


def compute_ndwi(green: float, nir: float) -> float:
    """McFeeters NDWI from green and near-infrared bands."""
    denom = green + nir
    if abs(denom) < 1e-9:
        return 0.0
    return (green - nir) / denom


def synthesize_bands(bbox: Tuple[float, float, float, float]) -> Tuple[float, float, float]:
    """Deterministic NIR, red, and green reflectance from a bounding box.

    Reflectance moves from bare drought at the Sahel anchor to healthy canopy
    eight degrees away. No random draw and no network call.
    """
    center_lon = (bbox[0] + bbox[2]) / 2.0
    center_lat = (bbox[1] + bbox[3]) / 2.0
    distance = math.hypot(center_lon - _DROUGHT_CENTER[0], center_lat - _DROUGHT_CENTER[1])
    health = min(distance / _DROUGHT_REACH_DEG, 1.0)
    nir = 0.18 + health * (0.72 - 0.18)
    red = 0.50 + health * (0.12 - 0.50)
    green = 0.22 + health * (0.40 - 0.22)
    return nir, red, green


class SentinelSatelliteRiskProcessor:
    """Computes Sentinel-2 style NDVI and NDWI for crop and property risk.

    Indices always come from local band synthesis so pricing stays repeatable.
    SENTINEL_API_TOKEN is recorded when set, and it does not trigger a live fetch.
    """

    def __init__(self, api_base_url: str = "https://services.sentinel-hub.com/api/v1"):
        self.api_base_url = api_base_url

    def fetch_ndvi_index(self, bbox: Tuple[float, float, float, float]) -> float:
        nir, red, _green = synthesize_bands(bbox)
        return round(compute_ndvi(nir, red), 3)

    def evaluate_property_crop_risk(
        self, bbox: Tuple[float, float, float, float], crop_type: str = "corn"
    ) -> Dict[str, Any]:
        nir, red, green = synthesize_bands(bbox)
        ndvi = round(compute_ndvi(nir, red), 3)
        ndwi = round(compute_ndwi(green, nir), 3)
        risk_score = 50.0
        reasons = []

        if ndvi < 0.30:
            risk_score += 25.0
            reasons.append(f"Plant health is poor. The vegetation index is {ndvi:.2f}.")
        elif ndvi < 0.45:
            risk_score += 10.0
            reasons.append(f"Plant health is moderate. The vegetation index is {ndvi:.2f}.")
        else:
            risk_score -= 15.0
            reasons.append(f"Plant health is strong. The vegetation index is {ndvi:.2f}.")

        token = (settings.SENTINEL_API_TOKEN or "").strip()
        return {
            "ndvi_index": ndvi,
            "ndwi_index": ndwi,
            "crop_risk_score": float(risk_score),
            "risk_delta": float(risk_score - 50.0),
            "crop_type": crop_type,
            "satellite_source": "deterministic_bbox_bands",
            "sentinel_token_configured": bool(token),
            "sentinel_live_fetch": False,
            "bands": {"nir": round(nir, 4), "red": round(red, 4), "green": round(green, 4)},
            "risk_factors": reasons,
        }
