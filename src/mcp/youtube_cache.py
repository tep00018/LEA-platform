"""Caching YouTube searches and pausing them when Google's daily quota runs out.

A YouTube Data API search costs about 101 quota units and the default daily quota is
10,000 units, so roughly 99 searches a day for the whole project. The tutor's query for an
objective is the same every time, so:

- **Cache.** A search's videos are kept in Redis for a week (``CACHE_TTL_SECONDS``), keyed by
  the query. Each objective is searched at most once a week, whatever the number of students.
- **Quota pause.** After a quota error (HTTP 403 ``quotaExceeded`` / ``rateLimitExceeded`` or
  429) no search is sent until Google's quota resets at midnight Pacific time; the tutor
  falls back to curated videos or search links meanwhile.
- **Failure memory.** Any other failure for a query is remembered for ten minutes, so a
  broken query isn't retried on every reply.

Nothing here needs the API key. Redis errors never break a search: without Redis (or if it
fails) every call simply goes straight to Google, as before.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 7 * 24 * 3600
FAILURE_TTL_SECONDS = 10 * 60
QUOTA_KEY = "youtube:quota_exhausted"
QUOTA_MARKERS = ("quotaexceeded", "ratelimitexceeded", "dailylimitexceeded", "quota exceeded", "httperror 429",
                 "429 when requesting")


def is_quota_error(error: BaseException | str) -> bool:
    """Does this error mean Google's quota is used up (as opposed to a bad query or a network fault)?"""
    text = str(error).lower()
    return any(marker in text for marker in QUOTA_MARKERS)


def seconds_until_quota_reset(now: Optional[datetime] = None) -> int:
    """Seconds until the next midnight in Pacific time, when YouTube's daily quota resets."""
    now = now or datetime.now(timezone.utc)
    try:
        from zoneinfo import ZoneInfo

        pacific = now.astimezone(ZoneInfo("America/Los_Angeles"))
        reset = (pacific + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return max(60, int((reset - pacific).total_seconds()))
    except Exception:  # no tz database: 08:00 UTC (midnight PST), an hour late in summer at worst
        reset = (now + timedelta(days=1 if now.hour >= 8 else 0)).replace(hour=8, minute=0, second=0, microsecond=0)
        return max(60, int((reset - now).total_seconds()))


def _digest(query: str) -> str:
    return hashlib.sha1(query.strip().lower().encode("utf-8")).hexdigest()[:20]


class YouTubeSearchCache:
    def __init__(self, redis_client, clock: Callable[[], float] = time.time):
        self._client = redis_client
        self._clock = clock

    def _conn(self):
        try:
            return self._client.get_redis() if self._client is not None else None
        except Exception as e:
            logger.debug(f"YouTube cache: no Redis connection: {e}")
            return None

    @staticmethod
    def _text(value) -> Optional[str]:
        return value.decode("utf-8") if isinstance(value, bytes) else value

    # -- cached searches
    def get(self, query: str) -> Optional[List[Dict[str, Any]]]:
        conn = self._conn()
        if conn is None:
            return None
        try:
            raw = self._text(conn.get(f"youtube:search:{_digest(query)}"))
            return json.loads(raw)["videos"] if raw else None
        except Exception as e:
            logger.debug(f"YouTube cache read failed: {e}")
            return None

    def put(self, query: str, videos: List[Dict[str, Any]]) -> None:
        conn = self._conn()
        if conn is None or not videos:
            return
        try:
            conn.set(f"youtube:search:{_digest(query)}", json.dumps({"videos": videos, "cached_at": self._clock()}),
                     ex=CACHE_TTL_SECONDS)
        except Exception as e:
            logger.debug(f"YouTube cache write failed: {e}")

    # -- quota pause
    def quota_paused_until(self) -> Optional[float]:
        """Epoch seconds when searches resume, or None if they aren't paused."""
        conn = self._conn()
        if conn is None:
            return None
        try:
            raw = self._text(conn.get(QUOTA_KEY))
            until = float(raw) if raw else None
            return until if until and until > self._clock() else None
        except Exception:
            return None

    def pause_for_quota(self) -> float:
        """Stop searching until the quota resets; returns when."""
        seconds = seconds_until_quota_reset(datetime.fromtimestamp(self._clock(), timezone.utc))
        until = self._clock() + seconds
        conn = self._conn()
        if conn is not None:
            try:
                conn.set(QUOTA_KEY, str(until), ex=seconds)
            except Exception as e:
                logger.debug(f"YouTube quota pause not stored: {e}")
        logger.warning("YouTube quota exhausted: automatic video search is paused until it resets")
        return until

    def resume(self) -> None:
        """Clear the pause (for a teacher or an admin who has raised the quota)."""
        conn = self._conn()
        if conn is not None:
            try:
                conn.delete(QUOTA_KEY)
            except Exception:
                pass

    # -- other failures
    def failed_recently(self, query: str) -> bool:
        conn = self._conn()
        try:
            return bool(conn is not None and conn.exists(f"youtube:failed:{_digest(query)}"))
        except Exception:
            return False

    def note_failure(self, query: str) -> None:
        conn = self._conn()
        if conn is not None:
            try:
                conn.set(f"youtube:failed:{_digest(query)}", "1", ex=FAILURE_TTL_SECONDS)
            except Exception:
                pass

    # -- for the Teacher screen
    def status(self) -> Dict[str, Any]:
        until = self.quota_paused_until()
        cached = 0
        conn = self._conn()
        if conn is not None:
            try:
                cached = sum(1 for _ in conn.scan_iter(match="youtube:search:*", count=200))
            except Exception:
                pass
        return {"quota_paused_until": datetime.fromtimestamp(until, timezone.utc).isoformat(timespec="minutes")
                if until else None, "cached_searches": cached}
