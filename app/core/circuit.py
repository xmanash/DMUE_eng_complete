"""Fail-open satellite breaker. Telematics still score while open."""

import time

from app.core.config import settings


class CircuitBreaker:
    """Open after N failures; auto-reset after cooldown."""

    def __init__(
        self,
        failures: int | None = None,
        cooldown_seconds: float | None = None,
    ):
        self.threshold = int(failures if failures is not None else settings.CIRCUIT_FAILURES)
        self.cooldown = float(
            cooldown_seconds if cooldown_seconds is not None else settings.CIRCUIT_COOLDOWN_SECONDS
        )
        self.failures = 0
        self.opened_at = 0.0

    def is_open(self, now: float | None = None) -> bool:
        if self.failures < self.threshold:
            return False
        clock = time.monotonic() if now is None else now
        if clock - self.opened_at >= self.cooldown:
            self.failures = 0
            self.opened_at = 0.0
            return False
        return True

    def record_success(self) -> None:
        self.failures = 0
        self.opened_at = 0.0

    def record_failure(self, now: float | None = None) -> None:
        self.failures += 1
        if self.failures >= self.threshold:
            self.opened_at = time.monotonic() if now is None else now


satellite_circuit = CircuitBreaker()
