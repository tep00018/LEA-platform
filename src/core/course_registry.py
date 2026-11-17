"""Course profiles and course discovery.

A course profile records the facts about a course that the rest of LEA must not guess,
such as whether code questions make sense for it. Profiles live in
``data/course_profiles/<CODE>.json``:

```json
{
  "code": "AIML101",
  "name": "Introduction to AI and Machine Learning (open course)",
  "discipline": "computing",
  "allows_code": false,
  "code_language": "python"
}
```

A course without a profile gets conservative defaults (no code questions) and a warning
in the log, so a new course can never inherit another course's assumptions.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from src.core.validation import InvalidIdentifier, course_code as validate_course_code

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class CourseProfile:
    code: str
    name: str = ""
    discipline: str = "unspecified"
    allows_code: bool = False
    code_language: Optional[str] = None
    from_file: bool = False
    # {"type": "folder", "path": "<subpath under LEA_COURSE_MATERIALS_ROOT>"}, or None if the
    # course has no linked materials source (see src/onboarding/materials_source.py).
    materials_source: Optional[dict[str, Any]] = None
    extra: dict[str, Any] = field(default_factory=dict, compare=False, hash=False)

    @property
    def display_name(self) -> str:
        return f"{self.code}: {self.name}" if self.name else self.code


class CourseRegistry:
    def __init__(self, data_dir: str | Path = "data"):
        self.data_dir = Path(data_dir)
        self.profiles_dir = self.data_dir / "course_profiles"
        self.kc_models_dir = self.data_dir / "kc_models"
        self.chroma_dir = self.data_dir / "chroma_data"
        self._kc_cache: dict[str, dict[str, Any]] = {}
        self._kc_versions: dict[str, str] = {}
        self._kc_mtimes: dict[str, float] = {}
        self._profile_cache: dict[str, CourseProfile] = {}

    # -- profiles ---------------------------------------------------------------------

    def profile(self, code: str) -> CourseProfile:
        code = validate_course_code(code)
        if code in self._profile_cache:
            return self._profile_cache[code]

        path = self.profiles_dir / f"{code}.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            known = {"code", "name", "discipline", "allows_code", "code_language", "materials_source"}
            profile = CourseProfile(
                code=code,
                name=data.get("name", ""),
                discipline=data.get("discipline", "unspecified"),
                allows_code=bool(data.get("allows_code", False)),
                code_language=data.get("code_language") if data.get("allows_code") else None,
                from_file=True,
                materials_source=data.get("materials_source"),
                extra={k: v for k, v in data.items() if k not in known},
            )
        else:
            kc = self.kc_model(code) or {}
            name = kc.get("course_info", {}).get("course_name", "")
            logger.warning(
                f"No course profile for {code} ({path}); using defaults with code questions disabled."
            )
            profile = CourseProfile(code=code, name=name)
        self._profile_cache[code] = profile
        return profile

    # -- KC models --------------------------------------------------------------------

    def kc_model_path(self, code: str) -> Path:
        code = validate_course_code(code)
        return self.kc_models_dir / code / f"kc_model_{code}.json"

    def kc_model(self, code: str) -> Optional[dict[str, Any]]:
        """The course's KC model, or None if it has not been onboarded. Reloaded when the
        file changes, so every process (API, Streamlit) sees a newly published version."""
        try:
            path = self.kc_model_path(code)
        except InvalidIdentifier:
            return None
        key = path.parent.name
        try:
            mtime = path.stat().st_mtime
        except OSError:
            self._kc_cache.pop(key, None)
            return None
        if key not in self._kc_cache or self._kc_mtimes.get(key) != mtime:
            self._kc_mtimes[key] = mtime
            raw = path.read_bytes()
            self._kc_cache[key] = json.loads(raw.decode("utf-8"))
            self._kc_versions[key] = hashlib.sha256(raw).hexdigest()[:12]
        return self._kc_cache[key]

    def forget(self, code: str) -> None:
        """Drop the cached profile and KC model of a course (after a teacher changes them)."""
        code = validate_course_code(code)
        self._profile_cache.pop(code, None)
        self._kc_cache.pop(code, None)
        self._kc_versions.pop(code, None)

    def kc_version(self, code: str) -> Optional[str]:
        """A short fingerprint of the KC model in use (a hash of its file), recorded with
        each event so evidence can be tied to the model it was collected under."""
        if self.kc_model(code) is None:
            return None
        return self._kc_versions.get(validate_course_code(code))

    # -- discovery --------------------------------------------------------------------

    def available_courses(self) -> list[str]:
        """Courses with a KC model on disk, sorted."""
        if not self.kc_models_dir.exists():
            return []
        codes = []
        for folder in self.kc_models_dir.iterdir():
            if folder.is_dir() and (folder / f"kc_model_{folder.name}.json").exists():
                codes.append(folder.name)
        return sorted(codes)

    def vector_store_path(self, code: str) -> Path:
        return self.chroma_dir / validate_course_code(code)

    def has_vector_store(self, code: str) -> bool:
        try:
            return (self.vector_store_path(code) / "chroma.sqlite3").exists()
        except InvalidIdentifier:
            return False


@lru_cache(maxsize=4)
def default_registry(data_dir: Optional[str] = None) -> CourseRegistry:
    """Registry rooted at LEA_DATA_DIR, or the repository's data/ folder."""
    return CourseRegistry(data_dir or os.getenv("LEA_DATA_DIR") or PROJECT_ROOT / "data")
