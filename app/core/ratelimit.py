import time
from typing import Dict, Tuple

from app.core.config import settings


class TokenBucket:
    """Per-key token bucket. Capacity and refill rate are tokens per minute."""

    def __init__(self, per_minute: int | None = None):
        self.per_minute = int(per_minute if per_minute is not None else settings.RATE_LIMIT_PER_MINUTE)
        self._buckets: Dict[str, Tuple[float, float]] = {}

    def reset(self) -> None:
        self._buckets.clear()

    def allow(self, key: str, now: float | None = None) -> bool:
        if self.per_minute <= 0:
            return False
        clock = time.monotonic() if now is None else now
        tokens, touched = self._buckets.get(key, (float(self.per_minute), clock))
        elapsed = max(0.0, clock - touched)
        tokens = min(float(self.per_minute), tokens + elapsed * (self.per_minute / 60.0))
        if tokens < 1.0:
            self._buckets[key] = (tokens, clock)
            return False
        self._buckets[key] = (tokens - 1.0, clock)
        return True


limiter = TokenBucket()
