"""Quiz, tutor and chat sessions stored in Redis as JSON.

Sessions live in Redis rather than in the web process, so a page refresh, a second tab or a
restart of LEA picks up where the learner left off, and any client (Streamlit now, the API
and Flutter later) sees the same session.
"""

from __future__ import annotations

import contextlib
import logging
from typing import Iterator, Optional, Type, TypeVar

from pydantic import BaseModel, ValidationError

from src.services.errors import Busy
from src.storage.locks import LockBusy, raw_connection, redis_lock

logger = logging.getLogger(__name__)

M = TypeVar("M", bound=BaseModel)

DAY = 24 * 3600
TTL = {"quiz": DAY, "tutor": DAY, "chat": 14 * DAY}


class SessionStore:
    PREFIX = "lea:session"

    def __init__(self, redis_client):
        self._client = redis_client

    @property
    def conn(self):
        conn = raw_connection(self._client)
        if conn is None:
            raise RuntimeError("Redis is not connected")
        return conn

    def key(self, kind: str, *parts: str) -> str:
        return ":".join([self.PREFIX, kind, *parts])

    def load(self, model: Type[M], kind: str, *parts: str) -> Optional[M]:
        raw = self.conn.get(self.key(kind, *parts))
        if not raw:
            return None
        try:
            return model.model_validate_json(raw)
        except ValidationError as e:
            # A session written by an older LEA version: drop it rather than crash.
            logger.warning("Discarding unreadable %s session %s: %s", kind, parts, e)
            self.delete(kind, *parts)
            return None

    def save(self, value: BaseModel, kind: str, *parts: str) -> None:
        self.conn.set(self.key(kind, *parts), value.model_dump_json(), ex=TTL.get(kind, DAY))

    def delete(self, kind: str, *parts: str) -> None:
        self.conn.delete(self.key(kind, *parts))

    @contextlib.contextmanager
    def locked(self, kind: str, *parts: str, timeout: float = 60, wait: float = 2) -> Iterator[None]:
        """Serialise changes to one session. A second request while the first is still
        running (a double click, a second tab) gets ``Busy`` instead of racing it. The lock
        is renewed while the work runs, however long the model takes."""
        try:
            with redis_lock(self._client, "session:" + ":".join([kind, *parts]), timeout=timeout, wait=wait,
                            keep_alive=True):
                yield
        except LockBusy:
            raise Busy("Still working on your last request. Give it a moment and try again.") from None
