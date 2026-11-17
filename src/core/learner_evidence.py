"""Graded-response evidence: the input to ZPD, accuracy and scaffolding fading.

Every graded answer (Quiz) or evaluated response (Tutor) is appended to a per-learner,
per-course list in Redis. The papers define ZPD as the mean accuracy across the
learner's last four responses; :func:`accuracy` implements exactly that over graded
entries. Responses the system could not grade are stored with ``correct=None`` and are
ignored by every calculation.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

ZPD_WINDOW = 4          # responses in the ZPD / accuracy window (papers: n = 4)
MAX_STORED = 50         # evidence kept per learner and course


def _conn(redis_client):
    return redis_client.get_redis() if hasattr(redis_client, "get_redis") else redis_client


class LearnerEvidence:
    def __init__(self, redis_client):
        self.redis_client = redis_client

    @staticmethod
    def key(username: str, course: str) -> str:
        return f"evidence:{username}:{course}"

    def record(
        self,
        username: str,
        course: str,
        *,
        mode: str,
        go_id: Optional[str],
        correct: Optional[bool],
        score: Optional[float],
        lo_id: Optional[str] = None,
        question_type: Optional[str] = None,
        weight: Optional[float] = None,
    ) -> dict[str, Any]:
        entry = {
            "ts": time.time(),
            "mode": mode,
            "go_id": go_id,
            "lo_id": lo_id,
            "correct": None if correct is None else bool(correct),
            "score": None if score is None else max(0.0, min(1.0, float(score))),
            "question_type": question_type,
        }
        if weight is not None:  # how much the grader stood behind this verdict (load-led scaffolding only)
            entry["weight"] = max(0.0, min(1.0, float(weight)))
        conn = _conn(self.redis_client)
        key = self.key(username, course)
        pipe = conn.pipeline()
        pipe.rpush(key, json.dumps(entry))
        pipe.ltrim(key, -MAX_STORED, -1)
        pipe.execute()
        return entry

    def recent(self, username: str, course: str, n: int = MAX_STORED) -> list[dict[str, Any]]:
        """Most recent ``n`` entries, oldest first."""
        try:
            raw = _conn(self.redis_client).lrange(self.key(username, course), -n, -1)
        except Exception as e:  # evidence is advisory; never break a turn over it
            logger.warning(f"Could not read learner evidence: {e}")
            return []
        entries = []
        for item in raw:
            try:
                entries.append(json.loads(item))
            except (TypeError, ValueError):
                continue
        return entries


def graded(entries: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in entries if e.get("correct") is not None]


def accuracy(entries: Iterable[dict[str, Any]], window: int = ZPD_WINDOW) -> Optional[float]:
    """Mean correctness of the last ``window`` graded entries, or None if there are none."""
    last = graded(entries)[-window:]
    if not last:
        return None
    return sum(1.0 for e in last if e["correct"]) / len(last)


def correctness_sequence(entries: Iterable[dict[str, Any]], lo_id: Optional[str] = None) -> list[bool]:
    """Graded correctness, oldest first, optionally restricted to one learning objective."""
    return [bool(e["correct"]) for e in graded(entries) if lo_id is None or e.get("lo_id") == lo_id]


def trailing_run(sequence: list[bool]) -> tuple[int, int]:
    """(consecutive correct, consecutive incorrect) counted back from the latest entry."""
    correct = incorrect = 0
    for value in reversed(sequence):
        if value and incorrect == 0:
            correct += 1
        elif not value and correct == 0:
            incorrect += 1
        else:
            break
    return correct, incorrect
