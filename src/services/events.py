"""What the services write to the durable event log (``src.storage.event_log``).

Learners are recorded only as a salted hash of their username (``LEA_EVENT_SALT`` in
.env; the same salt must be kept, or old and new pseudonyms stop matching). Each event is
tagged with the account's session kind: ``real`` (the default), ``test`` (preview and test
accounts, set with ``scripts/manage_account.py``) or ``simulated``. Test accounts also
never reach the CSV research logs.

Free text (chat questions, answers) is stored with the student's own username and full
name replaced by ``[student]``. That is **not full anonymisation**: students can type
other names or details, so treat text payloads as personal data.

Recording never raises and never changes what a student sees.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import threading
import time
from typing import Any, Callable, Dict, Optional

from src.core.kc_ids import parent_ids
from src.storage.event_log import SESSION_KINDS, EventLog

logger = logging.getLogger(__name__)

KIND_CACHE_SECONDS = 60
MAX_TEXT_CHARS = 4000
PLACEHOLDER = "[student]"


class EventRecorder:
    def __init__(self, log: Optional[EventLog], salt: Optional[str], redis_client=None,
                 kc_model: Optional[Callable[[str], Optional[dict]]] = None,
                 kc_version: Optional[Callable[[str], Optional[str]]] = None):
        if log is not None and not salt:
            logger.error("LEA_EVENT_SALT is not set: the event log is off. Add it to .env (see docs/SETUP.md).")
            log = None
        self.log = log
        self._salt = (salt or "").encode("utf-8")
        self.redis_client = redis_client
        self._kc_model = kc_model or (lambda code: None)
        self._kc_version = kc_version or (lambda code: None)
        self._kinds: Dict[str, tuple[str, float]] = {}
        self._kinds_lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self.log is not None

    # ------------------------------------------------------------------ identity

    def pseudonym(self, username: str) -> str:
        return hmac.new(self._salt, (username or "").encode("utf-8"), hashlib.sha256).hexdigest()[:32]

    def session_kind(self, username: str) -> str:
        """The account's session kind (``real`` unless marked otherwise), cached briefly."""
        now = time.monotonic()
        with self._kinds_lock:
            cached = self._kinds.get(username)
            if cached and now - cached[1] < KIND_CACHE_SECONDS:
                return cached[0]
        kind = "real"
        try:
            conn = self.redis_client.get_redis() if self.redis_client is not None else None
            stored = conn.hget(f"user:{username}", "session_kind") if conn is not None else None
            if stored in SESSION_KINDS:
                kind = stored
        except Exception as e:
            logger.warning(f"Couldn't read the session kind of an account: {e}")
        with self._kinds_lock:
            self._kinds[username] = (kind, now)
        return kind

    def _pseudonymise_ids(self, payload: Optional[Dict[str, Any]], username: str) -> Optional[Dict[str, Any]]:
        """Replace the raw username wherever it appears in the payload (quiz and tutor
        session IDs embed it, and so does the orchestrator's session context)."""
        if not payload or not username:
            return payload
        text = json.dumps(payload, default=str, ensure_ascii=False)
        pattern = r"(?<![A-Za-z0-9])" + re.escape(username) + r"(?![A-Za-z0-9])"
        if not re.search(pattern, text):
            return payload
        return json.loads(re.sub(pattern, "p-" + self.pseudonym(username)[:12], text))

    def is_test(self, username: str) -> bool:
        return self.session_kind(username) == "test"

    def forget_kind(self, username: str) -> None:
        with self._kinds_lock:
            self._kinds.pop(username, None)

    def scrub(self, text: Any, username: str) -> str:
        """The text with the student's own username and full name replaced (not full
        anonymisation; see the module docstring)."""
        text = str(text or "")[:MAX_TEXT_CHARS]
        names = [username]
        try:
            conn = self.redis_client.get_redis() if self.redis_client is not None else None
            full_name = conn.hget(f"user:{username}", "full_name") if conn is not None else None
            if full_name:
                names.append(full_name)
                names += [part for part in full_name.split() if len(part) >= 3]
        except Exception:
            pass
        for name in sorted({n for n in names if n and len(n) >= 3}, key=len, reverse=True):
            text = re.sub(r"(?<!\w)" + re.escape(name) + r"(?!\w)", PLACEHOLDER, text, flags=re.IGNORECASE)
        return text

    # ------------------------------------------------------------------ writing

    def learner(self, username: str, course: Optional[str], type: str, *, mode: str,
                week: Optional[int] = None, go_id: Optional[str] = None, correct: Optional[bool] = None,
                score: Optional[float] = None, question_type: Optional[str] = None,
                payload: Optional[Dict[str, Any]] = None) -> None:
        """One event from a learner's session (quiz, tutor or chat)."""
        if self.log is None:
            return
        try:
            lo_id = None
            if go_id:
                lo_id, go_week = parent_ids(go_id, self._kc_model(course) if course else None)
                week = week if week is not None else go_week
            self.log.append(
                type=type, session_kind=self.session_kind(username), course=course,
                kc_version=self._kc_version(course) if course else None,
                username_hash=self.pseudonym(username), mode=mode, go_id=go_id, lo_id=lo_id,
                week=week, correct=correct, score=score, question_type=question_type,
                payload=self._pseudonymise_ids(payload, username),
            )
        except Exception as e:
            logger.error(f"Recording a {type} event failed: {e}")

    def staff(self, actor: str, action: str, course: Optional[str] = None,
              payload: Optional[Dict[str, Any]] = None) -> None:
        """An audit-trail event for an admin or teacher action (real username kept)."""
        if self.log is None:
            return
        try:
            self.log.append(type=action, session_kind="real", course=course, actor=actor,
                            mode="admin", payload=payload)
        except Exception as e:
            logger.error(f"Recording staff action {action} failed: {e}")

    def decision(self, type: str, row: Dict[str, Any]) -> None:
        """An adaptive decision (the same fields as the CSV research logs), learner pseudonymised."""
        username = row.get("username")
        if self.log is None or not username or username == "unknown":
            return
        payload = {k: v for k, v in row.items() if k not in ("username", "course", "go_id", "mode", "week")}
        course = row.get("course") if row.get("course") not in (None, "unknown") else None
        go_id = row.get("go_id") if row.get("go_id") not in (None, "unknown") else None
        mode = row.get("mode") if row.get("mode") in ("quiz", "tutor", "chat") else None
        self.learner(username, course, type, mode=mode, week=row.get("week"), go_id=go_id, payload=payload)


def research_learners(recorder: EventRecorder) -> set[str]:
    """Pseudonyms of the learners whose events may be exported for research: accounts with
    research consent, and simulated accounts (which need none). Test accounts never."""
    conn = recorder.redis_client.get_redis()
    allowed = set()
    for key in conn.scan_iter(match="user:*", count=500):
        try:
            username, kind, consent = conn.hmget(key, ["username", "session_kind", "research_consent"])
        except Exception:  # another kind of key under user:
            continue
        if not username or kind == "test":
            continue
        if consent == "true" or kind == "simulated":
            allowed.add(recorder.pseudonym(username))
    return allowed


def disabled() -> EventRecorder:
    """A recorder that writes nothing (tools and tests that don't need the log)."""
    return EventRecorder(None, None)
