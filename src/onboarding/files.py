"""Upload rules: which files a teacher may upload, safe names, and LEA's staged names.

Checks are by extension *and* content (the first bytes), so a renamed file is refused.
Limits: 50 MB per file, 1 GB per course.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional, Tuple

MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_COURSE_BYTES = 1024 * 1024 * 1024

DOCUMENTS = {".pdf", ".docx", ".pptx", ".xlsx", ".md", ".txt", ".ipynb"}
MEDIA = {".mp3", ".mp4", ".wav"}
ALLOWED = DOCUMENTS | MEDIA

# What the material is; it becomes part of the staged name, which ingestion reads.
KINDS = ("Lecture", "Lab", "Reading", "Assignment", "Transcript", "Video", "Audio", "Other")
DEFAULT_KIND = {".pptx": "Lecture", ".pdf": "Reading", ".docx": "Reading", ".md": "Reading", ".txt": "Reading",
                ".xlsx": "Other", ".ipynb": "Lab", ".mp4": "Video", ".mp3": "Audio", ".wav": "Audio"}

_ZIP = b"PK\x03\x04"


class UploadRejected(ValueError):
    """The file can't be accepted; the message says why, for the teacher."""


def safe_name(name: str) -> str:
    """A file name safe to store: no folders, only letters, digits and ``._-()`` (others
    become ``-``), at most 120 characters, keeping the extension."""
    base = Path((name or "").replace("\\", "/")).name.strip()
    stem, ext = Path(base).stem, Path(base).suffix.lower()
    stem = re.sub(r"[^A-Za-z0-9._() -]", "-", stem).strip(" .-")
    stem = re.sub(r"\s+", " ", stem)[: 120 - len(ext)]
    if not stem or ext not in ALLOWED:
        raise UploadRejected(f"{name or 'This file'}: LEA takes PDF, Word, PowerPoint, Excel, Markdown, text, "
                             "notebook, MP3, MP4 and WAV files.")
    return stem + ext


def check_content(name: str, head: bytes) -> None:
    """Refuse a file whose first bytes don't match its extension."""
    ext = Path(name).suffix.lower()
    ok = {
        ".pdf": head.startswith(b"%PDF"),
        ".docx": head.startswith(_ZIP), ".pptx": head.startswith(_ZIP), ".xlsx": head.startswith(_ZIP),
        ".mp3": head.startswith(b"ID3") or (len(head) > 1 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0),
        ".wav": head.startswith(b"RIFF") and head[8:12] == b"WAVE",
        ".mp4": head[4:8] == b"ftyp",
    }.get(ext)
    if ok is None:  # text formats: must be UTF-8 text
        try:
            head.decode("utf-8")
        except UnicodeDecodeError as e:
            if e.start < len(head) - 4:  # not just a character cut off at the end of the sample
                raise UploadRejected(f"{name}: this isn't a UTF-8 text file.") from None
        if b"\x00" in head:
            raise UploadRejected(f"{name}: this isn't a text file.")
    elif not ok:
        raise UploadRejected(f"{name}: the contents don't look like a {ext[1:].upper()} file.")


_KIND_WORDS = "|".join(k.lower() for k in KINDS)
# A name that already starts "Week03", "Week03-Lecture" or "Week03-LectureA", then a separator.
_WEEK_PREFIX = re.compile(rf"^week[\s_-]*(\d{{1,2}})(?:[\s_.-]+({_KIND_WORDS})[a-z]?(?=[\s_.-]|$))?[\s_.-]*", re.I)


def infer_week_kind(name: str) -> Tuple[Optional[int], Optional[str]]:
    """The week (and kind) a file name states, as in ``Week03-Lecture-Backprop.pptx``; ``(None, None)`` if it
    states neither. Used for files in a linked folder, which have no upload form to choose them in."""
    match = _WEEK_PREFIX.match(Path(name).stem)
    if not match:
        return None, None
    kind = next((k for k in KINDS if k.lower() == (match.group(2) or "").lower()), None)
    return int(match.group(1)), kind


def staged_name(week: Optional[int], kind: str, letter: str, name: str) -> str:
    """LEA's ingestion name, ``WeekNN-KindX-Title.ext`` (week 0 when unassigned). A file name that already
    starts with its week and kind is not given them twice."""
    stem, ext = Path(name).stem, Path(name).suffix.lower()
    stem = _WEEK_PREFIX.sub("", stem, count=1) or stem
    title = "-".join(w[:1].upper() + w[1:] for w in re.split(r"[\s_.()-]+", stem) if w)[:80] or "Untitled"
    return f"Week{week or 0:02d}-{kind}{letter}-{title}{ext}"
