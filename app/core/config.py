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
    DMUE_ENV: str = "local"
    DEFAULT_MODEL_ROUTE: str = "dmue-full-v1"

    MAX_PREMIUM_INCREASE_PCT: float = 0.25
    MAX_PREMIUM_DECREASE_PCT: float = 0.20
    BASE_MONTHLY_AUTO_PREMIUM: float = 120.00

    CHROMA_PERSIST_DIR: str = "./data/chroma_db"
    AUDIT_LOG_PATH: str = "./data/audit/quotes.jsonl"
    TRACE_LOG_PATH: str = "./data/observability/traces.jsonl"

    LANGSMITH_TRACING: bool = False
    LANGSMITH_API_KEY: str = ""
    LANGSMITH_PROJECT: str = "dmue"

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

    # Sentinel Hub is opt-in. Local bbox bands stay the default.
    SENTINEL_LIVE_FETCH: bool = False
    SENTINEL_CLIENT_ID: str = ""
    SENTINEL_CLIENT_SECRET: str = ""
    SENTINEL_API_TOKEN: str = ""
    SENTINEL_OAUTH_URL: str = (
        "https://services.sentinel-hub.com/auth/realms/main/protocol/openid-connect/token"
    )
    SENTINEL_API_BASE: str = "https://services.sentinel-hub.com/api/v1"

    RATE_LIMIT_PER_MINUTE: int = 60
    INGEST_QUEUE_MAX: int = 100
    CACHE_TTL_SECONDS: float = 30.0
    CIRCUIT_FAILURES: int = 3
    CIRCUIT_COOLDOWN_SECONDS: float = 30.0

    DMUE_API_KEY: str = ""
    AUTH_REQUIRED: bool = False
    CORS_ALLOW_ORIGINS: str = ""

    UW_REFER_SCORE: float = 80.0
    UW_DECLINE_SCORE: float = 95.0
    UW_LOG_PATH: str = "./data/uw/actions.jsonl"
    SUBMISSIONS_LOG_PATH: str = "./data/uw/submissions.jsonl"


settings = Settings()
