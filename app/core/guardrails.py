import math
from typing import Any, Dict, List, Tuple

from app.core.config import PROHIBITED_FACTOR_KEYS, settings
from app.core.evals import prohibited_term_leak_count


class ActuarialGuardrailEnforcer:
    def __init__(self):
        self.max_increase = settings.MAX_PREMIUM_INCREASE_PCT
        self.max_decrease = settings.MAX_PREMIUM_DECREASE_PCT
        self.base_rate = settings.BASE_MONTHLY_AUTO_PREMIUM

    def enforce_rate_caps(
        self, calculated_premium: float, previous_premium: float
    ) -> Tuple[float, bool, str]:
        max_allowed = previous_premium * (1.0 + self.max_increase)
        min_allowed = previous_premium * (1.0 - self.max_decrease)

        clamped = False
        reason = "Within regulatory bounds"
        final_premium = calculated_premium

        if calculated_premium > max_allowed:
            final_premium = max_allowed
            clamped = True
            reason = f"Capped at max regulatory increase (+{int(self.max_increase * 100)}%)"
        elif calculated_premium < min_allowed:
            final_premium = min_allowed
            clamped = True
            reason = f"Floor set at max regulatory decrease (-{int(self.max_decrease * 100)}%)"

        return round(final_premium, 2), clamped, reason

    def reject_prohibited_keys(self, payload: Dict[str, Any]) -> None:
        found = sorted(
            str(key)
            for key in payload
            if str(key).lower() in PROHIBITED_FACTOR_KEYS
        )
        if found:
            raise ValueError(f"Prohibited factor present: {', '.join(found)}")

    def assert_no_prohibited_language(self, text: str) -> None:
        if prohibited_term_leak_count(text) > 0:
            raise ValueError("Prohibited factor leaked into explanation")

    def filter_anomalies(self, telemetry: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
        policy_id = str(telemetry.get("policy_id", "")).strip()
        if not policy_id:
            raise ValueError("policy_id is required")

        hard = self._finite(
            telemetry.get("hard_brakes_per_100mi", 0), "hard_brakes_per_100mi"
        )
        night = self._finite(telemetry.get("night_miles_pct", 0), "night_miles_pct")
        speed = self._finite(telemetry.get("speed_violations", 0), "speed_violations")
        miles = self._finite(telemetry.get("total_miles", 0), "total_miles")
        previous = self._finite(telemetry.get("previous_premium"), "previous_premium")

        if hard < 0 or miles < 0 or speed < 0:
            raise ValueError("Sensor value is outside physical bounds")
        if night < 0 or night > 1:
            raise ValueError("night_miles_pct is outside physical bounds")
        if previous <= 0:
            raise ValueError("previous_premium must be greater than zero")
        if abs(speed - round(speed)) > 1e-6:
            raise ValueError("speed_violations must be a whole number")

        anomalies: List[str] = []
        if hard > settings.HARD_BRAKE_MALFUNCTION_PER_100MI:
            anomalies.append(
                "Hardware malfunction: hard braking of "
                f"{hard:g} per 100 miles was excluded."
            )
            hard = settings.NEUTRAL_HARD_BRAKES_PER_100MI

        cleaned: Dict[str, Any] = {
            "policy_id": policy_id,
            "hard_brakes_per_100mi": hard,
            "night_miles_pct": night,
            "speed_violations": int(round(speed)),
            "total_miles": miles,
            "previous_premium": previous,
        }

        if telemetry.get("iot_moisture") is not None:
            moisture = self._finite(telemetry["iot_moisture"], "iot_moisture")
            if moisture < 0 or moisture > 1:
                raise ValueError("iot_moisture is outside physical bounds")
            cleaned["iot_moisture"] = moisture

        if telemetry.get("weather_precip_mm") is not None:
            precip = self._finite(telemetry["weather_precip_mm"], "weather_precip_mm")
            if precip < 0:
                raise ValueError("weather_precip_mm is outside physical bounds")
            cleaned["weather_precip_mm"] = precip

        if telemetry.get("weather_wind_mph") is not None:
            wind = self._finite(telemetry["weather_wind_mph"], "weather_wind_mph")
            if wind < 0:
                raise ValueError("weather_wind_mph is outside physical bounds")
            cleaned["weather_wind_mph"] = wind

        bbox = telemetry.get("bbox")
        if bbox not in (None, [], ()):
            if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
                raise ValueError("bbox must be four numbers: min_lon, min_lat, max_lon, max_lat")
            min_lon, min_lat, max_lon, max_lat = (
                self._finite(value, "bbox") for value in bbox
            )
            if not (-180 <= min_lon <= 180 and -180 <= max_lon <= 180):
                raise ValueError("bbox longitude is outside physical bounds")
            if not (-90 <= min_lat <= 90 and -90 <= max_lat <= 90):
                raise ValueError("bbox latitude is outside physical bounds")
            if min_lon > max_lon or min_lat > max_lat:
                raise ValueError("bbox is not ordered as min_lon, min_lat, max_lon, max_lat")
            cleaned["bbox"] = [min_lon, min_lat, max_lon, max_lat]

        return cleaned, anomalies

    def _finite(self, value: Any, name: str) -> float:
        if value is None:
            raise ValueError(f"{name} is required")
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{name} must be a finite number")
        if not math.isfinite(number):
            raise ValueError(f"{name} must be a finite number")
        return number
