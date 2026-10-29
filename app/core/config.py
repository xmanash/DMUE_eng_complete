from pydantic_settings import BaseSettings, SettingsConfigDict

# Keys that must never enter rating, memory, or policyholder text.
PROHIBITED_FACTOR_KEYS = frozenset(
    {
        "gender",
        "race",
        "sex",
        "ethnicity",
        "zipcode",
        "zip_code",
        "credit_score",
    }
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    PROJECT_NAME: str = "Dynamic Micro-Underwriting Engine"
    VERSION: str = "1.0.0"

    MAX_PREMIUM_INCREASE_PCT: float = 0.25
    MAX_PREMIUM_DECREASE_PCT: float = 0.20
    BASE_MONTHLY_AUTO_PREMIUM: float = 120.00

    CHROMA_PERSIST_DIR: str = "./data/chroma_db"

    # Guardrail 1: hard braking above this rate is a sensor fault, not a risk factor.
    HARD_BRAKE_MALFUNCTION_PER_100MI: float = 20.0
    NEUTRAL_HARD_BRAKES_PER_100MI: float = 3.0

    # Optional IoT and weather deltas. Applied only when the signal is present and high.
    IOT_MOISTURE_HIGH: float = 0.85
    IOT_MOISTURE_RISK_DELTA: float = 8.0
    WEATHER_WIND_HIGH_MPH: float = 40.0
    WEATHER_WIND_RISK_DELTA: float = 8.0
    WEATHER_PRECIP_HIGH_MM: float = 50.0
    WEATHER_PRECIP_RISK_DELTA: float = 6.0

    # Section 6 eval thresholds.
    FACTOR_COVERAGE_MIN: float = 0.50
    FLESCH_READING_EASE_MIN: float = 60.0
    FLESCH_GRADE_MAX: float = 8.0

    # Recognized for deployment config. Index math stays local; see satellite_processor.
    SENTINEL_API_TOKEN: str = ""


settings = Settings()
