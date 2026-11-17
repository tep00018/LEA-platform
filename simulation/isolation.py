"""Keeping a simulation run away from real data (docs/simulation/PLAN.md, principle 3).

``RunContext`` gives a run its own folder under ``simulation/runs/<run_id>/`` with:

- ``data/``: a copy of the AIML101 course data (Chroma rewrites its files when queried),
  which LEA uses through ``LEA_DATA_DIR``, so decision and motivation CSVs, mastery files
  and the vector store all land in the run folder;
- ``lea_events.db``: the run's own event log (``LEA_EVENTS_DB``, a per-run salt);
- ``claude_cwd/``: an empty working directory for ``claude -p``.

While the context is active:

- ``REDIS_URL`` points at an in-process fakeredis server, and any real Redis connection
  (from any URL, including the one in ``.env``) raises ``IsolationError``;
- any attempt to write under the repository's ``data/`` folder raises ``IsolationError``
  (a Python audit hook watches file opens, renames, deletes, directory changes and
  SQLite connections);
- ``YOUTUBE_API_KEY`` is set to empty, so LEA's YouTube search is off (it falls back to
  plain search links, exactly as in its own tests). Without this, a struggling simulated
  learner made hundreds of real YouTube searches with the researcher's key, exhausted its daily
  quota, and the key appeared in a logged error URL. ``dotenv`` never overrides a variable
  that is already set, but LEA's ``redis_client`` module reads ``.env`` straight into the environment
  when first imported and does override; the context imports it first, then applies these settings.

Everything is restored on exit. Nothing here changes LEA's code.
"""

from __future__ import annotations

import os
import secrets
import shutil
import sys
import threading
from pathlib import Path
from typing import Dict, Optional

import fakeredis
import redis
import redis.connection

from simulation import REPO_ROOT, RUNS_DIR

REAL_DATA = REPO_ROOT / "data"
FAKE_REDIS_URL = "redis://simulation-fakeredis.invalid:6379/0"

# Course files a run needs, relative to data/.
COURSE_TREES = ("kc_models/{c}", "chroma_data/{c}", "md_docs/{c}")
COURSE_FILES = ("course_profiles/{c}.json", "metadata/doc_metadata_{c}.json")


class IsolationError(RuntimeError):
    """A simulation run tried to reach real Redis or write under data/."""


# ---------------------------------------------------------------------------- write guard

_guard_lock = threading.Lock()
_protected: list[Path] = []
_hook_installed = False
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND


def _under_protected(path) -> Optional[Path]:
    if not _protected or path is None or isinstance(path, int):
        return None
    try:
        full = Path(os.path.abspath(os.fsdecode(path)))
    except (TypeError, ValueError):
        return None
    for root in _protected:
        if full == root or root in full.parents:
            return root
    return None


def _audit(event: str, args) -> None:
    if not _protected:
        return
    if event == "open":
        path, mode, flags = (list(args) + [None, None, None])[:3]
        writing = (isinstance(mode, str) and any(ch in mode for ch in "wax+")) or \
                  (isinstance(flags, int) and flags & _WRITE_FLAGS and mode is None)
        if writing and _under_protected(path):
            raise IsolationError(f"Simulation tried to write under data/: {path}")
    elif event in ("os.rename", "os.replace", "shutil.move", "shutil.copyfile", "shutil.copytree"):
        if len(args) > 1 and _under_protected(args[1]):
            raise IsolationError(f"Simulation tried to write under data/: {args[1]}")
    elif event in ("os.remove", "os.rmdir", "os.mkdir", "os.truncate", "os.chmod", "shutil.rmtree"):
        if args and _under_protected(args[0]):
            raise IsolationError(f"Simulation tried to change data/: {args[0]}")
    elif event == "sqlite3.connect":
        if args and _under_protected(args[0]):
            raise IsolationError(f"Simulation tried to open a database under data/: {args[0]}")


def _install_hook() -> None:
    global _hook_installed
    if not _hook_installed:
        sys.addaudithook(_audit)  # can't be removed; inactive while nothing is protected
        _hook_installed = True


# ---------------------------------------------------------------------------- Redis guard

def _refuse(self, *args, **kwargs):
    raise IsolationError("Simulation tried to connect to a real Redis server; runs use fakeredis only.")


_REAL_CONNECT = {cls: cls.__dict__["_connect"] for cls in
                 (redis.connection.Connection, redis.connection.SSLConnection,
                  redis.connection.UnixDomainSocketConnection) if "_connect" in cls.__dict__}


# ---------------------------------------------------------------------------- the context

def copy_course(course: str, target: Path, source: Path = REAL_DATA) -> None:
    """Copy one course's data (read-only on the source) into ``target``."""
    for tree in COURSE_TREES:
        rel = tree.format(c=course)
        shutil.copytree(source / rel, target / rel)
    for name in COURSE_FILES:
        rel = name.format(c=course)
        (target / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / rel, target / rel)


class RunContext:
    """A run folder plus the guards; use as a context manager."""

    def __init__(self, run_id: str, course: str = "AIML101", runs_dir: Path = RUNS_DIR,
                 source_data: Path = REAL_DATA, protect: Optional[list[Path]] = None, extra_env: Optional[Dict[str, str]] = None):
        if not run_id or any(ch in run_id for ch in r"\/:*?\"<>|") or run_id.startswith("."):
            raise ValueError("A run id is a plain folder name")
        self.run_id = run_id
        self.course = course
        self.dir = Path(runs_dir) / run_id
        self.data_dir = self.dir / "data"
        self.claude_cwd = self.dir / "claude_cwd"
        self.events_db = self.dir / "lea_events.db"
        self.source_data = Path(source_data)
        self.protect = [Path(p).resolve() for p in (protect or [REAL_DATA])]
        self.redis_url = FAKE_REDIS_URL
        self.extra_env = dict(extra_env or {})
        self.fake_server = fakeredis.FakeServer()
        self._saved_env: Dict[str, Optional[str]] = {}
        self._saved_from_url = None
        self._active = False

    # -- setup
    def prepare(self) -> "RunContext":
        """Create the folder and copy the course data (only once; a resumed run keeps it)."""
        self.dir.mkdir(parents=True, exist_ok=True)
        self.claude_cwd.mkdir(exist_ok=True)
        if not self.data_dir.exists():
            staging = self.dir / "data.partial"
            if staging.exists():
                shutil.rmtree(staging)
            copy_course(self.course, staging, self.source_data)
            staging.rename(self.data_dir)
        return self

    def salt(self) -> str:
        path = self.dir / "event_salt"
        if not path.exists():
            path.write_text(secrets.token_hex(32), encoding="utf-8")
        return path.read_text(encoding="utf-8").strip()

    # -- activation
    def __enter__(self) -> "RunContext":
        from src.core.course_registry import default_registry

        self.prepare()
        # LEA's redis_client module reads .env into os.environ, overriding what is already set, the first
        # time it is imported. Import it now, before the run's settings are applied, so a later import
        # (building the services) can't bring a real key or Redis URL back inside the run.
        import src.storage.redis_client  # noqa: F401

        env = {"REDIS_URL": self.redis_url, "LEA_DATA_DIR": str(self.data_dir),
               "LEA_EVENTS_DB": str(self.events_db), "LEA_EVENT_SALT": self.salt(), "YOUTUBE_API_KEY": "",
               **self.extra_env}
        for key, value in env.items():
            self._saved_env[key] = os.environ.get(key)
            os.environ[key] = value

        server = self.fake_server
        original = redis.Redis.from_url.__func__
        self._saved_from_url = redis.Redis.__dict__["from_url"]

        def from_url(cls, url, **kwargs):
            if str(url).startswith(FAKE_REDIS_URL):
                return fakeredis.FakeRedis(server=server, decode_responses=kwargs.get("decode_responses", False))
            return original(cls, url, **kwargs)  # real URLs get a client whose connections are refused

        redis.Redis.from_url = classmethod(from_url)
        for cls in _REAL_CONNECT:
            cls._connect = _refuse
        with _guard_lock:
            _install_hook()
            _protected.extend(self.protect)
        default_registry.cache_clear()
        self._active = True
        return self

    def __exit__(self, *exc) -> None:
        from src.core.course_registry import default_registry

        with _guard_lock:
            for root in self.protect:
                if root in _protected:
                    _protected.remove(root)
        for cls, fn in _REAL_CONNECT.items():
            cls._connect = fn
        if self._saved_from_url is not None:
            redis.Redis.from_url = self._saved_from_url
        for key, value in self._saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        default_registry.cache_clear()
        self._active = False

    # -- checkpoints of LEA's state (fakeredis lives in memory)
    def dump_redis(self) -> Dict[str, list]:
        """Every key in the run's fakeredis as (DUMP payload, TTL in ms), base64-encoded."""
        import base64

        conn = fakeredis.FakeRedis(server=self.fake_server)
        out = {}
        for key in conn.keys("*"):
            payload = conn.dump(key)
            if payload is not None:
                out[base64.b64encode(key).decode()] = [base64.b64encode(payload).decode(), conn.pttl(key)]
        return out

    def restore_redis(self, dumped: Dict[str, list]) -> None:
        import base64

        conn = fakeredis.FakeRedis(server=self.fake_server)
        conn.flushall()
        for key, (payload, ttl) in dumped.items():
            conn.restore(base64.b64decode(key), ttl if ttl and ttl > 0 else 0, base64.b64decode(payload))

