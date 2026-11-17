"""Student analytics from the event log (B6), as pure functions over event rows.

Only aggregates leave here, and any figure drawn from fewer than ``MIN_STUDENTS``
students is withheld (``None``, with ``suppressed``). Definitions (LEA's own, shown to
teachers as such):

- a student's *graded attempts* at an objective are their ``answer`` events on it with a
  ``correct`` value (the tutor's ungraded warm-up doesn't count), in time order;
- their *mastery estimate* is the mean score of their last three graded attempts; they have
  *mastered* it at or above the objective's threshold and are *struggling* 0.25 or more
  below it (students with fewer than two graded attempts aren't counted);
- the class *band*: mastered if 60% or more of the counted students mastered it, struggling
  if 40% or more struggle, otherwise developing; *not enough evidence* under 5 students;
- *first-attempt accuracy*: the share of students right on their first graded attempt;
- *attempts to master*: among students who reached mastery, the mean number of graded
  attempts until they first did;
- the *learning curve*: error rate at each practice opportunity (1st, 2nd, ... graded
  attempt), each point from at least 5 students; its *verdict* compares the first two
  opportunities with the later ones.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Optional, Tuple

MIN_STUDENTS = 5
LAST_N = 3
STRUGGLE_GAP = 0.25


def _payload(row: Dict[str, Any]) -> Dict[str, Any]:
    raw = row.get("payload_json")
    try:
        return json.loads(raw) if raw else {}
    except ValueError:
        return {}


def _score(row: Dict[str, Any]) -> float:
    if row.get("score") is not None:
        return float(row["score"])
    return float(row["correct"] or 0)


def graded_attempts(rows: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
    """go_id -> learner -> their graded answer events in order."""
    out: Dict[str, Dict[str, List[Dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if r["type"] == "answer" and r.get("go_id") and r.get("correct") is not None:
            out[r["go_id"]][r["username_hash"]].append(r)
    return out


def _band(estimates: List[Tuple[float, float]]) -> Optional[str]:
    """estimates: (mastery estimate, threshold) per counted student."""
    if len(estimates) < MIN_STUDENTS:
        return None
    mastered = sum(1 for m, t in estimates if m >= t) / len(estimates)
    struggling = sum(1 for m, t in estimates if m <= t - STRUGGLE_GAP) / len(estimates)
    if mastered >= 0.6:
        return "mastered"
    if struggling >= 0.4:
        return "struggling"
    return "developing"


def curve(by_learner: Dict[str, List[Dict[str, Any]]], max_opportunities: int = 10) -> List[Dict[str, Any]]:
    points = []
    for k in range(max_opportunities):
        outcomes = [attempts[k]["correct"] for attempts in by_learner.values() if len(attempts) > k]
        if not outcomes:
            break
        n = len(outcomes)
        points.append({"opportunity": k + 1, "students": n,
                       "error_rate": round(1 - sum(outcomes) / n, 3) if n >= MIN_STUDENTS else None})
    return points


def course_curve(by_go: Dict[str, Dict[str, List[Dict[str, Any]]]], max_opportunities: int = 10) -> List[Dict[str, Any]]:
    """The course's typical curve: every student's attempts on every objective, pooled by
    opportunity. A point is shown when at least 5 different students contribute to it."""
    points = []
    for k in range(max_opportunities):
        outcomes, learners = [], set()
        for by_learner in by_go.values():
            for learner, attempts in by_learner.items():
                if len(attempts) > k:
                    outcomes.append(attempts[k]["correct"])
                    learners.add(learner)
        if not outcomes:
            break
        points.append({"opportunity": k + 1, "students": len(learners),
                       "error_rate": round(1 - sum(outcomes) / len(outcomes), 3)
                       if len(learners) >= MIN_STUDENTS else None})
    return points


def verdict(points: List[Dict[str, Any]]) -> Optional[str]:
    """flat / declining / rising, from the shown points (None if too few)."""
    shown = [p["error_rate"] for p in points if p["error_rate"] is not None]
    if len(shown) < 3:
        return None
    early, late = sum(shown[:2]) / 2, sum(shown[2:]) / len(shown[2:])
    if late > early + 0.05:
        return "rising"
    if early - late < 0.1:
        return "flat"
    return "declining"


def objective_stats(go: Dict[str, Any], by_learner: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    threshold = float(go.get("mastery_threshold", 0.75))
    counted = {h: a for h, a in by_learner.items() if len(a) >= 2}
    estimates = []
    to_master = []
    for attempts in counted.values():
        scores = [_score(a) for a in attempts]
        estimates.append((sum(scores[-LAST_N:]) / len(scores[-LAST_N:]), threshold))
        for i in range(len(scores)):
            window = scores[max(0, i - LAST_N + 1): i + 1]
            if i >= 1 and sum(window) / len(window) >= threshold:
                to_master.append(i + 1)
                break
    students = len(by_learner)
    firsts = [a[0]["correct"] for a in by_learner.values() if a]
    enough = students >= MIN_STUDENTS
    points = curve(by_learner)
    return {
        "go_id": go["go_id"], "skill_name": go.get("skill_name", ""), "threshold": threshold,
        "students": students if enough else None, "suppressed": not enough,
        "graded_attempts": sum(len(a) for a in by_learner.values()) if enough else None,
        "band": _band(estimates) or "insufficient",
        "first_attempt_accuracy": round(sum(firsts) / len(firsts), 3) if enough else None,
        "attempts_to_master": round(sum(to_master) / len(to_master), 1) if len(to_master) >= MIN_STUDENTS else None,
        "curve": points, "curve_verdict": verdict(points),
    }


def struggle(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Per objective: students with 3+ wrong tutor replies in a row, shown video help, and
    tutor sessions that ended on it without moving on."""
    streak: Dict[str, set] = defaultdict(set)
    video: Dict[str, set] = defaultdict(set)
    last_turn: Dict[str, Tuple[str, bool]] = {}
    for r in rows:
        if r["type"] != "answer" or r.get("mode") != "tutor" or not r.get("go_id"):
            continue
        p = _payload(r)
        if (p.get("consecutive_incorrect") or 0) >= 3:
            streak[r["go_id"]].add(r["username_hash"])
        if p.get("youtube_shown"):
            video[r["go_id"]].add(r["username_hash"])
        if p.get("session_id"):
            last_turn[p["session_id"]] = (r["go_id"], bool(p.get("advanced")))
    stuck: Counter = Counter()
    ended = {(_payload(r).get("session_id")) for r in rows if r["type"] == "tutor_end"}
    for session, (go_id, advanced) in last_turn.items():
        if session in ended and not advanced:
            stuck[go_id] += 1
    out = {}
    for go_id in set(streak) | set(video) | set(stuck):
        out[go_id] = {"streak_students": len(streak[go_id]), "video_students": len(video[go_id]),
                      "sessions_left_stuck": stuck[go_id]}
    return out


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().rstrip(".").lower()


def wrong_answers(by_learner: Dict[str, List[Dict[str, Any]]], top: int = 3) -> Dict[str, Any]:
    """The most common wrong quiz answers for an objective (multiple choice and true/false,
    by the option chosen; short answers by their text). Quiz questions are written for
    each student, so this groups by objective, not by question."""
    counts: Counter = Counter()
    students_wrong: set = set()
    examples: Dict[str, str] = {}
    for learner, attempts in by_learner.items():
        for a in attempts:
            if a.get("mode") != "quiz" or a["correct"]:
                continue
            p = _payload(a)
            answer = str(p.get("response", ""))
            options = p.get("options") or []
            letter = re.match(r"^\s*([A-Da-d])(?:[).:\s]|$)", answer)
            if letter and options:
                index = "ABCD".index(letter.group(1).upper())
                answer = options[index] if index < len(options) else answer
                answer = re.sub(r"^[A-D][).:]\s*", "", str(answer))
            key = _normalise(answer)[:120]
            if not key or len(key) > 120:
                continue
            counts[key] += 1
            students_wrong.add(learner)
            examples.setdefault(key, answer.strip()[:160])
    total = sum(counts.values())
    if len(students_wrong) < MIN_STUDENTS or not total:
        return {"suppressed": True, "students": None, "answers": []}
    return {"suppressed": False, "students": len(students_wrong), "answers": [
        {"answer": examples[k], "share": round(n / total, 3), "count": n} for k, n in counts.most_common(top)]}


def attention(stats: Dict[str, Any], strug: Optional[Dict[str, Any]], chat_students: int = 0) -> Dict[str, Any]:
    """LEA's "needs attention" heuristic: low first-attempt accuracy, a flat or rising
    curve, tutor struggles and chat questions on the topic, with the factor that drove it."""
    if stats["suppressed"]:
        return {"score": None, "level": None, "driver": None}
    n = stats["students"] or 1
    factors = {
        "low first-attempt accuracy": max(0.0, 0.7 - (stats["first_attempt_accuracy"] or 0)) / 0.7,
        "a flat learning curve": {"flat": 0.8, "rising": 1.0}.get(stats["curve_verdict"] or "", 0.0),
        "tutor struggles": min(1.0, (strug or {}).get("streak_students", 0) / n * 2),
        "many chat questions": min(1.0, chat_students / n * 2),
    }
    weights = {"low first-attempt accuracy": 0.35, "a flat learning curve": 0.3, "tutor struggles": 0.2,
               "many chat questions": 0.15}
    score = sum(factors[k] * weights[k] for k in factors)
    driver = max(factors, key=lambda k: factors[k] * weights[k])
    level = "high" if score >= 0.45 else ("medium" if score >= 0.25 else "low")
    return {"score": round(score, 3), "level": level, "driver": driver if factors[driver] > 0 else None,
            "factors": {k: round(v, 2) for k, v in factors.items()}}


def suggestion(stats: Dict[str, Any], att: Dict[str, Any], strug: Optional[Dict[str, Any]],
               source: Optional[str]) -> Optional[str]:
    """A drafted note for the teacher (a suggestion, never applied by LEA)."""
    if att.get("level") not in ("high", "medium"):
        return None
    driver = att.get("driver")
    where = f" Revisit {source}, where it's taught." if source else ""
    if driver == "a flat learning curve":
        if (stats.get("first_attempt_accuracy") or 1) < 0.5:
            return ("Errors aren't falling with practice and most students miss it the first time: consider "
                    "splitting it into smaller objectives, or adding a worked example." + where)
        return "Errors aren't falling with practice: add a worked example that shows each step." + where
    if driver == "low first-attempt accuracy":
        return "Most students miss it the first time: check the prerequisite is taught first, or add an example." + where
    if driver == "tutor struggles":
        return "Students get stuck with the tutor here: a clearer explanation or a short video may help." + where
    if driver == "many chat questions":
        return "Students ask about this a lot in Chat: answer the common question in the lecture." + where
    return None


def usage(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    learners = {r["username_hash"] for r in rows if r.get("username_hash")}
    starts = [r for r in rows if r["type"] in ("quiz_start", "tutor_start")]
    chats = [r for r in rows if r["type"] == "chat_question"]
    minutes = 0.0
    open_: Dict[str, str] = {}
    from datetime import datetime

    for r in rows:
        p = _payload(r)
        sid = p.get("session_id") or p.get("quiz_id")
        if r["type"] in ("quiz_start", "tutor_start") and sid:
            open_[sid] = r["ts"]
        elif r["type"] in ("quiz_end", "tutor_end") and sid in open_:
            try:
                delta = datetime.fromisoformat(r["ts"]) - datetime.fromisoformat(open_.pop(sid))
                minutes += min(max(delta.total_seconds() / 60, 0), 120)
            except ValueError:
                pass
    enough = len(learners) >= MIN_STUDENTS
    return {"active_students": len(learners) if enough else None, "sessions": len(starts) if enough else None,
            "chat_questions": len(chats) if enough else None, "hours": round(minutes / 60, 1) if enough else None,
            "suppressed": not enough}
