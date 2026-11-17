"""The FastAPI application."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import List, Optional

import anyio.to_thread
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api import errors
from src.api.routes import admin, auth, chat, courses, quiz, teach, tutor

logger = logging.getLogger(__name__)

# Any localhost port by default (the Flutter web dev server picks a random one)
DEFAULT_ORIGIN_REGEX = r"https?://(localhost|127\.0\.0\.1)(:\d+)?"
WORKER_THREADS = 100


def create_app(services=None, cors_origins: Optional[List[str]] = None, start_background_work: bool = True) -> FastAPI:
    """Build the API. Without ``services`` they are built at startup from the environment
    (``REDIS_URL``, ``OPENAI_API_KEY``). ``LEA_CORS_ORIGINS`` (comma-separated) adds
    allowed browser origins, e.g. the address the Flutter web app is served from."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Endpoints are synchronous and run on worker threads; model calls hold one for
        # seconds, so allow more than AnyIO's default 40 at once.
        anyio.to_thread.current_default_thread_limiter().total_tokens = WORKER_THREADS
        if getattr(app.state, "services", None) is None:
            from src.services.container import build_services

            app.state.services = build_services()
        if start_background_work:
            app.state.services.start_background_work(jobs=True)
        yield

    app = FastAPI(
        title="LEA API",
        version="0.3.0",
        description="Learning Engagement Assistant: chat, tutor and quiz modes over one adaptive "
                    "learner model. Authenticate with `POST /auth/login` and send the token as "
                    "`Authorization: Bearer <token>`.",
        lifespan=lifespan,
    )
    app.state.services = services

    origins = cors_origins if cors_origins is not None else [
        o.strip() for o in os.getenv("LEA_CORS_ORIGINS", "").split(",") if o.strip()]
    app.add_middleware(errors.CatchAll)  # added first, so it sits inside CORS
    app.add_middleware(
        CORSMiddleware, allow_origins=origins, allow_origin_regex=DEFAULT_ORIGIN_REGEX,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["Authorization", "Content-Type"],
        expose_headers=["Retry-After", "WWW-Authenticate"], allow_credentials=False,
    )
    errors.install(app)

    @app.get("/health", tags=["health"])
    def health():
        ok = False
        try:
            ok = bool(app.state.services.redis_client.get_redis().ping())
        except Exception as e:
            logger.error(f"Health check: Redis unreachable: {e}")
        return {"status": "ok" if ok else "degraded", "redis": ok}

    for module in (auth, courses, chat, quiz, tutor, teach, admin):
        app.include_router(module.router, responses=errors.ERROR_RESPONSES)
    return app
