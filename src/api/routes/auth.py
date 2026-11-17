"""Accounts and login."""

from fastapi import APIRouter, Depends, Request, Response, status

from src.api import deps
from src.api.schemas import CourseEnrollIn, CourseOut, LoginIn, LoginOut, MessageOut, RegisterIn
from src.auth.tokens import IDLE_SECONDS
from src.services.container import Services
from src.services.errors import InvalidInput, RateLimited
from src.services.models import UserProfile

router = APIRouter(tags=["auth"])

# Per client address: failed logins per 15 minutes, registrations per hour. Generous,
# because a whole class can share one address (school network); guessing a password is
# stopped by the per-username limits in AccountService.
FAILED_LOGINS_PER_IP = 100
REGISTRATIONS_PER_IP = 60


def _limit(svc: Services, scope: str, key: str, limit: int, window: int, message: str) -> None:
    if svc.rate_limiter:
        wait = svc.rate_limiter.hit(scope, key, limit, window)
        if wait:
            raise RateLimited(message, wait)


@router.post("/auth/register", status_code=status.HTTP_201_CREATED, response_model=MessageOut)
def register(body: RegisterIn, request: Request, svc: Services = Depends(deps.services)):
    _limit(svc, "register-ip", deps.client_ip(request), REGISTRATIONS_PER_IP, 3600,
           "Too many new accounts from this device. Try again later.")
    message = svc.accounts.register(body.username, body.full_name, body.password, body.password, body.courses)
    return MessageOut(message=message)


@router.post("/auth/login", response_model=LoginOut)
def login(body: LoginIn, request: Request, svc: Services = Depends(deps.services)):
    ip = deps.client_ip(request)
    if svc.rate_limiter:
        wait = svc.rate_limiter.blocked("login-fail-ip", ip, FAILED_LOGINS_PER_IP, 15 * 60)
        if wait:
            raise RateLimited("Too many failed logins from this device. Try again later.", wait)
    try:
        profile, token = svc.accounts.login(body.username, body.password, address=ip)
    except InvalidInput:
        if svc.rate_limiter:
            svc.rate_limiter.hit("login-fail-ip", ip, FAILED_LOGINS_PER_IP, 15 * 60)
        raise
    return LoginOut(token=token, expires_in=IDLE_SECONDS, user=profile)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(token: str = Depends(deps.token), svc: Services = Depends(deps.services)):
    svc.accounts.logout(token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserProfile)
def me(user: str = Depends(deps.current_user), svc: Services = Depends(deps.services)):
    return svc.accounts.profile(user)


@router.get("/courses", response_model=list[CourseOut], tags=["courses"])
def available_courses(svc: Services = Depends(deps.services)):
    """Courses a new account can enrol in (no login needed)."""
    return [CourseOut(code=c, name=svc.registry.profile(c).display_name) for c in svc.courses.available()]


@router.get("/me/courses", response_model=list[CourseOut], tags=["courses"])
def my_courses(user: str = Depends(deps.current_user), svc: Services = Depends(deps.services)):
    return [CourseOut(code=c, name=svc.registry.profile(c).display_name)
            for c in svc.accounts.profile(user).enrolled_courses]


@router.post("/me/courses", response_model=list[CourseOut], status_code=201, tags=["courses"])
def add_my_course(body: CourseEnrollIn, user: str = Depends(deps.current_user), svc: Services = Depends(deps.services)):
    """Enroll yourself in one more course, from GET /courses. Idempotent."""
    profile = svc.accounts.add_course(user, body.code)
    return [CourseOut(code=c, name=svc.registry.profile(c).display_name) for c in profile.enrolled_courses]


@router.delete("/me/courses/{code}", response_model=list[CourseOut], tags=["courses"])
def remove_my_course(code: str, user: str = Depends(deps.current_user), svc: Services = Depends(deps.services)):
    """Un-enrol yourself from a course. Your progress in it isn't deleted."""
    profile = svc.accounts.remove_course(user, code)
    return [CourseOut(code=c, name=svc.registry.profile(c).display_name) for c in profile.enrolled_courses]
