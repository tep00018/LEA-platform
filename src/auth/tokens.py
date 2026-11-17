"""Login tokens, validated on the server for every API request.

A token is 32 random bytes handed to the client once. Redis stores only its SHA-256
hash, the username and when it was issued. A token expires after ``IDLE_SECONDS``
without use (each use renews it) and in any case ``MAX_AGE_SECONDS`` after login.
Logging out deletes it at once; ``revoke_all`` ends every session of a user.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from typing import Optional, Tuple

from src.storage.locks import raw_connection

IDLE_SECONDS = 12 * 3600
MAX_AGE_SECONDS = 7 * 24 * 3600


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class TokenStore:
    PREFIX = "auth:token:"
    USER_PREFIX = "auth:user_tokens:"

    def __init__(self, redis_client, clock=time.time):
        self._client = redis_client
        self._clock = clock

    @property
    def conn(self):
        return raw_connection(self._client)

    def issue(self, username: str) -> Tuple[str, float]:
        """A new token for ``username`` and when it expires if unused."""
        token = secrets.token_urlsafe(32)
        now = self._clock()
        key = self.PREFIX + _digest(token)
        # Bound to this account's creation time, so a deleted and re-registered username
        # doesn't inherit the old account's tokens.
        account = self.conn.hget(f"user:{username}", "created_at") or ""
        self.conn.set(key, json.dumps({"username": username, "issued": now, "account": account}), ex=IDLE_SECONDS)
        self.conn.sadd(self.USER_PREFIX + username, _digest(token))
        self.conn.expire(self.USER_PREFIX + username, MAX_AGE_SECONDS)
        return token, now + IDLE_SECONDS

    def validate(self, token: Optional[str]) -> Optional[str]:
        """The username for a live token (renewing it), or None."""
        if not token or len(token) > 200:
            return None
        key = self.PREFIX + _digest(token)
        raw = self.conn.get(key)
        if not raw:
            return None
        data = json.loads(raw)
        username = data["username"]
        remaining = data["issued"] + MAX_AGE_SECONDS - self._clock()
        if remaining <= 0 or not self._current_account(username, data.get("account", "")):
            self.revoke(token)
            return None
        self.conn.expire(key, int(min(IDLE_SECONDS, remaining)) or 1)
        return username

    def revoke(self, token: str) -> None:
        digest = _digest(token)
        raw = self.conn.get(self.PREFIX + digest)
        self.conn.delete(self.PREFIX + digest)
        if raw:
            self.conn.srem(self.USER_PREFIX + json.loads(raw)["username"], digest)

    def revoke_all(self, username: str) -> None:
        for digest in self.conn.smembers(self.USER_PREFIX + username):
            self.conn.delete(self.PREFIX + digest)
        self.conn.delete(self.USER_PREFIX + username)

    def _current_account(self, username: str, account: str) -> bool:
        """The user still exists, is active (a missing flag counts as active, as at login),
        and is the same account the token was issued to."""
        exists, active, created = self.conn.hmget(f"user:{username}", "username", "is_active", "created_at")
        return bool(exists) and (active or "true").lower() == "true" and (created or "") == account
