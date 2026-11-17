"""Simulated students for trying the analytics (and B9's end-to-end run).

Writes events tagged ``simulated`` straight into the event log: graded quiz and tutor
answers with a plausible learning pattern per objective (most improve with practice; a
few, picked at random, stay hard: a flat curve), common wrong answers, tutor struggle,
session starts and ends, and chat questions. Nothing here is real student data and it is
never tagged ``real``; analytics show it only when "Simulated" is chosen.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from src.onboarding import kc_model as K

CHAT_TEMPLATES = [
    "I don't get {name}. Can you explain it simply?",
    "Why does {name} matter?",
    "Can you give me an example of {name}?",
    "What's the difference between {name} and the previous idea?",
]


def seed(recorder, model: Dict[str, Any], course: str, students: int = 30, weeks: int | None = None,
         rng_seed: int = 7) -> Dict[str, int]:
    """Writes the events; returns counts."""
    rng = random.Random(rng_seed)
    rows = K.rows_from_model(model)
    if weeks is not None:
        rows = [r for r in rows if int(r["week"]) <= weeks]
    hard = {r["go_id"] for r in rng.sample(rows, max(1, len(rows) // 8))}
    version = (model.get("version_info") or {}).get("version")
    start = datetime.now(timezone.utc) - timedelta(days=28)
    log = recorder.log
    counts = {"students": students, "answers": 0, "chat": 0, "sessions": 0}

    def put(learner: str, ts: datetime, **fields) -> None:
        log.append(session_kind="simulated", course=course, kc_version=str(version) if version else None,
                   username_hash=recorder.pseudonym(learner), ts=ts.isoformat(timespec="milliseconds"), **fields)

    for s in range(students):
        learner = f"sim.{course.lower()}.{s:03d}"
        ability = rng.gauss(0, 0.8)
        t = start + timedelta(hours=rng.randint(0, 48))
        for week in sorted({int(r["week"]) for r in rows}):
            week_rows = [r for r in rows if int(r["week"]) == week]
            quiz_id = f"quiz_sim_{s}_{week}"
            put(learner, t, type="quiz_start", mode="quiz", week=week, payload={"quiz_id": quiz_id})
            session_id = f"tutor_sim_{s}_{week}"
            put(learner, t, type="tutor_start", mode="tutor", week=week, payload={"session_id": session_id})
            counts["sessions"] += 2
            for r in week_rows:
                streak = 0
                attempts = rng.randint(2, 6)
                for k in range(attempts):
                    t += timedelta(minutes=rng.randint(1, 6))
                    base = 0.35 if r["go_id"] in hard else 0.45 + 0.12 * k
                    p = min(0.95, max(0.05, base + 0.12 * ability))
                    correct = rng.random() < p
                    mode = "quiz" if k % 2 == 0 else "tutor"
                    streak = 0 if correct else streak + 1
                    payload: Dict[str, Any] = {"graded": True}
                    if mode == "quiz":
                        options = [f"{r['skill_name']} (right)", "A common misconception", "An unrelated idea", "A guess"]
                        chosen = 0 if correct else rng.choices([1, 2, 3], weights=[6, 2, 1])[0]
                        payload.update({"quiz_id": quiz_id, "question": f"About {r['skill_name']}?",
                                        "options": [f"{'ABCD'[i]}) {o}" for i, o in enumerate(options)],
                                        "expected_answer": "A", "response": "ABCD"[chosen]})
                    else:
                        payload.update({"session_id": session_id, "response": "…", "diagnostic": False,
                                        "consecutive_incorrect": streak, "youtube_shown": streak >= 3,
                                        "advanced": correct and k == attempts - 1})
                    put(learner, t, type="answer", mode=mode, go_id=r["go_id"], lo_id=r["lo_id"], week=week,
                        correct=correct, score=1.0 if correct else rng.choice([0.0, 0.2, 0.4]),
                        question_type="multiple_choice" if mode == "quiz" else "tutor_response", payload=payload)
                    counts["answers"] += 1
                if r["go_id"] in hard and rng.random() < 0.7:
                    put(learner, t, type="chat_question", mode="chat", week=week,
                        payload={"text": rng.choice(CHAT_TEMPLATES).format(name=r["skill_name"].lower()), "answered": True})
                    counts["chat"] += 1
            t += timedelta(minutes=rng.randint(10, 40))
            put(learner, t, type="quiz_end", mode="quiz", week=week, payload={"quiz_id": quiz_id})
            put(learner, t, type="tutor_end", mode="tutor", week=week, payload={"session_id": session_id})
            t += timedelta(days=rng.randint(3, 6))
    counts["hard_objectives"] = len(hard)
    return counts


def existing(recorder, course: str) -> int:
    return len(recorder.log.query("course = ? AND session_kind = 'simulated'", [course]))

