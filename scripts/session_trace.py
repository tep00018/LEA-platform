"""Print a readable, turn-by-turn trace of one learner's tutor and quiz activity in one
course -- for testing LEA by hand, not a report or an export.

    python scripts/session_trace.py <username> DEMO101
    python scripts/session_trace.py <username> DEMO101 --week 1

For each turn: time, mode, the tutor's recorded question or the quiz question, your reply,
whether it was graded and correct, cognitive load, ZPD, support level, motivation state, and
that objective's mastery. Reads only the durable event log (LEA_EVENTS_DB, or
data/lea_events.db) and, as a fallback when a turn's own snapshot is missing something, the
decision-log CSVs under <data>/decision_logs/. Never calls a model.

Two things this can't show, because LEA doesn't keep them: a test account's turns (see
scripts/manage_account.py set-kind) never reach the decision-log CSVs, only the event log,
so this always reads the event log first; and GO mastery has no historical record, only the
mastery tracker's CURRENT stored value (Redis mastery:<username>:<course>) -- shown against
the last turn that touched each objective, not a true per-turn snapshot.
Uses REDIS_URL, LEA_EVENT_SALT and LEA_EVENTS_DB (optional) from .env.
"""

import argparse
import csv
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

from src.services.events import EventRecorder  # noqa: E402
from src.storage.event_log import EventLog  # noqa: E402
from src.storage.redis_client import LEARedisClient  # noqa: E402


def _load_decision_csvs(data_dir: Optional[Path], username: str) -> Dict[str, List[Dict[str, str]]]:
    """Rows for this username from each decision-log CSV, oldest first. Empty (not an
    error) for a test account, since those never reach the CSVs -- see the module docstring."""
    out: Dict[str, List[Dict[str, str]]] = {}
    for name in ("cognitive_load_decisions", "scaffolding_decisions", "motivation_decisions"):
        path = data_dir / "decision_logs" / f"{name}.csv" if data_dir else None
        rows: List[Dict[str, str]] = []
        if path is not None and path.exists():
            with open(path, newline="", encoding="utf-8") as f:
                rows = [r for r in csv.DictReader(f) if r.get("username") == username]
        out[name] = rows
    return out


def _nearest_at_or_before(rows: List[Dict[str, str]], ts: str) -> Optional[Dict[str, str]]:
    candidates = [r for r in rows if r.get("timestamp", "") <= ts]
    return candidates[-1] if candidates else None


def _support_from_scaffolding_strategy(value: Any) -> Optional[str]:
    """``learner_state``'s scaffolding_strategy can be a plain string or a dict (the
    orchestrator's own adaptive-context shape); handle either."""
    if isinstance(value, str) and value:
        return value
    if isinstance(value, dict):
        strategy = value.get("strategy_type") or value.get("type") or value.get("strategy")
        intensity = value.get("intensity_level") or value.get("intensity")
        if strategy and intensity:
            return f"{strategy}/{intensity}"
        if strategy:
            return strategy
    return None


def _go_mastery(conn, username: str, course: str) -> Dict[str, Optional[float]]:
    try:
        raw = conn.get(f"mastery:{username}:{course}")
        data = json.loads(raw) if raw else {}
    except Exception:
        return {}
    levels = {}
    for go_id, value in (data.get("go_masteries") or {}).items():
        levels[go_id] = value.get("level") if isinstance(value, dict) else value
    return levels


def build_trace(log: EventLog, recorder: EventRecorder, username: str, course: str,
                data_dir: Optional[Path], week: Optional[int] = None) -> List[Dict[str, Any]]:
    username_hash = recorder.pseudonym(username)
    rows = log.query("username_hash = ? AND course = ?", (username_hash, course))
    if week is not None:
        rows = [r for r in rows if r.get("week") in (week, None)]
    decisions = _load_decision_csvs(data_dir, username)

    turns: List[Dict[str, Any]] = []
    state: Optional[Dict[str, Any]] = None
    go_ids_touched: List[str] = []
    for row in rows:
        payload = json.loads(row["payload_json"]) if row["payload_json"] else {}
        if row["type"] == "learner_state":
            state = payload
            continue
        if row["type"] not in ("answer",):
            continue

        cognitive = (state or {}).get("cognitive_state") or {}
        cognitive_load = cognitive.get("cognitive_load")
        zpd = cognitive.get("zpd_score")
        motivation_state = (state or {}).get("motivation_state")
        support = None
        if row["mode"] == "tutor" and payload.get("scaffolding_strategy"):
            support = _support_from_scaffolding_strategy(payload.get("scaffolding_strategy"))
            if support and payload.get("scaffolding_intensity"):
                support = f"{payload['scaffolding_strategy']}/{payload['scaffolding_intensity']}"
        if support is None:
            support = _support_from_scaffolding_strategy((state or {}).get("scaffolding_strategy"))

        if cognitive_load is None or zpd is None:
            nearest = _nearest_at_or_before(decisions["cognitive_load_decisions"], row["ts"])
            if nearest:
                cognitive_load = cognitive_load if cognitive_load is not None else nearest.get("cognitive_load")
                zpd = zpd if zpd is not None else nearest.get("zpd_score")
        if support is None:
            nearest = _nearest_at_or_before(decisions["scaffolding_decisions"], row["ts"])
            if nearest and nearest.get("strategy_type"):
                support = f"{nearest['strategy_type']}/{nearest.get('intensity_level', '?')}"
        if motivation_state is None:
            nearest = _nearest_at_or_before(decisions["motivation_decisions"], row["ts"])
            if nearest:
                motivation_state = nearest.get("motivation_state")

        question = (payload.get("recorded_question") if row["mode"] == "tutor" else payload.get("question")) or ""
        go_id = row.get("go_id")
        if go_id:
            go_ids_touched.append(go_id)
        turns.append({
            "ts": row["ts"], "mode": row["mode"], "go_id": go_id, "question": question,
            "reply": payload.get("response", ""), "graded": bool(payload.get("graded")),
            "correct": None if row["correct"] is None else bool(row["correct"]),
            "cognitive_load": cognitive_load, "zpd": zpd, "support": support,
            "motivation_state": motivation_state,
        })
    return turns


def _fmt(value: Any, digits: int = 2) -> str:
    if value is None or value == "":
        return "-"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def print_trace(turns: List[Dict[str, Any]], mastery: Dict[str, Optional[float]]) -> None:
    if not turns:
        print("No tutor or quiz turns found for this learner and course.")
        return
    for t in turns:
        graded = "graded" if t["graded"] else "not graded"
        correct = "-" if t["correct"] is None else ("correct" if t["correct"] else "incorrect")
        print(f"\n[{t['ts']}] {t['mode'].upper()}" + (f"  GO {t['go_id']}" if t["go_id"] else ""))
        if t["question"]:
            print(f"  Question:   {t['question']}")
        print(f"  Reply:      {t['reply']}")
        print(f"  Result:     {graded}, {correct}")
        print(f"  Cog. load:  {_fmt(t['cognitive_load'])}   ZPD: {_fmt(t['zpd'])}   "
              f"Support: {t['support'] or '-'}   Motivation: {t['motivation_state'] or '-'}")
        if t["go_id"] in mastery:
            print(f"  {t['go_id']} mastery (now): {_fmt(mastery[t['go_id']])}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("username")
    parser.add_argument("course")
    parser.add_argument("--week", type=int, help="Only turns in this week")
    args = parser.parse_args(argv)

    # Student replies and tutor questions are free text and can carry characters outside the
    # Windows console's default codepage (curly quotes, non-breaking hyphens); never crash a
    # trace over that.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    load_dotenv(ROOT / ".env")
    salt = os.getenv("LEA_EVENT_SALT")
    if not salt:
        print("LEA_EVENT_SALT is not set in .env, so learners can't be matched to their events.")
        return 1
    events_path = os.getenv("LEA_EVENTS_DB") or str(ROOT / "data" / "lea_events.db")
    if not Path(events_path).exists():
        print(f"No event log at {events_path}")
        return 1
    client = LEARedisClient()
    conn = client.get_redis()
    if conn is None:
        print("Can't reach Redis: check REDIS_URL in .env")
        return 1
    log = EventLog(events_path)
    recorder = EventRecorder(log, salt, client)
    data_dir = Path(os.getenv("LEA_DATA_DIR") or ROOT / "data")

    turns = build_trace(log, recorder, args.username, args.course, data_dir, week=args.week)
    mastery = _go_mastery(conn, args.username, args.course)
    print_trace(turns, mastery)
    log.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
