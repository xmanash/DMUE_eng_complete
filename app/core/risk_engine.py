import numpy as np
from typing import Any, Dict, List, Tuple

from app.core.config import settings


class DynamicRiskEngine:
    def __init__(self, base_premium: float = 120.0):
        self.base_premium = base_premium

    def premium_for_score(self, risk_score: float) -> float:
        multiplier = 0.7 + (risk_score / 100.0) * 0.8
        return self.base_premium * multiplier

    def calculate_auto_telemetry_score(
        self, telemetry: Dict[str, Any]
    ) -> Tuple[float, float, list]:
        hard_brakes = telemetry.get("hard_brakes_per_100mi", 0)
        night_pct = telemetry.get("night_miles_pct", 0.0)
        speed_violations = telemetry.get("speed_violations", 0)

        risk_score = 50.0
        reasons = []

        if hard_brakes > 5:
            risk_score += 15
            reasons.append(
                f"Hard braking is frequent at {hard_brakes:g} events per 100 miles."
            )
        elif hard_brakes < 2:
            risk_score -= 10
            reasons.append("Braking is smooth and steady.")

        if night_pct > 0.25:
            reasons.append(
                f"Night driving is high at {int(round(night_pct * 100))} percent of miles."
            )
            risk_score += 12

        if speed_violations > 2:
            risk_score += 20
            reasons.append(f"Speeding occurred {int(speed_violations)} times.")

        risk_score = float(np.clip(risk_score, 0.0, 100.0))
        raw_premium = self.premium_for_score(risk_score)
        return risk_score, raw_premium, reasons

    def apply_environment_signals(
        self,
        risk_score: float,
        telemetry: Dict[str, Any],
        reasons: List[str],
    ) -> Tuple[float, float, List[str]]:
        updated = list(reasons)
        score = float(risk_score)

        moisture = telemetry.get("iot_moisture")
        if moisture is not None and moisture >= settings.IOT_MOISTURE_HIGH:
            score += settings.IOT_MOISTURE_RISK_DELTA
            updated.append(f"Home moisture is high at {int(round(moisture * 100))} percent.")

        wind = telemetry.get("weather_wind_mph")
        if wind is not None and wind >= settings.WEATHER_WIND_HIGH_MPH:
            score += settings.WEATHER_WIND_RISK_DELTA
            updated.append(f"Wind is high at {wind:g} miles per hour.")

        precip = telemetry.get("weather_precip_mm")
        if precip is not None and precip >= settings.WEATHER_PRECIP_HIGH_MM:
            score += settings.WEATHER_PRECIP_RISK_DELTA
            updated.append(f"Rain is heavy at {precip:g} millimeters.")

        score = float(np.clip(score, 0.0, 100.0))
        return score, self.premium_for_score(score), updated


def recommendations_for(reasons: List[str]) -> List[str]:
    advice = []
    for reason in reasons:
        text = reason.lower()
        if "hard braking" in text:
            advice.append("Leave more space so braking stays gentle.")
        elif "night driving" in text:
            advice.append("Drive more of your miles in daylight.")
        elif "speeding" in text:
            advice.append("Stay at or under the speed limit.")
        elif "moisture" in text:
            advice.append("Check the home for a leak and dry the wet area.")
        elif "wind" in text:
            advice.append("Secure loose items before the next high wind.")
        elif "rain" in text:
            advice.append("Clear drains before the next heavy rain.")
        elif "plant health is poor" in text or "plant health is moderate" in text:
            advice.append("Inspect the crop or yard and water if the soil is dry.")
        elif "smooth" in text or "plant health is strong" in text:
            advice.append("Keep the same safe habits next month.")
    return advice
