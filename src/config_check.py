"""Startup configuration check with messages that say exactly what to fix."""

from __future__ import annotations

import os
from typing import Optional

from src.logging_config import redact


def check_configuration(redis_url: Optional[str] = None, openai_key: Optional[str] = None) -> list[str]:
    """Return a list of problems (empty when LEA can start)."""
    problems: list[str] = []
    openai_key = openai_key if openai_key is not None else os.getenv("OPENAI_API_KEY", "")
    redis_url = redis_url if redis_url is not None else os.getenv("REDIS_URL", "")

    if not openai_key or openai_key.startswith("sk-your"):
        problems.append("OPENAI_API_KEY is not set. Add your OpenAI API key to the .env file.")

    if not redis_url:
        problems.append("REDIS_URL is not set. Add your Redis address to the .env file, "
                        "for example redis://default:PASSWORD@HOST:PORT.")
    else:
        try:
            import redis

            redis.from_url(redis_url, socket_connect_timeout=5, socket_timeout=5).ping()
        except Exception as e:
            name = type(e).__name__
            hint = {
                "AuthenticationError": "the password in REDIS_URL is wrong",
                "TimeoutError": "the host or port in REDIS_URL is wrong, or the database is unreachable",
                "ConnectionError": "the host or port in REDIS_URL is wrong, the database was deleted, "
                                   "or TLS is required (try rediss:// instead of redis://)",
            }.get(name, "check REDIS_URL")
            problems.append(f"Cannot connect to Redis at {redact(redis_url)}: {hint} ({name}).")
    return problems
