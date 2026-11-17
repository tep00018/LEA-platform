"""Try as a student: a sandbox student account per teacher, and the teacher-only
explanation of each preview turn.

The sandbox is ``<teacher>.preview`` (a normal student account that nobody can log in to:
its password is random and never shown). It is tagged ``session_kind = test`` from the
start, so none of its activity reaches the research logs, analytics or exports, and it
records ``preview_of`` (the teacher). The teacher's app gets a token for it from
``start`` and uses it for the student screens.

While a preview account works, the services record what LEA decided on each turn
(objective, mastery before and after, grading, the learner model's state, scaffolding and
the course content retrieved) under ``preview:explain:<account>``. Only the owning
teacher can read it, through ``/teach/courses/{code}/preview/explain``; student responses
never carry it.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.core.validation import COURSE_CODE_PATTERN
from src.services.errors import InvalidInput
from src.services.events import EventRecorder, disabled

EXPLAIN_TURNS = 20
PROBES = [
    ("diagnostic", "Answer the tutor's first question with \"I don't know\""),
    ("wrong-twice", "Give a wrong answer twice in a row"),
    ("off-topic", "Ask Chat something off-topic"),
    ("give-answer", "Ask the tutor for the answer outright"),
    ("hint", "Ask for a hint instead of answering"),
]


def preview_username(teacher: str) -> str:
    """``<teacher>.preview``, shortened with a hash when that would pass 32 characters."""
    name = f"{teacher}.preview"
    if len(name) <= 32:
        return name
    return f"{teacher[:18]}.{hashlib.sha1(teacher.encode()).hexdigest()[:5]}.preview"


class PreviewService:
    def __init__(self, auth_service, registry, events: Optional[EventRecorder] = None):
        self.auth = auth_service
        self.registry = registry
        self.events = events or disabled()

    @property
    def conn(self):
        return self.auth.redis_client.get_redis()

    # ------------------------------------------------------------------ sandbox account

    def start(self, teacher: str, course: str) -> Dict[str, Any]:
        """Create or reuse the teacher's sandbox, enrol it in ``course`` and return a token."""
        if self.registry.kc_model(course) is None:
            raise InvalidInput("Publish this course's objectives first: students (and previews) use the published version.")
        username = preview_username(teacher)
        key = f"user:{username}"
        if not self.conn.exists(key):
            ok, message = self.auth.register_user(username, secrets.token_urlsafe(24),
                                                  f"{teacher} (preview)", [course])
            if not ok:
                raise InvalidInput(f"The preview account couldn't be created: {message}")
        self.conn.hset(key, mapping={"session_kind": "test", "preview_of": teacher, "role": "student"})
        self.events.forget_kind(username)
        courses = json.loads(self.conn.hget(key, "enrolled_courses") or "[]")
        if course not in courses:
            courses.append(course)
            self.conn.hset(key, "enrolled_courses", json.dumps(courses))
        token, expires = self.auth.tokens.issue(username)
        version = (self.registry.kc_model(course) or {}).get("version_info", {}).get("version", 0)
        self.events.staff(teacher, "preview_start", course=course, payload={"account": username})
        return {"username": username, "token": token, "course": course, "version": version,
                "expires_at": datetime.fromtimestamp(expires, timezone.utc).isoformat(timespec="seconds")}

    def reset(self, teacher: str, course: str) -> int:
        """Forget everything the sandbox did in ``course`` (it's test data); returns the
        number of records removed."""
        username = preview_username(teacher)
        removed = 0
        for key in list(self.conn.scan_iter(match=f"*{username}*", count=1000)):
            parts = key.split(":")
            if username not in parts or key == f"user:{username}" or key.startswith("auth:"):
                continue  # the account itself and its login stay
            other_courses = [p for p in parts if COURSE_CODE_PATTERN.match(p) and p != course]
            if not other_courses:  # this course's data, or data that isn't per course
                removed += self.conn.delete(key)
        progress = f"progress:{username}"
        if self.conn.type(progress) == "hash":
            removed += self.conn.hdel(progress, course)
        backup = Path(self.registry.data_dir) / "mastery_tracking" / f"mastery_{username}_{course}.json"
        if backup.exists():
            backup.unlink()
            removed += 1
        self.events.staff(teacher, "preview_reset", course=course, payload={"account": username, "removed": removed})
        return removed

    # ------------------------------------------------------------------ explanations

    def is_preview(self, username: str) -> bool:
        try:
            return self.events.is_test(username) and bool(self.conn.hget(f"user:{username}", "preview_of"))
        except Exception:
            return False

    def record(self, username: str, course: str, turn: Dict[str, Any]) -> None:
        """Keep the explanation of one preview turn (does nothing for real students)."""
        if not self.is_preview(username):
            return
        key = f"preview:explain:{username}"
        entry = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "course": course, **turn}
        self.conn.lpush(key, json.dumps(entry, default=str))
        self.conn.ltrim(key, 0, EXPLAIN_TURNS - 1)

    def explanations(self, teacher: str, course: str) -> List[Dict[str, Any]]:
        raw = self.conn.lrange(f"preview:explain:{preview_username(teacher)}", 0, EXPLAIN_TURNS - 1)
        return [e for e in (json.loads(r) for r in raw) if e.get("course") == course]

    def probes(self, course: str, week: Optional[int]) -> List[Dict[str, str]]:
        """Things to try in a preview: the general probes, then one question per learning
        objective of the week."""
        items = [{"id": pid, "text": text} for pid, text in PROBES]
        model = self.registry.kc_model(course) or {}
        for w in model.get("week_navigation", {}).values():
            if week is not None and w.get("week_number") != week:
                continue
            for lo in w.get("learning_objectives", [])[:6]:
                title = lo.get("short_title") or lo.get("title", "")
                items.append({"id": f"ask-{lo['lo_id']}", "text": f"Ask Chat a question about \"{title}\""})
            break
        return items


def learner_summary(state: Any) -> Dict[str, Any]:
    """The parts of a learner assessment the explain panel shows."""
    data = state.as_context() if hasattr(state, "as_context") else dict(state or {})
    cognitive = data.get("cognitive_state") or {}
    scaffolding = data.get("scaffolding_strategy") or {}
    return {
        "zpd": cognitive.get("zpd_score"), "cognitive_load": cognitive.get("cognitive_load"),
        "motivation": data.get("motivation_state"),
        "scaffolding": scaffolding.get("strategy_type") or scaffolding.get("strategy"),
        "intensity": scaffolding.get("intensity_level") or scaffolding.get("intensity"),
    }
