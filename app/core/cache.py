import time
from typing import Any, Hashable, Optional

from app.core.config import settings


class TtlCache:
    def __init__(self, ttl_seconds: float | None = None):
        self.ttl = float(ttl_seconds if ttl_seconds is not None else settings.CACHE_TTL_SECONDS)
        self._store: dict[Hashable, tuple[float, Any]] = {}

    def get(self, key: Hashable, now: float | None = None) -> Optional[Any]:
        clock = time.monotonic() if now is None else now
        item = self._store.get(key)
        if item is None:
            return None
        expires, value = item
        if clock >= expires:
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: Hashable, value: Any, now: float | None = None) -> None:
        clock = time.monotonic() if now is None else now
        self._store[key] = (clock + self.ttl, value)

    def invalidate(self, key: Hashable) -> None:
        self._store.pop(key, None)

    def invalidate_policy(self, policy_id: str) -> None:
        drop = [key for key in self._store if isinstance(key, tuple) and key[:1] == (policy_id,)]
        for key in drop:
            self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()


context_cache = TtlCache()
satellite_cache = TtlCache()
