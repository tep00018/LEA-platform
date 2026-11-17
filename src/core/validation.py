"""Validation for identifiers that end up in file paths and Redis keys."""

from __future__ import annotations

import re

COURSE_CODE_PATTERN = re.compile(r"^[A-Z]{2,4}\d{3}[A-Z]?$")
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")


class InvalidIdentifier(ValueError):
    pass


def course_code(value: str) -> str:
    """Normalise and validate a course code such as ``AIML101`` or ``DEMO101``."""
    code = (value or "").strip().upper()
    if not COURSE_CODE_PATTERN.match(code):
        raise InvalidIdentifier(f"Invalid course code: {value!r}")
    return code


def is_valid_username(value: str) -> bool:
    return bool(USERNAME_PATTERN.match(value or ""))
