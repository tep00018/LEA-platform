"""Fixed-window rate limits in Redis (shared by every LEA process)."""

from __future__ import annotations

import time

from src.storage.locks import raw_connection


class RateLimiter:
    PREFIX = "ratelimit:"

    def __init__(self, redis_client, clock=time.time):
        self._client = redis_client
        self._clock = clock

    def _key(self, scope: str, key: str, window: int) -> tuple:
        start = int(self._clock() // window) * window
        return f"{self.PREFIX}{scope}:{key}:{start}", start + window

    def hit(self, scope: str, key: str, limit: int, window: int) -> int:
        """Count one event. Returns 0 if within ``limit`` per ``window`` seconds, else the
        seconds until the window resets."""
        name, resets = self._key(scope, key, window)
        conn = raw_connection(self._client)
        count = conn.incr(name)
        if count == 1:
            conn.expire(name, window + 1)
        return 0 if count <= limit else max(1, int(resets - self._clock()))

    def blocked(self, scope: str, key: str, limit: int, window: int) -> int:
        """Like ``hit`` without counting: seconds to wait if already over the limit."""
        name, resets = self._key(scope, key, window)
        count = int(raw_connection(self._client).get(name) or 0)
        return 0 if count < limit else max(1, int(resets - self._clock()))

    def reset(self, scope: str, key: str, window: int) -> None:
        raw_connection(self._client).delete(self._key(scope, key, window)[0])
