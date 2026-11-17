"""Request dependencies: the service container, the logged-in user, enrolment, roles, limits."""

from __future__ import annotations

from typing import Optional

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.core.validation import course_code as valid_course_code
from src.services.container import Services
from src.services.errors import InvalidInput, NotAuthenticated, NotEnrolled, RateLimited

bearer = HTTPBearer(auto_error=False, description="The token from POST /auth/login")

# Model-backed actions (chat, tutor replies, quiz questions) per minute: per user, and per
# address (enough for a class sharing one network, but it bounds throwaway accounts)
MODEL_CALLS_PER_MINUTE = 30
MODEL_CALLS_PER_IP_PER_MINUTE = 300


def services(request: Request) -> Services:
    return request.app.state.services


def token(credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer)) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        raise NotAuthenticated("Log in to continue.")
    return credentials.credentials


def current_user(tok: str = Depends(token), svc: Services = Depends(services)) -> str:
    """The username the token belongs to. Identity never comes from the request body."""
    return svc.accounts.authenticate(tok)


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def require_enrolled(username: str, course: str, svc: Services) -> str:
    try:
        course = valid_course_code(course)
    except ValueError:
        raise InvalidInput(f"Unknown course: {course}") from None
    if course not in svc.accounts.profile(username).enrolled_courses:
        raise NotEnrolled(f"You aren't enrolled in {course}.")
    return course


def require_week(course: str, week: int, svc: Services) -> None:
    if svc.courses.outline(course).week(week) is None:
        raise InvalidInput(f"{course} has no week {week}.")


def enrolled_course(code: str, user: str = Depends(current_user), svc: Services = Depends(services)) -> str:
    """Path parameter ``code``, checked against the user's enrolments."""
    return require_enrolled(user, code, svc)


def require_admin(user: str = Depends(current_user), svc: Services = Depends(services)) -> str:
    """The logged-in admin (403 for anyone else). Used on the whole /admin router, so it
    runs before the request body is read."""
    svc.staff.require_admin(user)
    return user


def require_staff(user: str = Depends(current_user), svc: Services = Depends(services)) -> str:
    """A logged-in teacher or admin (403 for students). Used on the whole /teach router."""
    svc.staff.require_staff(user)
    return user


def teacher_course(code: str, user: str = Depends(current_user), svc: Services = Depends(services)) -> str:
    """Path parameter ``code``, which the caller must own (or be an admin)."""
    return svc.staff.require_teacher(user, code)


def model_budget(request: Request, user: str = Depends(current_user), svc: Services = Depends(services)) -> str:
    """Counts one model-backed action against the per-minute allowances."""
    if svc.rate_limiter:
        for scope, key, limit in [("model", user, MODEL_CALLS_PER_MINUTE),
                                  ("model-ip", client_ip(request), MODEL_CALLS_PER_IP_PER_MINUTE)]:
            wait = svc.rate_limiter.hit(scope, key, limit, 60)
            if wait:
                raise RateLimited("You're going a bit fast. Try again in a moment.", wait)
    return user
