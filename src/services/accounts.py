"""Registration and login."""

from __future__ import annotations

from typing import List, Optional, Tuple

from src.services.errors import InvalidInput, NotAuthenticated, RateLimited
from src.services.events import EventRecorder, disabled
from src.services.models import UserProfile

MIN_PASSWORD_LENGTH = 6
# Login attempts allowed in LOGIN_WINDOW seconds before a username is paused: per
# username and address, and (higher, so one device can't lock a student out) per username
# from anywhere. A successful login clears the counters.
LOGIN_ATTEMPTS = 5
LOGIN_ATTEMPTS_ANY_ADDRESS = 50
LOGIN_WINDOW = 15 * 60


class AccountService:
    def __init__(self, auth_service, available_courses, rate_limiter=None, events: Optional[EventRecorder] = None):
        self.auth = auth_service
        self._available_courses = available_courses
        self.limiter = rate_limiter
        self.events = events or disabled()

    def register(self, username: str, full_name: str, password: str, confirm_password: str,
                 courses: List[str]) -> str:
        """Create an account; returns the confirmation message or raises InvalidInput."""
        if not all([username, full_name, password, confirm_password]):
            raise InvalidInput("Please fill in all fields.")
        if password != confirm_password or len(password) < MIN_PASSWORD_LENGTH:
            raise InvalidInput(f"Password must be at least {MIN_PASSWORD_LENGTH} characters and passwords must match.")
        if not courses:
            raise InvalidInput("Please select at least one course.")
        unknown = [c for c in courses if c not in self._available_courses()]
        if unknown:
            raise InvalidInput(f"Unknown course: {', '.join(unknown)}")
        ok, message = self.auth.register_user(username, password, full_name, courses)
        if not ok:
            raise InvalidInput(message)
        return "Account created. Open the Login tab to sign in."

    def login(self, username: str, password: str, address: str = "local") -> Tuple[UserProfile, str]:
        """Check credentials; returns the profile and a login token, or raises InvalidInput.

        Every attempt is counted before the password is checked (so parallel guesses can't
        slip past the limit); over the limit, RateLimited until the window ends.
        """
        if not username or not password:
            raise InvalidInput("Please enter username and password.")
        limits = [("login", f"{username}|{address}", LOGIN_ATTEMPTS),
                  ("login-any", username, LOGIN_ATTEMPTS_ANY_ADDRESS)]
        if self.limiter:
            for scope, key, limit in limits:
                wait = self.limiter.hit(scope, key, limit, LOGIN_WINDOW)
                if wait:
                    raise RateLimited(f"Too many login attempts. Try again in {wait // 60 + 1} minutes.", wait)
        ok, token, message = self.auth.login_user(username, password)
        if not ok:
            raise InvalidInput(message)
        if self.limiter:
            for scope, key, _ in limits:
                self.limiter.reset(scope, key, LOGIN_WINDOW)
        return self.profile(username), token

    def authenticate(self, token: str) -> str:
        """The username a login token belongs to (renewing it), or NotAuthenticated."""
        username = self.auth.validate_session(token)
        if not username:
            raise NotAuthenticated("Please log in again.")
        return username

    def logout(self, token: str) -> None:
        self.auth.logout(token)

    def add_course(self, username: str, code: str) -> UserProfile:
        """Self-service enrollment in one more course (idempotent)."""
        if code not in self._available_courses():
            raise InvalidInput(f"Unknown course: {code}.")
        self.auth.redis_client.add_user_course(username, code)
        self.events.staff(username, "course_self_enroll", course=code)
        return self.profile(username)

    def remove_course(self, username: str, code: str) -> UserProfile:
        """Self-service un-enrollment. Progress isn't deleted, only the enrollment."""
        self.auth.redis_client.remove_user_course(username, code)
        self.events.staff(username, "course_self_unenroll", course=code)
        return self.profile(username)

    def profile(self, username: str) -> UserProfile:
        data = self.auth.get_user_data(username) or {}
        full_name, role = "", None
        try:
            conn = self.auth.redis_client.get_redis()
            full_name, role = conn.hmget(f"user:{username}", ["full_name", "role"])
        except Exception:
            pass
        return UserProfile(username=username, full_name=full_name or "",
                           enrolled_courses=list(data.get("enrolled_courses", [])),
                           role=role if role in ("student", "teacher", "admin") else "student")
