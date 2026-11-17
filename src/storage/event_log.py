"""Durable, append-only event log in SQLite (``data/lea_events.db``, gitignored).

Redis keeps only each learner's recent evidence; this log keeps every event, for research
and (later) teacher analytics. Learners appear only as a salted hash of their username
(see ``src.services.events``); staff actions carry the actor's real username because they
are an audit trail.

The API and Streamlit are separate processes that both write here, so writes rely on
SQLite's own locking (WAL mode, a busy timeout) as well as a lock inside each process.
Back the log up by copying the file (see docs/SETUP.md). Nothing is ever updated or
deleted.
"""

from __future__ import annotations

import csv
import json
import logging
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional

logger = logging.getLogger(__name__)

SESSION_KINDS = ("real", "test", "simulated")
MODES = ("quiz", "tutor", "chat", "admin")

COLUMNS = [
    "id", "ts", "course", "kc_version", "username_hash", "actor", "session_kind", "mode",
    "type", "go_id", "lo_id", "week", "correct", "score", "question_type", "payload_json",
]

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT NOT NULL,
    course        TEXT,
    kc_version    TEXT,
    username_hash TEXT,
    actor         TEXT,
    session_kind  TEXT NOT NULL CHECK (session_kind IN {SESSION_KINDS}),
    mode          TEXT CHECK (mode IS NULL OR mode IN {MODES}),
    type          TEXT NOT NULL,
    go_id         TEXT,
    lo_id         TEXT,
    week          INTEGER,
    correct       INTEGER CHECK (correct IS NULL OR correct IN (0, 1)),
    score         REAL,
    question_type TEXT,
    payload_json  TEXT
);
CREATE INDEX IF NOT EXISTS events_course_kind_type ON events (course, session_kind, type);
CREATE INDEX IF NOT EXISTS events_learner ON events (username_hash, course);
CREATE INDEX IF NOT EXISTS events_go ON events (course, go_id);
"""


class EventLog:
    """One SQLite file. ``append`` never raises: a logging failure must not break a
    student's turn, so it is logged and counted in ``failed_writes`` instead."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.failed_writes = 0
        self._conn = self._connect()
        with self._lock:
            self._conn.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10, check_same_thread=False, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def append(self, *, type: str, session_kind: str, course: Optional[str] = None,
               kc_version: Optional[str] = None, username_hash: Optional[str] = None,
               actor: Optional[str] = None, mode: Optional[str] = None, go_id: Optional[str] = None,
               lo_id: Optional[str] = None, week: Optional[int] = None, correct: Optional[bool] = None,
               score: Optional[float] = None, question_type: Optional[str] = None,
               payload: Optional[Dict[str, Any]] = None, ts: Optional[str] = None) -> bool:
        row = (
            ts or datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            course, kc_version, username_hash, actor, session_kind, mode, type, go_id, lo_id,
            week, None if correct is None else int(bool(correct)),
            None if score is None else float(score), question_type,
            json.dumps(payload, default=str, ensure_ascii=False) if payload else None,
        )
        try:
            with self._lock:
                self._conn.execute(
                    "INSERT INTO events (ts, course, kc_version, username_hash, actor, session_kind, mode,"
                    " type, go_id, lo_id, week, correct, score, question_type, payload_json)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", row)
            return True
        except Exception as e:
            self.failed_writes += 1
            logger.error(f"Event log write failed ({type}): {e}")
            return False

    def query(self, where: str = "", params: Iterable[Any] = ()) -> List[Dict[str, Any]]:
        """Rows as dicts, oldest first. ``where`` is a trusted SQL fragment (code only)."""
        sql = "SELECT * FROM events" + (f" WHERE {where}" if where else "") + " ORDER BY id"
        with self._lock:
            cursor = self._conn.execute(sql, tuple(params))
            names = [c[0] for c in cursor.description]
            return [dict(zip(names, r)) for r in cursor.fetchall()]

    def iter_rows(self, where: str = "", params: Iterable[Any] = ()) -> Iterator[Dict[str, Any]]:
        """Like ``query`` but streamed from a separate connection, for large exports."""
        sql = "SELECT * FROM events" + (f" WHERE {where}" if where else "") + " ORDER BY id"
        conn = sqlite3.connect(self.path, timeout=10)
        try:
            cursor = conn.execute(sql, tuple(params))
            names = [c[0] for c in cursor.description]
            for r in cursor:
                yield dict(zip(names, r))
        finally:
            conn.close()

    def export_csv(self, out: Path | str, *, kinds: Iterable[str] = ("real",),
                   learners: Optional[Iterable[str]] = None, course: Optional[str] = None) -> int:
        """Write a research export and return the number of rows.

        Only ``kinds`` are included (``test`` never is, whatever is asked), and learner
        events only for the hashes in ``learners`` when given (consented learners). Staff
        audit events (``actor`` set) are never exported.
        """
        kinds = [k for k in kinds if k in SESSION_KINDS and k != "test"]
        if not kinds:
            raise ValueError("Nothing to export: choose real and/or simulated sessions.")
        clauses = [f"session_kind IN ({', '.join('?' for _ in kinds)})", "actor IS NULL"]
        params: List[Any] = list(kinds)
        if course:
            clauses.append("course = ?")
            params.append(course)
        allowed = None if learners is None else set(learners)
        count = 0
        with open(out, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([c for c in COLUMNS if c != "actor"])
            for row in self.iter_rows(" AND ".join(clauses), params):
                if allowed is not None and row["username_hash"] not in allowed:
                    continue
                writer.writerow([row[c] for c in COLUMNS if c != "actor"])
                count += 1
        return count

    def export_staff_csv(self, out: Path | str, pseudonym, *, course: Optional[str] = None) -> int:
        """Write teacher and admin actions (``actor`` set) for a study of how LEA is used
        to teach. Actors, and any username in a payload (``username``/``account`` fields,
        or an actor's name inside other text, such as ``<teacher>.preview``), are replaced by
        ``pseudonym(name)``. Learner events are never included. Returns the number of rows."""
        clauses, params = ["actor IS NOT NULL"], []
        if course:
            clauses.append("course = ?")
            params.append(course)
        where = " AND ".join(clauses)
        actors = {r["actor"] for r in self.iter_rows(where, params)} - {"system"}

        def scrub(value: Any) -> Any:
            if isinstance(value, dict):
                return {k: (pseudonym(v) if k in ("username", "account") and isinstance(v, str) and v != "system"
                            else scrub(v)) for k, v in value.items()}
            if isinstance(value, list):
                return [scrub(v) for v in value]
            if isinstance(value, str):
                for name in sorted(actors, key=len, reverse=True):
                    if name in value:
                        value = re.sub(rf"(?<![\w.]){re.escape(name)}(?![\w])", pseudonym(name), value)
            return value

        count = 0
        with open(out, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["ts", "course", "kc_version", "actor", "type", "payload_json"])
            for row in self.iter_rows(where, params):
                actor = row["actor"] if row["actor"] == "system" else pseudonym(row["actor"])
                payload = scrub(json.loads(row["payload_json"] or "{}"))
                writer.writerow([row["ts"], row["course"], row["kc_version"], actor, row["type"],
                                 json.dumps(payload, ensure_ascii=False)])
                count += 1
        return count

    def close(self) -> None:
        with self._lock:
            self._conn.close()
