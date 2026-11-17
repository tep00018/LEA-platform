"""A read-only source of course materials outside LEA's own uploads.

Today there is one implementation, a local folder under ``LEA_COURSE_MATERIALS_ROOT``
(default ``~/Documents/LEA/course_materials``, one subfolder per course
code). The ``MaterialsSource`` interface (``list_files`` / ``read_bytes`` / ``fingerprint``)
is deliberately small so a connector to an existing system (Canvas, Moodle, SharePoint,
Google Drive) can be added later without changing the Teacher screens or the Build
pipeline -- see ``src/services/course_setup.py``'s ``sync_materials_source``, which
reconciles a source's current files into the course's normal uploads
(``course:{code}:uploads``); everything past that point (pricing, Build, embedding) is the
existing, unchanged upload pipeline.

A course records its link as ``{"type": "folder", "path": "<subpath under the root>"}`` on
its profile (``CourseProfile.materials_source``).

Folder source rules: read-only; the linked path must resolve inside the root (no ``..``, no
absolute path, no symlink -- file or directory -- leading outside it); the same file types
and size limits as uploads (``src/onboarding/files.py``); anything inside a folder whose
name starts with ``_`` (e.g. ``_teacher``), and any hidden file or folder, is never even
offered as a candidate -- not listed, not rejected, simply invisible, exactly like it
doesn't exist for ingestion purposes.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from src.onboarding import files as F

DEFAULT_ROOT = str(Path.home() / "Documents" / "LEA" / "course_materials")


def materials_root() -> Path:
    return Path(os.getenv("LEA_COURSE_MATERIALS_ROOT") or DEFAULT_ROOT)


def _inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


@dataclass(frozen=True)
class MaterialsFile:
    """One file a source offers, at its path relative to the source's own subfolder."""

    relpath: str
    size: int
    sha256: str


@dataclass(frozen=True)
class RejectedFile:
    relpath: str
    reason: str


class MaterialsSource:
    """A read-only, external source of course files. One implementation today
    (``FolderMaterialsSource``); a future connector implements the same three methods."""

    def list_files(self) -> List[MaterialsFile]:
        raise NotImplementedError

    def rejected_files(self) -> List[RejectedFile]:
        """Candidate files that exist but weren't offered by ``list_files()``, with why."""
        raise NotImplementedError

    def read_bytes(self, relpath: str) -> bytes:
        raise NotImplementedError

    def fingerprint(self, relpath: str) -> str:
        """A stable identifier for a file's current contents (its sha256)."""
        raise NotImplementedError


class FolderSourceError(ValueError):
    """The folder path itself is invalid (missing, traversal, escape) -- not a per-file issue."""


class FolderMaterialsSource(MaterialsSource):
    """A read-only local folder under the course materials root."""

    def __init__(self, subpath: str, root: Optional[Path] = None):
        self.root = (root or materials_root()).resolve()
        clean = (subpath or "").strip().strip("/\\")
        if not clean or Path(clean).is_absolute() or ".." in Path(clean).parts:
            raise FolderSourceError("Choose a folder under the materials root.")
        candidate = self.root / clean
        try:
            resolved = candidate.resolve()
        except OSError:
            raise FolderSourceError("That folder can't be read.") from None
        if not _inside(resolved, self.root):
            raise FolderSourceError("That folder is outside the materials root.")
        if not resolved.is_dir():
            raise FolderSourceError(f"No folder called {clean} under the materials root.")
        self.subpath = clean
        self.path = resolved
        self._scanned = False
        self._files: List[MaterialsFile] = []
        self._rejected: List[RejectedFile] = []

    def _scan(self) -> None:
        if self._scanned:
            return
        total = 0
        for dirpath, dirnames, filenames in os.walk(self.path, followlinks=False):
            dirnames[:] = [d for d in sorted(dirnames) if not d.startswith(".") and not d.startswith("_")]
            for filename in sorted(filenames):
                if filename.startswith(".") or filename.startswith("_"):
                    continue
                full = Path(dirpath) / filename
                rel = full.relative_to(self.path).as_posix()
                if full.is_symlink():
                    try:
                        target = full.resolve()
                    except OSError:
                        self._rejected.append(RejectedFile(rel, "a broken link"))
                        continue
                    if not _inside(target, self.root):
                        self._rejected.append(RejectedFile(rel, "a link outside the materials root"))
                        continue
                ext = full.suffix.lower()
                if ext not in F.ALLOWED:
                    self._rejected.append(RejectedFile(rel, "not a file type LEA accepts"))
                    continue
                try:
                    size = full.stat().st_size
                except OSError:
                    self._rejected.append(RejectedFile(rel, "can't be read"))
                    continue
                if size == 0:
                    self._rejected.append(RejectedFile(rel, "empty file"))
                    continue
                if size > F.MAX_FILE_BYTES:
                    self._rejected.append(RejectedFile(rel, f"over {F.MAX_FILE_BYTES // (1024 * 1024)} MB"))
                    continue
                if total + size > F.MAX_COURSE_BYTES:
                    self._rejected.append(RejectedFile(
                        rel, f"would take the course over its {F.MAX_COURSE_BYTES // (1024 ** 3)} GB limit"))
                    continue
                total += size
                digest = hashlib.sha256()
                with open(full, "rb") as f:
                    while chunk := f.read(1024 * 1024):
                        digest.update(chunk)
                self._files.append(MaterialsFile(relpath=rel, size=size, sha256=digest.hexdigest()))
        self._scanned = True

    def list_files(self) -> List[MaterialsFile]:
        self._scan()
        return list(self._files)

    def rejected_files(self) -> List[RejectedFile]:
        self._scan()
        return list(self._rejected)

    def read_bytes(self, relpath: str) -> bytes:
        full = (self.path / relpath).resolve()
        if not _inside(full, self.path):
            raise FolderSourceError("That file is outside the linked folder.")
        return full.read_bytes()

    def fingerprint(self, relpath: str) -> str:
        for f in self.list_files():
            if f.relpath == relpath:
                return f.sha256
        raise FileNotFoundError(relpath)


def available_subfolders(root: Optional[Path] = None) -> List[str]:
    """Top-level subfolder names under the materials root, sorted -- for the Teacher UI's
    folder picker. Hidden and ``_``-prefixed folders are never offered as link targets."""
    root = root or materials_root()
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith((".", "_")))
