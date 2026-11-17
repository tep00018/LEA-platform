"""Roles, course ownership and account administration (the Teacher module's access rules).

Every account has a role: ``student`` (the default: everything LEA did before), ``teacher``
(the Teacher area for the courses they own) or ``admin`` (everything, plus accounts and
ownership). A course's owners are the Redis set ``course:{code}:owners``. There is no
self-service teacher sign-up: the first admin is made with
``scripts/manage_account.py make-admin``, and admins make everyone else.

Every change here is written to the event log's staff audit trail (real usernames).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from src.core.validation import course_code as valid_course_code
from src.core.validation import is_valid_username
from src.services.errors import InvalidInput, NotFound, NotPermitted
from src.services.events import EventRecorder, disabled
from src.storage.event_log import SESSION_KINDS

ROLES = ("student", "teacher", "admin")
STAFF_ROLES = ("teacher", "admin")
MIN_PASSWORD_LENGTH = 8


def owners_key(course: str) -> str:
    return f"course:{course}:owners"


class StaffService:
    def __init__(self, auth_service, events: Optional[EventRecorder] = None, available_courses=None):
        self.auth = auth_service
        self.events = events or disabled()
        self._available_courses = available_courses or (lambda: [])

    @property
    def conn(self):
        return self.auth.redis_client.get_redis()

    # ------------------------------------------------------------------ reads

    def role(self, username: str) -> str:
        role = self.conn.hget(f"user:{username}", "role")
        return role if role in ROLES else "student"

    def owned_courses(self, username: str) -> List[str]:
        """Courses this account owns, sorted (by scanning the owner sets)."""
        owned = []
        for key in self.conn.scan_iter(match="course:*:owners", count=500):
            if self.conn.sismember(key, username):
                owned.append(key.split(":")[1])
        return sorted(owned)

    def owners(self, course: str) -> List[str]:
        return sorted(self.conn.smembers(owners_key(self._code(course))))

    def users(self) -> List[Dict[str, Any]]:
        """Every account, for the admin list (no password data)."""
        owned: Dict[str, List[str]] = {}
        for key in self.conn.scan_iter(match="course:*:owners", count=500):
            for member in self.conn.smembers(key):
                owned.setdefault(member, []).append(key.split(":")[1])
        rows = []
        for key in self.conn.scan_iter(match="user:*", count=500):
            try:
                data = self.conn.hmget(key, ["username", "full_name", "role", "is_active", "session_kind",
                                             "created_at", "enrolled_courses"])
            except Exception:  # another kind of key under user:
                continue
            username, full_name, role, active, kind, created, courses = data
            if not username:
                continue
            rows.append({
                "username": username, "full_name": full_name or "",
                "role": role if role in ROLES else "student",
                "active": (active or "true").lower() == "true",
                "session_kind": kind or "real", "created_at": created or "",
                "enrolled_courses": json.loads(courses) if courses else [],
                "owned_courses": sorted(owned.get(username, [])),
            })
        return sorted(rows, key=lambda r: r["username"].lower())

    # ------------------------------------------------------------------ checks

    def require_admin(self, username: str) -> None:
        if self.role(username) != "admin":
            raise NotPermitted("Only an admin can do that.")

    def require_teacher(self, username: str, course: str) -> str:
        """The course code, if the account owns the course or is an admin; NotPermitted
        otherwise (the same answer whether or not the course exists)."""
        role = self.role(username)
        try:
            code = valid_course_code(course)
        except ValueError:
            code = None
        if role == "admin" and code:
            return code
        if role == "teacher" and code and self.conn.sismember(owners_key(code), username):
            return code
        raise NotPermitted("You don't teach this course.")

    def require_staff(self, username: str) -> str:
        role = self.role(username)
        if role not in STAFF_ROLES:
            raise NotPermitted("This area is for teachers.")
        return role

    # ------------------------------------------------------------------ admin actions

    def create_staff(self, actor: str, username: str, full_name: str, password: str, role: str = "teacher") -> Dict:
        if role not in STAFF_ROLES:
            raise InvalidInput("New staff accounts are teachers or admins.")
        if not full_name.strip():
            raise InvalidInput("Please give the teacher's name.")
        if len(password or "") < MIN_PASSWORD_LENGTH:
            raise InvalidInput(f"Passwords must be at least {MIN_PASSWORD_LENGTH} characters.")
        ok, message = self.auth.register_user(username, password, full_name.strip(), [])
        if not ok:
            raise InvalidInput(message)
        self.conn.hset(f"user:{username}", "role", role)
        self.events.staff(actor, "staff_create_account", payload={"username": username, "role": role})
        return self._user(username)

    def update_user(self, actor: str, username: str, role: Optional[str] = None,
                    active: Optional[bool] = None, session_kind: Optional[str] = None) -> Dict:
        self._require_user(username)
        if session_kind is not None:
            if session_kind not in SESSION_KINDS:
                raise InvalidInput(f"Session kind must be one of: {', '.join(SESSION_KINDS)}.")
            self.conn.hset(f"user:{username}", "session_kind", session_kind)
            self.events.forget_kind(username)
            self.events.staff(actor, "staff_set_session_kind", payload={"username": username, "kind": session_kind})
        if role is not None:
            if role not in ROLES:
                raise InvalidInput(f"Role must be one of: {', '.join(ROLES)}.")
            if role != "admin":
                self._keep_an_admin(username)
            self.conn.hset(f"user:{username}", "role", role)
            self.events.staff(actor, "staff_set_role", payload={"username": username, "role": role})
        if active is not None:
            if not active:
                if username == actor:
                    raise InvalidInput("You can't deactivate your own account.")
                self._keep_an_admin(username)
            self.conn.hset(f"user:{username}", "is_active", "true" if active else "false")
            if not active:
                self.auth.tokens.revoke_all(username)  # signed out at once
            self.events.staff(actor, "staff_set_active", payload={"username": username, "active": active})
        return self._user(username)

    def add_course(self, actor: str, username: str, code: str) -> Dict:
        """Enroll any account in a course on their behalf (idempotent)."""
        self._require_user(username)
        code = self._available_code(code)
        self.auth.redis_client.add_user_course(username, code)
        self.events.staff(actor, "staff_add_course", course=code, payload={"username": username})
        return self._user(username)

    def remove_course(self, actor: str, username: str, code: str) -> Dict:
        """Un-enrol any account from a course. Progress isn't deleted, only the enrollment."""
        self._require_user(username)
        code = self._code(code)
        self.auth.redis_client.remove_user_course(username, code)
        self.events.staff(actor, "staff_remove_course", course=code, payload={"username": username})
        return self._user(username)

    def add_owner(self, actor: str, course: str, username: str) -> List[str]:
        code = self._code(course)
        self._require_user(username)
        if self.role(username) not in STAFF_ROLES:
            raise InvalidInput(f"{username} isn't a teacher. Make them a teacher first.")
        self.conn.sadd(owners_key(code), username)
        self.events.staff(actor, "staff_add_owner", course=code, payload={"username": username})
        return self.owners(code)

    def remove_owner(self, actor: str, course: str, username: str) -> List[str]:
        code = self._code(course)
        if not self.conn.srem(owners_key(code), username):
            raise NotFound(f"{username} doesn't own {code}.")
        self.events.staff(actor, "staff_remove_owner", course=code, payload={"username": username})
        return self.owners(code)

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _code(course: str) -> str:
        try:
            return valid_course_code(course)
        except ValueError:
            raise InvalidInput(f"Not a course code: {course}") from None

    def _available_code(self, course: str) -> str:
        code = self._code(course)
        if code not in self._available_courses():
            raise InvalidInput(f"Unknown course: {code}.")
        return code

    def _require_user(self, username: str) -> None:
        if not is_valid_username(username) or not self.conn.exists(f"user:{username}"):
            raise NotFound(f"No account called {username}.")

    def _user(self, username: str) -> Dict:
        return next(u for u in self.users() if u["username"] == username)

    def _keep_an_admin(self, username: str) -> None:
        """Refuse to demote or deactivate the last active admin."""
        if self.role(username) != "admin":
            return
        others = [u for u in self.users() if u["role"] == "admin" and u["active"] and u["username"] != username]
        if not others:
            raise InvalidInput("LEA needs at least one active admin. Make someone else an admin first.")
