"""Service errors as HTTP responses: ``{"detail": message, "code": error class}``."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.api.schemas import ErrorOut
from src.services import errors as e

logger = logging.getLogger(__name__)

STATUS = {
    e.InvalidInput: 400,
    e.NotAuthenticated: 401,
    e.NotEnrolled: 403,
    e.NotPermitted: 403,
    e.NotFound: 404,
    e.NoActiveSession: 404,
    e.WrongState: 409,
    e.Busy: 409,
    e.RateLimited: 429,
    e.Unavailable: 503,
}


def status_for(error: e.ServiceError) -> int:
    return next((code for cls, code in STATUS.items() if isinstance(error, cls)), 400)


def install(app: FastAPI) -> None:
    @app.exception_handler(e.ServiceError)
    async def service_error(request: Request, error: e.ServiceError):
        headers = {}
        if isinstance(error, e.NotAuthenticated):
            headers["WWW-Authenticate"] = "Bearer"
        if isinstance(error, e.RateLimited):
            headers["Retry-After"] = str(error.retry_after)
        return JSONResponse({"detail": str(error), "code": type(error).__name__},
                            status_code=status_for(error), headers=headers)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, error: RequestValidationError):
        problems = "; ".join(f"{'.'.join(str(p) for p in err['loc'][1:]) or 'body'}: {err['msg']}"
                             for err in error.errors())
        return JSONResponse({"detail": problems or "Invalid request.", "code": "ValidationError"}, status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, error: StarletteHTTPException):
        return JSONResponse({"detail": str(error.detail), "code": "HTTPError"}, status_code=error.status_code,
                            headers=getattr(error, "headers", None))


class CatchAll:
    """Turns unexpected exceptions into a JSON 500. Installed inside the CORS middleware,
    so a browser client can read the error instead of seeing a network failure."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        started = False

        async def tracking_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception:
            logger.exception("Unhandled error on %s %s", scope.get("method"), scope.get("path"))
            if started:
                raise
            response = JSONResponse({"detail": "Something went wrong. Please try again.", "code": "InternalError"},
                                    status_code=500)
            await response(scope, receive, send)


# Documented on every route, so generated clients know the error shape
ERROR_RESPONSES = {code: {"model": ErrorOut, "description": text} for code, text in [
    (400, "InvalidInput"), (401, "NotAuthenticated"), (403, "NotEnrolled or NotPermitted"),
    (404, "NoActiveSession or NotFound"),
    (409, "WrongState or Busy"), (422, "ValidationError"), (429, "RateLimited (see Retry-After)"),
    (503, "Unavailable"),
]}
