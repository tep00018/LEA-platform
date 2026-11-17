"""Keeping secrets out of error messages and logs.

A failed Google API call raises an error whose text is the full request URL, API key
included (``<HttpError 429 when requesting https://...&key=AIza...>``). LEA returned that
text to callers and logged it. ``redact()`` removes keys, tokens and URL passwords from
any text; ``install_log_redaction()`` applies it to every log record in the process, so a
secret that reaches a log call by any route is cleaned before a handler sees it.

Patterns (applied in order, each replaced with ``<redacted>``):

- query parameters that carry secrets: ``?key=``, ``&api_key=``, ``access_token=``,
  ``token=``, ``client_secret=``
- Google API keys (``AIza...``) and OpenAI/Anthropic-style keys (``sk-...``) anywhere
- ``Bearer`` / ``Basic`` authorisation values
- the password in a URL with credentials (``redis://user:password@host``)
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

REDACTED = "<redacted>"

_PATTERNS = (
    (re.compile(r"(?i)([?&](?:key|api[_-]?key|access[_-]?token|token|client[_-]?secret)=)[^&\s'\"<>)]+"),
     r"\1" + REDACTED),
    (re.compile(r"AIza[0-9A-Za-z_\-]{20,}"), REDACTED),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}"), REDACTED),
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=\-]{20,}"), r"\1 " + REDACTED),
    (re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)[^/\s:@]*:[^/\s@]+@"), r"\1" + REDACTED + "@"),
)


def redact(text: Any) -> str:
    """``text`` with secrets removed. Safe to call on anything; idempotent."""
    out = str(text)
    for pattern, replacement in _PATTERNS:
        out = pattern.sub(replacement, out)
    return out


_previous_factory: Optional[Any] = None


def install_log_redaction() -> None:
    """Clean every log record (message and traceback) in this process. Idempotent."""
    global _previous_factory
    if _previous_factory is not None:
        return
    _previous_factory = logging.getLogRecordFactory()
    previous = _previous_factory
    formatter = logging.Formatter()

    def factory(*args, **kwargs):
        record = previous(*args, **kwargs)
        try:
            message = record.getMessage()
            cleaned = redact(message)
            if cleaned != message:
                record.msg, record.args = cleaned, None
            if record.exc_info and record.exc_info[0] is not None and not record.exc_text:
                text = formatter.formatException(record.exc_info)
                cleaned_text = redact(text)
                if cleaned_text != text:
                    record.exc_text = cleaned_text
        except Exception:  # logging must never be the thing that fails
            pass
        return record

    logging.setLogRecordFactory(factory)


def uninstall_log_redaction() -> None:
    """Put the previous record factory back (for tests)."""
    global _previous_factory
    if _previous_factory is not None:
        logging.setLogRecordFactory(_previous_factory)
        _previous_factory = None
