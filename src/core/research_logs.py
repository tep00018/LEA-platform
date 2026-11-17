"""CSV logs of adaptive decisions, for research analysis.

Written under ``<data>/decision_logs`` and ``<data>/motivation_logs`` (both gitignored).
The column layouts are unchanged from the paper version, so existing analysis scripts
keep working. Writes are serialised with a process-wide lock because requests now run on
several threads.

With an event recorder (``src.services.events``), every decision is also written to the
durable event log, and test accounts (teacher previews, test logins) are left out of
these CSV files at write time.
"""

from __future__ import annotations

import csv
import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_WRITE_LOCK = threading.Lock()

COGNITIVE_COLUMNS = [
    "timestamp", "username", "course", "mode", "cognitive_load",
    "zpd_score", "motivation", "fatigue", "scaffolding_decision",
    "intervention_type", "difficulty_adjustment", "session_context",
]
SCAFFOLDING_COLUMNS = [
    "timestamp", "username", "course", "go_id", "cl_level",
    "zpd_level", "strategy_type", "intensity_level",
    "fade_threshold", "consecutive_correct", "was_faded",
]
MOTIVATION_DECISION_COLUMNS = [
    "timestamp", "username", "course", "mode", "motivation_state",
    "persistence_level", "affective_score", "performance_score",
    "session_completion_rate", "consecutive_correct", "consecutive_incorrect",
    "time_on_task", "help_seeking_frequency", "cognitive_load",
    "zpd_score", "motivation_score", "fatigue_level", "session_context",
]


def _append(path: Path, columns: list, row: list) -> None:
    with _WRITE_LOCK:
        new = not path.exists()
        with open(path, "a", newline="") as f:
            writer = csv.writer(f)
            if new:
                writer.writerow(columns)
            writer.writerow(row)


class DecisionLogger:
    """Cognitive-load, scaffolding and motivation decisions made by the orchestrator."""

    def __init__(self, data_dir: Optional[Path] = None, events=None):
        self.events = events
        if data_dir is None:
            from src.core.course_registry import default_registry
            data_dir = default_registry().data_dir
        self.log_dir = Path(data_dir) / "decision_logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def _skip_csv(self, kind: str, d: Dict[str, Any]) -> bool:
        """Send the decision to the event log; True if it must stay out of the CSV files."""
        if self.events is None:
            return False
        try:
            self.events.decision(kind, d)
            return self.events.is_test(d.get("username", ""))
        except Exception as e:
            logger.error(f"Event log for {kind} failed: {e}")
            return False

    def log_cognitive_decision(self, d: Dict[str, Any]) -> None:
        if self._skip_csv("cognitive_decision", d):
            return
        try:
            _append(self.log_dir / "cognitive_load_decisions.csv", COGNITIVE_COLUMNS, [
                datetime.now().isoformat(), d.get("username", "unknown"), d.get("course", "unknown"),
                d.get("mode", "unknown"), d.get("cognitive_load", 0.0), d.get("zpd_score", 0.0),
                d.get("motivation", 0.0), d.get("fatigue", 0.0), d.get("scaffolding_decision", "unknown"),
                d.get("intervention_type", "unknown"), d.get("difficulty_adjustment", "none"),
                json.dumps(d.get("session_context", {}), default=str),
            ])
        except Exception as e:
            logger.error(f"Error logging cognitive decision: {e}")

    def log_scaffolding_decision(self, d: Dict[str, Any]) -> None:
        if self._skip_csv("scaffolding_decision", d):
            return
        try:
            _append(self.log_dir / "scaffolding_decisions.csv", SCAFFOLDING_COLUMNS, [
                datetime.now().isoformat(), d.get("username", "unknown"), d.get("course", "unknown"),
                d.get("go_id", "unknown"), d.get("cl_level", "unknown"), d.get("zpd_level", "unknown"),
                d.get("strategy_type", "unknown"), d.get("intensity_level", "unknown"),
                d.get("fade_threshold", 0), d.get("consecutive_correct", 0), d.get("was_faded", False),
            ])
        except Exception as e:
            logger.error(f"Error logging scaffolding decision: {e}")

    def log_motivation_decision(self, d: Dict[str, Any]) -> None:
        if self._skip_csv("motivation_decision", d):
            return
        try:
            _append(self.log_dir / "motivation_decisions.csv", MOTIVATION_DECISION_COLUMNS, [
                datetime.now().isoformat(), d.get("username", "unknown"), d.get("course", "unknown"),
                d.get("mode", "unknown"), d.get("motivation_state", "unknown"),
                d.get("persistence_level", "unknown"), d.get("affective_score", 0.0),
                d.get("performance_score", 0.0), d.get("session_completion_rate", 0.0),
                d.get("consecutive_correct", 0), d.get("consecutive_incorrect", 0),
                d.get("time_on_task", 0.0), d.get("help_seeking_frequency", 0.0),
                d.get("cognitive_load", 0.0), d.get("zpd_score", 0.0), d.get("motivation_score", 0.0),
                d.get("fatigue_level", 0.0), json.dumps(d.get("session_context", {}), default=str),
            ])
        except Exception as e:
            logger.error(f"Error logging motivation decision: {e}")


MOTIVATION_METRIC_COLUMNS = [
    "timestamp", "username", "course", "week", "mode", "motivation_state",
    "persistence_level", "affective_score", "performance_score", "session_completion_rate",
    "consecutive_correct", "consecutive_incorrect", "time_on_task", "help_seeking_frequency",
    "cognitive_load", "zpd_score", "motivation_score", "fatigue_level",
]


def log_motivation_metrics(snapshot: Dict[str, Any], username: str, course: str, week: int, mode: str,
                           data_dir: Optional[Path] = None) -> None:
    """One row per assessed interaction in ``motivation_logs/motivation_metrics_YYYYMM.csv``.

    ``snapshot`` is a learner-state snapshot (see ``src.services.models.LearnerState``).
    """
    try:
        if data_dir is None:
            from src.core.course_registry import default_registry
            data_dir = default_registry().data_dir
        log_dir = Path(data_dir) / "motivation_logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        metrics = snapshot.get("motivation_metrics") or {}
        cognitive = snapshot.get("cognitive_state") or {}
        _append(log_dir / f"motivation_metrics_{datetime.now().strftime('%Y%m')}.csv", MOTIVATION_METRIC_COLUMNS, [
            datetime.now().isoformat(), username, course, week, mode,
            snapshot.get("motivation_state", "unknown"),
            metrics.get("persistence_level", "unknown"), metrics.get("affective_score", 0.0),
            metrics.get("performance_score", 0.0), metrics.get("session_completion_rate", 0.0),
            metrics.get("consecutive_correct", 0), metrics.get("consecutive_incorrect", 0),
            metrics.get("time_on_task", 0.0), metrics.get("help_seeking_frequency", 0.0),
            cognitive.get("cognitive_load", 0.0), cognitive.get("zpd_score", 0.0),
            cognitive.get("motivation_score", 0.0), cognitive.get("fatigue_level", 0.0),
        ])
    except Exception as e:
        logger.error(f"Failed to log motivation metrics: {e}")
