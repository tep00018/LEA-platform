"""Driving LEA for one learner-week (docs/simulation/PLAN.md, section 2).

Per week: one Chat sitting (3-5 bank questions for the week, one of them a follow-up,
rephrased in the learner's voice), then Tutor until LEA ends the session, the learner
quits, or 40 turns, then a Quiz answered to the end. If LEA opens the next week, move on;
if not, Tutor and Quiz again up to ``extra_rounds_when_stuck`` more times, then move on
anyway and mark the week "stuck".

Every exchange becomes one record in ``events.jsonl``: the learner's hidden state before
and after, the intent, what the student wrote, LEA's full output (message, grade, score),
LEA's mastery before and after for the objective, the orchestrator's decisions (read back
from the run's event log, as LEA wrote them), what was retrieved, and the OpenAI and
Claude usage of that exchange. LEA is called exactly as the API calls it.
"""

from __future__ import annotations

import json
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
import dataclasses
from typing import Any, Callable, Dict, List, Optional

from simulation.capture import read_decisions
from simulation.learner import Learner
from simulation.llm.claude_cli import ClaudeCallError

QTYPE = {"multiple_choice": "multiple_choice", "true_false": "true_false", "fill_in_blank": "fill_in",
         "fill_in": "fill_in", "open_ended": "open_ended", "short_answer": "open_ended"}


class EventWriter:
    """Append-only ``events.jsonl`` (thread-safe)."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def write(self, record: Dict[str, Any]) -> None:
        line = json.dumps({"ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), **record},
                          ensure_ascii=False, default=str)
        with self._lock, open(self.path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def mastery_levels(services, username: str, course: str) -> Dict[str, Optional[float]]:
    """LEA's stored mastery level per GO for this learner (read directly, as preview does)."""
    raw = services.redis_client.get_redis().get(f"mastery:{username}:{course}")
    data = json.loads(raw) if raw else {}
    out = {}
    for go, value in (data.get("go_masteries") or {}).items():
        out[go] = value.get("level") if isinstance(value, dict) else value
    return out


class LearnerRunner:
    """One simulated learner driving LEA; call ``run_week`` for each week in turn."""

    def __init__(self, *, services, learner: Learner, bank: Dict[str, Dict[str, Any]], student, meter, spy,
                 writer: EventWriter, config: Dict[str, Any], course: str, run_id: str,
                 thresholds: Dict[str, float], trace: Optional[Callable[[str], None]] = None):
        self.trace = trace
        self.s = services
        self.learner = learner
        self.bank = bank
        self.student = student
        self.meter = meter
        self.spy = spy
        self.writer = writer
        self.config = config
        self.course = course
        self.run_id = run_id
        self.thresholds = thresholds
        self.username = learner.username
        self.pseudonym = services.events.pseudonym(self.username)
        self.last_event_id = 0
        self.turn_no = 0
        self.turn_decisions: List[Dict[str, Any]] = []
        # Real fill-in-the-blank answers this learner has seen, for programmatic wrong answers
        # (a genuine course term that is simply wrong for the current blank, not an LLM invention).
        self._fill_in_pool: List[str] = []

    # ------------------------------------------------------------ setup
    def create_account(self) -> None:
        """A throwaway account in the run's own fakeredis, tagged simulated."""
        password = secrets.token_urlsafe(16)
        self.s.accounts.register(self.username, self.learner.profile.name, password, password, [self.course])
        self.s.redis_client.get_redis().hset(f"user:{self.username}", "session_kind", "simulated")
        self.s.events.forget_kind(self.username)

    # ------------------------------------------------------------ one week
    def run_week(self, week: int) -> Dict[str, Any]:
        cfg = self.config["scale"]
        gos = [g["go_id"] for g in self.s.courses.week_objectives(self.course, week)]
        self.turn_no = 0  # turns are numbered within the learner-week (stable across resumes)
        self.spy.take()
        self.meter.since_mark()
        self._drain_decisions()
        self.chat_sitting(week, gos)
        advanced, rounds = None, 0
        for rounds in range(1, 2 + int(cfg["extra_rounds_when_stuck"])):
            tutor = self.tutor_session(week, rounds, int(cfg["tutor_turn_cap"]))
            quiz = self.quiz(week, rounds)
            advanced = tutor.get("advanced_to_week") or quiz.get("advanced_to_week")
            if advanced:
                break
        levels = mastery_levels(self.s, self.username, self.course)
        truth = self.learner.snapshot()
        summary = {
            "kind": "week_end", "run_id": self.run_id, "learner": self.username, "profile": self.learner.profile.key,
            "week": week, "rounds": rounds, "advanced_to_week": advanced, "stuck": not advanced,
            "gos": [{"go_id": g, "lea_mastery": levels.get(g), "threshold": self.thresholds.get(g),
                     "lea_mastered": (levels.get(g) is not None and self.thresholds.get(g) is not None
                                      and levels[g] >= self.thresholds[g]),
                     "known": truth["known"].get(g), "p_know": truth["p_know"].get(g)} for g in gos],
            "all_mastery": levels,
        }
        self.writer.write(summary)
        return summary

    # ------------------------------------------------------------ chat
    def chat_sitting(self, week: int, gos: List[str]) -> None:
        entries = [self.bank[g] for g in gos if g in self.bank]
        if not entries:
            return
        rng = self.learner.rng_style
        n = int(rng.integers(3, 6))
        order = [entries[int(i)] for i in rng.permutation(len(entries))]
        picked: List[Dict[str, Any]] = []
        parent = order[0]
        first_q = int(parent["questions"][2]["follows"])
        picked.append({"entry": parent, "text": parent["questions"][first_q]["text"], "follow_up": False})
        picked.append({"entry": parent, "text": parent["questions"][2]["text"], "follow_up": True})
        for e in (order[1:] * 3)[: max(0, n - 2)]:
            q = int(rng.integers(0, 2))
            picked.append({"entry": e, "text": e["questions"][q]["text"], "follow_up": False})
        texts = [p["text"] for p in picked]
        try:
            texts = self.student.chat_messages(self.learner, texts, self.learner.target_words())
        except ClaudeCallError:
            pass  # keep the bank's wording; the record says so
        for i, (p, text) in enumerate(zip(picked, texts)):
            before = self.learner.snapshot()
            reply = self.s.chat.send(self.username, self.course, week, text)
            self._record("chat", week, 1, p["entry"]["go_id"], "chat_question", None, text, before, {
                "message": reply.message, "ok": reply.ok}, extra={
                "chat_index": i, "follow_up": p["follow_up"], "bank_question": p["text"],
                "source_file": p["entry"]["source_file"], "reference_answer": p["entry"]["reference_answer"],
                "rephrased": text != p["text"]})

    # ------------------------------------------------------------ tutor
    def tutor_session(self, week: int, round_no: int, cap: int) -> Dict[str, Any]:
        state = self.s.tutor.start(self.username, self.course, week)
        self.learner.start_session()
        session = state.session
        message = next((m.get("content") or m.get("message") for m in reversed(session.conversation_history)
                        if m.get("role") == "tutor"), "")
        self._drain_decisions()
        self.writer.write({"kind": "tutor_start", "run_id": self.run_id, "learner": self.username,
                           "profile": self.learner.profile.key, "week": week, "round": round_no,
                           "message": message, "retrieval": self.spy.take(),
                           "go_ids": [g["go_id"] for g in session.go_list]})
        ended_by = "cap"
        for _ in range(cap):
            if session.current_go_index >= len(session.go_list):
                ended_by = "lea"
                break
            go = session.go_list[session.current_go_index]["go_id"]
            entry = self.bank.get(go) or {"skill_name": go, "reference_answer": "", "source_quote": "",
                                          "misconceptions": []}
            intent = self.learner.turn(go, "tutor_reply")
            if intent.kind == "quit":
                self._record("tutor", week, round_no, go, "tutor_reply", intent, None, self.learner.snapshot(),
                             {"message": None}, extra={"quit": True})
                ended_by = "learner"
                break
            misconception = self._misconception(entry) if intent.kind == "answer" and not intent.correct else None
            try:
                text = self.student.tutor_reply(self.learner, intent, message or "", entry, misconception)
            except ClaudeCallError as e:
                self._record("tutor", week, round_no, go, "tutor_reply", intent, None, self.learner.snapshot(),
                             {"message": None}, extra={"student_failed": str(e)[:200]})
                ended_by = "student_failed"
                break
            if intent.kind == "answer" and getattr(self.student, "last_checkable", None) is False:
                # The tutor asked nothing with a right answer, so "meant to be correct or wrong" has no meaning here.
                intent = dataclasses.replace(intent, kind="acknowledge", correct=None)
                misconception = None
            before = self.learner.snapshot()
            mastery_before = mastery_levels(self.s, self.username, self.course).get(go)
            sig = self._signals(go, "tutor_reply", intent, text, message or "")
            reply = self.s.tutor.respond(self.username, text, timing=sig["timing"])
            self.learner.after_tutor_exchange(go, intent)
            session = reply.state.session
            message = reply.message
            self._record("tutor", week, round_no, go, "tutor_reply", intent, text, before, {
                "message": reply.message, "graded": reply.graded, "correct": reply.correct,
                "advanced": session.current_go_index, "completed": reply.state.completed},
                mastery_before=mastery_before, extra={"misconception": misconception, **sig})
            if reply.state.completed:
                ended_by = "lea"
                break
        summary = self.s.tutor.end(self.username) or {}
        self.writer.write({"kind": "tutor_end", "run_id": self.run_id, "learner": self.username, "week": week,
                           "round": round_no, "ended_by": ended_by,
                           "summary": {k: v for k, v in summary.items() if isinstance(v, (int, float, str, bool,
                                                                                           type(None)))}})
        return summary

    # ------------------------------------------------------------ quiz
    def quiz(self, week: int, round_no: int) -> Dict[str, Any]:
        state = self.s.quiz.start(self.username, self.course, week)
        self.learner.start_session()
        self._drain_decisions()
        while state.status == "question":
            q = state.current_question or {}
            go = q.get("go_id")
            qtype = QTYPE.get(q.get("type"), "open_ended")
            intent = self.learner.turn(go, qtype, may_digress=False)
            before = self.learner.snapshot()
            entry = self.bank.get(go)
            answer, misconception = self._quiz_answer(q, qtype, intent, entry)
            if answer is None:
                self._record("quiz", week, round_no, go, qtype, intent, None, before, {"message": None},
                             extra={"student_failed": True, "question": q})
                state = self.s.quiz.end(self.username)
                break
            mastery_before = mastery_levels(self.s, self.username, self.course).get(go)
            sig = self._signals(go, qtype, intent, answer, str(q.get("text") or ""), quiz=True)
            state = self.s.quiz.answer(self.username, answer, timing=sig["timing"])
            self.learner.after_quiz_feedback(go)
            fb = state.feedback
            self._record("quiz", week, round_no, go, qtype, intent, answer, before, {
                "graded": fb.graded, "correct": fb.correct, "score": fb.score, "explanation": fb.explanation,
                "expected_answer": fb.expected_answer}, mastery_before=mastery_before, extra={
                "question": {k: q.get(k) for k in ("text", "type", "options", "correct_answer", "sample_answer",
                                                   "skill_name")},
                "misconception": misconception, **sig})
            state = self.s.quiz.next(self.username)
        result = {"advanced_to_week": state.advanced_to_week if state is not None else None}
        self.s.quiz.discard(self.username)
        self.writer.write({"kind": "quiz_end", "run_id": self.run_id, "learner": self.username, "week": week,
                           "round": round_no, **result})
        return result

    def _quiz_answer(self, q: Dict[str, Any], qtype: str, intent, entry) -> tuple[Optional[str], Optional[str]]:
        if qtype == "multiple_choice":
            options = list(q.get("options") or [])
            letter = str(q.get("correct_answer", "A")).strip()[:1].upper()
            index = next((i for i, o in enumerate(options) if str(o).strip().upper().startswith(letter)), 0)
            return str(options[self.learner.pick_option(options, index, intent.correct)]) if options else letter, None
        if qtype == "true_false":
            truth = str(q.get("correct_answer", "True")).strip().lower().startswith("t")
            return ("True" if truth == intent.correct else "False"), None
        if qtype == "fill_in":
            correct_term = str(q.get("correct_answer") or "").strip()
            if correct_term and correct_term.lower() not in {t.lower() for t in self._fill_in_pool}:
                self._fill_in_pool.append(correct_term)
            if not intent.correct:
                # A genuine course term that is simply wrong for this blank -- no LLM call, so it can
                # never accidentally come out right. Falls back to the old (LLM) path only until enough
                # distinct terms have been seen (early in a run).
                pool = [t for t in self._fill_in_pool if t.lower() != correct_term.lower()]
                if pool:
                    return str(self.learner.rng_style.choice(pool)), None
        misconception = None if intent.correct else self._misconception(entry or {})
        try:
            return self.student.quiz_answer(self.learner, intent, q, entry, misconception), misconception
        except ClaudeCallError:
            return None, misconception

    # ------------------------------------------------------------ helpers
    def _signals(self, go: str, qtype: str, intent, text: str, prompt: str, quiz: bool = False) -> Dict[str, Any]:
        """The hidden load for this turn and the timing block a client would send (see signals.py)."""
        demand = 1.0 - self.learner.success_probability(go, qtype)
        task = 0.0 if quiz else (1.0 if len((text or "").split()) > 15 else 0.0)  # as LEA classifies task type
        return self.learner.signals.observe(go, demand=demand, task=task, prompt_chars=len(prompt), chars=len(text or ""),
                                            kind=intent.kind, engagement=intent.engagement,
                                            answer_attempt=intent.kind == "answer")

    def _misconception(self, entry: Dict[str, Any]) -> Optional[str]:
        options = [m["text"] for m in entry.get("misconceptions") or []]
        return str(self.learner.rng_style.choice(options)) if options else None

    def _drain_decisions(self) -> List[Dict[str, Any]]:
        log = self.s.events.log
        if log is None:
            return []
        rows, self.last_event_id = read_decisions(log, self.pseudonym, self.last_event_id)
        return rows

    def _record(self, mode: str, week: int, round_no: int, go: Optional[str], qtype: str, intent, text,
                before: Dict[str, Any], lea: Dict[str, Any], *, mastery_before=None, extra=None) -> None:
        self.turn_no += 1
        self.turn_decisions = self._drain_decisions()
        after = self.learner.snapshot()
        mastery_after = mastery_levels(self.s, self.username, self.course).get(go) if go else None
        student_calls, self.student.calls[:] = list(self.student.calls), []
        self.writer.write({
            "kind": "turn", "run_id": self.run_id, "learner": self.username, "profile": self.learner.profile.key,
            "week": week, "round": round_no, "mode": mode, "turn": self.turn_no, "go_id": go, "qtype": qtype,
            "intent": None if intent is None else {
                "kind": intent.kind, "correct": intent.correct, "p_correct": intent.p_correct, "known": intent.known,
                "engagement": intent.engagement, "target_words": intent.target_words},
            "student_text": text,
            "hidden_before": {"known": before["known"].get(go), "p_know": before["p_know"].get(go),
                              "engagement": before["engagement"], "eps": before["eps"]} if go else None,
            "hidden_after": {"known": after["known"].get(go), "p_know": after["p_know"].get(go)} if go else None,
            "lea": lea,
            "mastery": {"before": mastery_before, "after": mastery_after, "threshold": self.thresholds.get(go)},
            "decisions": self.turn_decisions,
            "retrieval": self.spy.take(),
            "openai": self.meter.since_mark(),
            "claude_student": {"calls": len(student_calls), "cost_usd": round(sum(c["cost_usd"] for c in student_calls), 6),
                               "models": sorted({c["model"] for c in student_calls if c.get("model")})},
            **(extra or {}),
        })
        if self.trace:
            self.trace(self._trace_line(mode, week, round_no, go, qtype, intent, text, lea, mastery_before,
                                        mastery_after, student_calls))

    def _trace_line(self, mode, week, round_no, go, qtype, intent, text, lea, m_before, m_after, student_calls) -> str:
        def q(v, n):
            return "-" if v is None else (f"{v:.2f}" if isinstance(v, float) else str(v))[:n]

        decisions = ",".join(sorted({str(d.get("type")) for d in self.turn_decisions}))
        cost = sum(c["cost_usd"] for c in student_calls)
        head = f"[{self.username} w{week}r{round_no} #{self.turn_no} {mode}/{qtype} go={go}]"
        if intent is None:
            said = f"chat: {(text or '')[:90]!r}"
            return f"{head} {said} | lea_ok={lea.get('ok')} decisions={decisions}"
        h = self.learner.snapshot()
        know = h["p_know"].get(go) if go else None
        return (f"{head} intent={intent.kind}/{'-' if intent.correct is None else 'right' if intent.correct else 'wrong'} p_ok={q(intent.p_correct, 4)} "
                f"eng={intent.engagement} | said={(text or '')[:80]!r} | true_p_know={q(know, 4)} "
                f"lea: graded={lea.get('graded')} correct={lea.get('correct', lea.get('is_correct'))} "
                f"mastery {q(m_before, 4)}->{q(m_after, 4)} | decisions={decisions} | student ${cost:.4f}")
