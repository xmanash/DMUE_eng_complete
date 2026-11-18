"""NDVI/NDWI: local bbox bands by default, optional Sentinel Hub statistics."""

import math
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

import httpx

from app.core.config import settings

# Sahel-like box. Center (30.5, 14.5) is the drought anchor for TC-03.
DISTRESSED_BBOX: Tuple[float, float, float, float] = (30.0, 14.0, 31.0, 15.0)
# Far from the drought anchor, so the band blend reaches full vegetation.
HEALTHY_BBOX: Tuple[float, float, float, float] = (-105.0, 40.0, -104.0, 41.0)
_DROUGHT_CENTER = (30.5, 14.5)
_DROUGHT_REACH_DEG = 8.0
_HTTP_TIMEOUT = 8.0
# Sentinel-2 L2A: B04 red, B08 NIR, B03 green. Same NDVI/NDWI formulas as local bands.
_EVALSCRIPT = """//VERSION=3
function setup() {
  return {
    input: [{ bands: ["B03", "B04", "B08", "dataMask"] }],
    output: [
      { id: "ndvi", bands: 1, sampleType: "FLOAT32" },
      { id: "ndwi", bands: 1, sampleType: "FLOAT32" },
      { id: "dataMask", bands: 1 }
    ]
  };
}
function evaluatePixel(s) {
  var ndviDen = s.B08 + s.B04;
  var ndwiDen = s.B03 + s.B08;
  var ndvi = ndviDen === 0 ? 0 : (s.B08 - s.B04) / ndviDen;
  var ndwi = ndwiDen === 0 ? 0 : (s.B03 - s.B08) / ndwiDen;
  return { ndvi: [ndvi], ndwi: [ndwi], dataMask: [s.dataMask] };
}
"""

_oauth_token: Optional[str] = None
_oauth_expires_at: float = 0.0


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


def sentinel_client_id() -> str:
    return (settings.SENTINEL_CLIENT_ID or "").strip()


def sentinel_client_secret() -> str:
    """OAuth secret, or SENTINEL_API_TOKEN as a drop-in alias."""
    return (settings.SENTINEL_CLIENT_SECRET or settings.SENTINEL_API_TOKEN or "").strip()


def sentinel_credentials_configured() -> bool:
    return bool(sentinel_client_id() and sentinel_client_secret())


def should_use_live_sentinel(payload_flag: Any = None) -> bool:
    """True only when requested (body or env) and OAuth credentials exist."""
    if payload_flag is True:
        requested = True
    elif payload_flag is False:
        requested = False
    else:
        requested = bool(settings.SENTINEL_LIVE_FETCH)
    return requested and sentinel_credentials_configured()


def sentinel_status() -> Dict[str, bool]:
    return {
        "live_enabled": bool(settings.SENTINEL_LIVE_FETCH),
        "credentials_configured": sentinel_credentials_configured(),
    }


def reset_oauth_cache() -> None:
    global _oauth_token, _oauth_expires_at
    _oauth_token = None
    _oauth_expires_at = 0.0


def _score_from_indices(ndvi: float, ndwi: float, crop_type: str) -> Dict[str, Any]:
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
    token = bool(sentinel_client_secret())
    return {
        "ndvi_index": ndvi,
        "ndwi_index": ndwi,
        "crop_risk_score": float(risk_score),
        "risk_delta": float(risk_score - 50.0),
        "crop_type": crop_type,
        "sentinel_token_configured": token,
        "risk_factors": reasons,
    }


def _local_result(
    bbox: Tuple[float, float, float, float],
    crop_type: str,
    *,
    source: str,
    live_fetch: bool,
    error: Optional[str] = None,
) -> Dict[str, Any]:
    nir, red, green = synthesize_bands(bbox)
    ndvi = round(compute_ndvi(nir, red), 3)
    ndwi = round(compute_ndwi(green, nir), 3)
    payload = _score_from_indices(ndvi, ndwi, crop_type)
    payload.update(
        {
            "satellite_source": source,
            "sentinel_live_fetch": live_fetch,
            "bands": {"nir": round(nir, 4), "red": round(red, 4), "green": round(green, 4)},
        }
    )
    if error:
        payload["sentinel_live_error"] = error
    return payload


def _mean_from_output(output: Any) -> Optional[float]:
    if not isinstance(output, dict):
        return None
    stats = output.get("stats") or output.get("statistics") or {}
    if isinstance(stats, dict) and stats.get("mean") is not None:
        sample = stats.get("sampleCount", stats.get("validCount", 1))
        if sample == 0:
            return None
        return float(stats["mean"])
    bands = output.get("bands")
    if isinstance(bands, dict):
        for band in bands.values():
            found = _mean_from_output(band)
            if found is not None:
                return found
    return None


def _parse_statistics(body: Dict[str, Any]) -> Tuple[float, float]:
    rows = body.get("data") if isinstance(body, dict) else None
    if not isinstance(rows, list) or not rows:
        raise ValueError("empty")
    outputs = rows[0].get("outputs") if isinstance(rows[0], dict) else None
    if not isinstance(outputs, dict):
        raise ValueError("empty")
    ndvi = _mean_from_output(outputs.get("ndvi") or {})
    ndwi = _mean_from_output(outputs.get("ndwi") or {})
    if ndvi is None or ndwi is None:
        raise ValueError("empty")
    return round(float(ndvi), 3), round(float(ndwi), 3)


def _classify_http_error(exc: BaseException) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code if exc.response is not None else 0
        if status in {401, 403}:
            return "unauthorized"
        return "http"
    if isinstance(exc, ValueError) and str(exc) == "empty":
        return "empty"
    return "http"


class SentinelSatelliteRiskProcessor:
    """NDVI and NDWI for crop and property risk.

    Local bbox bands are the default. Live Sentinel Hub is opt-in and falls
    back to those bands when the fetch fails.
    """

    def __init__(self, api_base_url: str | None = None):
        self.api_base_url = (api_base_url or settings.SENTINEL_API_BASE).rstrip("/")

    def fetch_ndvi_index(self, bbox: Tuple[float, float, float, float]) -> float:
        nir, red, _green = synthesize_bands(bbox)
        return round(compute_ndvi(nir, red), 3)

    def _access_token(self) -> str:
        global _oauth_token, _oauth_expires_at
        now = time.time()
        if _oauth_token and now < _oauth_expires_at - 30:
            return _oauth_token
        response = httpx.post(
            settings.SENTINEL_OAUTH_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": sentinel_client_id(),
                "client_secret": sentinel_client_secret(),
            },
            timeout=_HTTP_TIMEOUT,
        )
        response.raise_for_status()
        body = response.json()
        token = str(body.get("access_token") or "")
        if not token:
            raise ValueError("empty")
        expires = float(body.get("expires_in") or 3600)
        _oauth_token = token
        _oauth_expires_at = now + expires
        return token

    def _fetch_live_indices(self, bbox: Tuple[float, float, float, float]) -> Tuple[float, float]:
        token = self._access_token()
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=30)
        payload = {
            "input": {
                "bounds": {
                    "bbox": [float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])],
                    "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/4326"},
                },
                "data": [
                    {
                        "type": "sentinel-2-l2a",
                        "dataFilter": {
                            "timeRange": {
                                "from": start.strftime("%Y-%m-%dT00:00:00Z"),
                                "to": end.strftime("%Y-%m-%dT23:59:59Z"),
                            },
                            "maxCloudCoverage": 40,
                        },
                    }
                ],
            },
            "aggregation": {
                "timeRange": {
                    "from": start.strftime("%Y-%m-%dT00:00:00Z"),
                    "to": end.strftime("%Y-%m-%dT23:59:59Z"),
                },
                "aggregationInterval": {"of": "P30D"},
                "evalscript": _EVALSCRIPT,
                "resx": 0.002,
                "resy": 0.002,
            },
        }
        response = httpx.post(
            f"{self.api_base_url}/statistics",
            json=payload,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=_HTTP_TIMEOUT,
        )
        response.raise_for_status()
        return _parse_statistics(response.json())

    def evaluate_property_crop_risk(
        self,
        bbox: Tuple[float, float, float, float],
        crop_type: str = "corn",
        live: bool = False,
    ) -> Dict[str, Any]:
        """Hub failures return local indices; they do not raise."""
        if not live:
            return _local_result(
                bbox,
                crop_type,
                source="deterministic_bbox_bands",
                live_fetch=False,
            )
        if not sentinel_credentials_configured():
            return _local_result(
                bbox,
                crop_type,
                source="local_fallback",
                live_fetch=False,
                error="unauthorized",
            )
        try:
            ndvi, ndwi = self._fetch_live_indices(bbox)
        except Exception as exc:
            return _local_result(
                bbox,
                crop_type,
                source="local_fallback",
                live_fetch=False,
                error=_classify_http_error(exc),
            )
        payload = _score_from_indices(ndvi, ndwi, crop_type)
        payload.update(
            {
                "satellite_source": "sentinel_hub_s2l2a",
                "sentinel_live_fetch": True,
            }
        )
        return payload
