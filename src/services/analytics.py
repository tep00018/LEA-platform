"""Student analytics for teachers (B6), from the event log.

``kind`` is ``real`` (the default: real students only) or ``simulated`` (students seeded
by ``scripts/seed_simulated.py``, for trying the screens); the two are never mixed and
test sessions are never included. Every figure from fewer than 5 students is withheld
(see ``src.onboarding.analytics_compute``). Views are logged as staff events: teachers'
use of the dashboard is research data too.

Two parts use OpenAI, only when the teacher asks and after showing the cost: chat topics
(questions grouped by topic and mapped to objectives, with a second independent pass to
report agreement) and a drafted explainer for an objective (never published by LEA).
Results are kept in ``data/analytics/<CODE>/`` (gitignored).
"""

from __future__ import annotations

import csv
import io
import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from src.onboarding import analytics_compute as C
from src.onboarding import kc_model as K
from src.services.errors import InvalidInput, NotFound, Unavailable
from src.services.events import EventRecorder, disabled

logger = logging.getLogger(__name__)

KINDS = ("real", "simulated")
TOPIC_MODEL = "gpt-4o-mini"
MAX_CHAT_QUESTIONS = 400
TOPIC_USD_PER_QUESTION = 0.00004
EXPLAINER_USD = 0.002


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class AnalyticsService:
    def __init__(self, registry, events: Optional[EventRecorder] = None, openai_client=None,
                 course_content: Optional[Callable[[str, str], str]] = None):
        self.registry = registry
        self.events = events or disabled()
        self.openai_client = openai_client
        self.course_content = course_content or (lambda course, query: "")

    # ------------------------------------------------------------------ reads

    def _model(self, code: str) -> Dict[str, Any]:
        model = self.registry.kc_model(code)
        if model is None:
            raise InvalidInput("Publish this course's objectives first: analytics follow the live version.")
        return model

    def rows(self, code: str, kind: str = "real", since: Optional[str] = None,
             until: Optional[str] = None) -> List[Dict[str, Any]]:
        if kind not in KINDS:
            raise InvalidInput("Show real or simulated students.")
        if self.events.log is None:
            raise Unavailable("The event log is off (LEA_EVENT_SALT isn't set), so there's nothing to analyse.")
        where, params = ["course = ?", "session_kind = ?", "actor IS NULL"], [code, kind]
        if since:
            where.append("ts >= ?")
            params.append(since)
        if until:
            where.append("ts < ?")
            params.append(until)
        return self.events.log.query(" AND ".join(where), params)

    def _topics(self, code: str, kind: str) -> Optional[Dict[str, Any]]:
        path = self._folder(code) / f"chat_topics_{kind}.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def _folder(self, code: str) -> Path:
        return Path(self.registry.data_dir) / "analytics" / code

    # ------------------------------------------------------------------ overview and detail

    def overview(self, actor: str, code: str, kind: str = "real", week: Optional[int] = None,
                 since: Optional[str] = None, until: Optional[str] = None) -> Dict[str, Any]:
        model = self._model(code)
        rows = self.rows(code, kind, since, until)
        by_go = C.graded_attempts(rows)
        strug = C.struggle(rows)
        chat = self._chat_students_by_go(code, kind)
        objectives = []
        for r in K.rows_from_model(model):
            if week is not None and int(r["week"]) != week:
                continue
            go = K.gos_of(model)[r["go_id"]]
            stats = C.objective_stats(go, by_go.get(r["go_id"], {}))
            att = C.attention(stats, strug.get(r["go_id"]), chat.get(r["go_id"], 0))
            objectives.append({**{k: v for k, v in stats.items() if k != "curve"}, "week": int(r["week"]),
                               "lo_id": r["lo_id"], "attention": att})
        objectives.sort(key=lambda o: (o["attention"]["score"] is None, -(o["attention"]["score"] or 0)))
        students = len({r["username_hash"] for r in rows if r["type"] == "answer"})
        bands = {b: sum(1 for o in objectives if o["band"] == b)
                 for b in ("mastered", "developing", "struggling", "insufficient")}
        self.events.staff(actor, "analytics_view", course=code, payload={
            "view": "overview", "kind": kind, "week": week,
            "flagged": [o["go_id"] for o in objectives if o["attention"]["level"] == "high"]})
        return {"course": code, "kind": kind, "week": week, "min_students": C.MIN_STUDENTS,
                "students": students if students >= C.MIN_STUDENTS else None,
                "suppressed": students < C.MIN_STUDENTS, "bands": bands, "objectives": objectives,
                "usage": C.usage(rows), "kc_version": (model.get("version_info") or {}).get("version", 0)}

    def detail(self, actor: str, code: str, go_id: str, kind: str = "real") -> Dict[str, Any]:
        model = self._model(code)
        go = K.gos_of(model).get(go_id)
        if go is None:
            raise NotFound("No such objective in the live version.")
        rows = self.rows(code, kind)
        by_go = C.graded_attempts(rows)
        by_learner = by_go.get(go_id, {})
        week = next((int(r["week"]) for r in K.rows_from_model(model) if r["go_id"] == go_id), None)
        stats = C.objective_stats(go, by_learner)
        strug = C.struggle(rows).get(go_id)
        topics = [t for t in (self._topics(code, kind) or {}).get("topics", []) if t.get("go_id") == go_id]
        chat_students = sum(t["students"] for t in topics)
        att = C.attention(stats, strug, chat_students)
        source = (go.get("provenance") or {}).get("source_file")
        enough = not stats["suppressed"]
        self.events.staff(actor, "analytics_view", course=code, payload={"view": "objective", "kind": kind, "go_id": go_id})
        return {**stats, "kind": kind, "week": week, "attention": att, "course_curve": C.course_curve(by_go),
                "wrong_answers": C.wrong_answers(by_learner),
                "struggle": ({**strug, "suppressed": False} if enough and strug else
                             {"streak_students": None, "video_students": None, "sessions_left_stuck": None,
                              "suppressed": not enough}),
                "chat_topics": topics, "suggestion": C.suggestion(stats, att, strug, source),
                "description": go.get("description", "")}

    def curves_csv(self, actor: str, code: str, kind: str = "real") -> str:
        """Aggregated learning curves (objective, opportunity, students, error rate), in the
        spirit of DataShop's learning-curve export; no per-student rows."""
        model = self._model(code)
        by_go = C.graded_attempts(self.rows(code, kind))
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(["KC (granular objective)", "Objective name", "Week", "Opportunity", "Students", "Error rate"])
        for r in K.rows_from_model(model):
            for p in C.curve(by_go.get(r["go_id"], {})):
                if p["error_rate"] is not None:
                    writer.writerow([r["go_id"], r["skill_name"], r["week"], p["opportunity"], p["students"],
                                     p["error_rate"]])
        self.events.staff(actor, "analytics_export", course=code, payload={"kind": kind})
        return out.getvalue()

    # ------------------------------------------------------------------ chat topics (LLM, on request)

    def _chat_students_by_go(self, code: str, kind: str) -> Dict[str, int]:
        counts: Dict[str, int] = defaultdict(int)
        for t in (self._topics(code, kind) or {}).get("topics", []):
            if t.get("go_id"):
                counts[t["go_id"]] += t["students"]
        return counts

    def _chat_questions(self, code: str, kind: str) -> List[Dict[str, Any]]:
        rows = [r for r in self.rows(code, kind) if r["type"] == "chat_question"][-MAX_CHAT_QUESTIONS:]
        return [{"learner": r["username_hash"], "text": C._payload(r).get("text", "")[:300]} for r in rows]

    def chat_topics(self, code: str, kind: str = "real") -> Dict[str, Any]:
        questions = self._chat_questions(code, kind)
        learners = len({q["learner"] for q in questions})
        return {"result": self._topics(code, kind), "questions": len(questions),
                "students": learners if learners >= C.MIN_STUDENTS else None,
                "usd": round(len(questions) * TOPIC_USD_PER_QUESTION, 4),
                "can_run": learners >= C.MIN_STUDENTS}

    def run_chat_topics(self, actor: str, code: str, kind: str = "real") -> Dict[str, Any]:
        model = self._model(code)
        questions = self._chat_questions(code, kind)
        if len({q["learner"] for q in questions}) < C.MIN_STUDENTS:
            raise InvalidInput("Chat topics need questions from at least 5 students.")
        objectives = "\n".join(f"{r['go_id']}: {r['skill_name']}" for r in K.rows_from_model(model))
        numbered = "\n".join(f"{i}. {q['text']}" for i, q in enumerate(questions))
        grouped = self._ask_json(
            "You group students' questions about a course into topics. Return JSON: {\"topics\": [{\"label\": "
            "short topic name, \"go_id\": the best-matching objective ID or null, \"questions\": [question numbers], "
            "\"paraphrases\": [up to 3 short paraphrased example questions, with no names or personal details]}]}. "
            "Every question belongs to exactly one topic.",
            f"Objectives:\n{objectives}\n\nQuestions:\n{numbered}")
        second = self._ask_json(
            "For each student question, give the ID of the course objective it is about, or null. "
            "Return JSON: {\"assignments\": {\"question number\": \"objective ID or null\"}}.",
            f"Objectives:\n{objectives}\n\nQuestions:\n{numbered}")
        first_map = {}
        topics = []
        valid = set(K.gos_of(model))
        for t in grouped.get("topics", []):
            idx = [i for i in t.get("questions", []) if isinstance(i, int) and 0 <= i < len(questions)]
            go = t.get("go_id") if t.get("go_id") in valid else None
            for i in idx:
                first_map[i] = go
            students = len({questions[i]["learner"] for i in idx})
            if students >= C.MIN_STUDENTS:  # topics asked by fewer than 5 students aren't shown
                topics.append({"label": str(t.get("label", ""))[:80], "go_id": go, "students": students,
                               "questions": len(idx), "paraphrases": [str(p)[:200] for p in t.get("paraphrases", [])[:3]]})
        assigned = second.get("assignments", {})
        both = [i for i in first_map if str(i) in assigned]
        agreement = (sum(1 for i in both if (assigned[str(i)] if assigned[str(i)] in valid else None) == first_map[i])
                     / len(both)) if both else None
        result = {"ran_at": _now(), "kind": kind, "model": TOPIC_MODEL, "questions": len(questions),
                  "agreement": round(agreement, 3) if agreement is not None else None,
                  "topics": sorted(topics, key=lambda t: -t["students"])}
        folder = self._folder(code)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"chat_topics_{kind}.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        self.events.staff(actor, "analytics_chat_topics", course=code, payload={
            "kind": kind, "questions": len(questions), "topics": len(topics), "agreement": result["agreement"]})
        return result

    # ------------------------------------------------------------------ explainer (LLM, on request)

    def explainer(self, actor: str, code: str, go_id: str) -> Dict[str, Any]:
        model = self._model(code)
        go = K.gos_of(model).get(go_id)
        if go is None:
            raise NotFound("No such objective in the live version.")
        content = self.course_content(code, f"{go.get('skill_name', '')}. {go.get('description', '')}")[:3000]
        text = self._ask(
            "You help a university teacher. Write a short, clear explanation (at most 180 words) of the objective "
            "for students who find it hard, using the course material given. Plain language, one worked example if "
            "it helps. The teacher will edit it before using it.",
            f"Objective: {go.get('skill_name', '')}\n{go.get('description', '')}\n\nCourse material:\n{content}")
        self.events.staff(actor, "analytics_explainer", course=code, payload={"go_id": go_id})
        return {"go_id": go_id, "text": text.strip(), "model": TOPIC_MODEL,
                "note": "Drafted by LEA from the course material. Check and edit it; LEA never publishes it."}

    # ------------------------------------------------------------------ model calls

    def _ask(self, system: str, user: str, json_mode: bool = False) -> str:
        if self.openai_client is None:
            raise Unavailable("OpenAI isn't configured.")
        try:
            response = self.openai_client.chat.completions.create(
                model=TOPIC_MODEL, temperature=0.2, max_tokens=1500 if json_mode else 400,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                **({"response_format": {"type": "json_object"}} if json_mode else {}))
            return response.choices[0].message.content or ""
        except Exception as e:
            logger.error(f"Analytics model call failed: {e}")
            raise Unavailable("The model couldn't be reached. Please try again.") from None

    def _ask_json(self, system: str, user: str) -> Dict[str, Any]:
        try:
            return json.loads(self._ask(system, user, json_mode=True))
        except ValueError:
            raise Unavailable("The model's answer couldn't be read. Please try again.") from None
