"""Central logging setup for LEA.

Library modules only create loggers (``logging.getLogger(__name__)``); the entry
point calls :func:`setup_logging` once. Level comes from the ``LOG_LEVEL``
environment variable (default ``INFO``). Set ``LOG_LEVEL=DEBUG`` to see the
detailed trace the code used to print unconditionally.
"""

import logging
import os
import re

_CONFIGURED = False

# Patterns that must never reach a log line in clear text.
_SECRET_PATTERNS = [
    (re.compile(r"sk-[A-Za-z0-9_\-]{8,}"), "sk-***"),                  # OpenAI keys
    (re.compile(r"AIza[0-9A-Za-z_\-]{20,}"), "AIza***"),               # Google API keys
    (re.compile(r"(rediss?://[^:@/\s]*:)[^@/\s]+@"), r"\1***@"),       # password in Redis URLs
]


def redact(text: str) -> str:
    """Mask API keys and credentials embedded in ``text``."""
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def setup_logging(level: str | None = None) -> None:
    """Configure the ``src`` logger hierarchy once per process."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    level_name = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    handler = logging.StreamHandler()
    handler.setFormatter(RedactingFormatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S"))
    root = logging.getLogger("src")
    root.handlers[:] = [handler]
    root.setLevel(getattr(logging, level_name, logging.INFO))
    root.propagate = False
    _CONFIGURED = True
