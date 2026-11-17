"""Trying LEA on another model, side by side (not part of the study's metrics).

The same scripted learner does the same things against LEA once per arm:

1. Chat: a sitting of five questions from the question bank (a question and its follow-up
   on two objectives, then one more question);
2. Tutor: six turns on week 1 (right, wrong, right, "I'm not sure", a real question, wrong);
3. Quiz: all of week 1, answered right, wrong, right, wrong... using the answer LEA itself
   holds for each question (multiple choice, true/false, a blank) or the bank's reference
   answer and misconceptions (open-ended).

LEA runs unchanged. Only the model behind its client differs (``openai`` = LEA as deployed;
``sonnet`` = the same services on Claude Sonnet through the subscription), and an arm may
run only some parts (``parts``) or under a prompt variant (``simulation/variants.py``).
Each arm has its own run folder, fakeredis and copy of AIML101, like any simulation run.
One learner and one script make this a look at what each model writes, not a measurement.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from simulation.capture import OpenAIMeter, RetrievalSpy
from simulation.harness import load_bank

COURSE = "AIML101"
USER = "sim_compare_0"
QUIZ_LIMIT = 14
PARTS = ("chat", "tutor", "quiz")
TUTOR_PLAN = ("right", "wrong", "right", "minimal", "question", "wrong")
EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿⭐✅]")


def _letter(value: Any) -> str:
    text = str(value or "").strip()
    return text[:1].upper() if text else ""


def mc_answer(q: Dict[str, Any], right: bool) -> str:
    options = list(q.get("options") or [])
    letter = _letter(q.get("correct_answer"))
    keyed = [o for o in options if _letter(o) == letter]
    others = [o for o in options if _letter(o) != letter]
    return str((keyed or options or [letter])[0] if right else (others or options or ["X"])[0])


def tf_answer(q: Dict[str, Any], right: bool) -> str:
    truth = str(q.get("correct_answer", "True")).strip().lower().startswith("t")
    return "True" if truth == right else "False"


def free_answer(q: Dict[str, Any], right: bool, bank: Dict[str, Dict[str, Any]]) -> str:
    entry = bank.get(q.get("go_id") or "") or {}
    if right and q.get("type") == "fill_in_blank" and q.get("correct_answer"):
        return str(q["correct_answer"])  # a blank takes the missing word, not a sentence
    if right:
        return str(entry.get("reference_answer") or q.get("correct_answer") or q.get("sample_answer") or "I think so.")
    misconceptions = entry.get("misconceptions") or []
    return str(misconceptions[0]["text"]) if misconceptions else "I have no idea."


def quiz_answer(q: Dict[str, Any], right: bool, bank) -> str:
    kind = q.get("type")
    if kind == "multiple_choice":
        return mc_answer(q, right)
    if kind == "true_false":
        return tf_answer(q, right)
    return free_answer(q, right, bank)


def tutor_text(kind: str, entry: Dict[str, Any]) -> str:
    if kind == "minimal":
        return "I'm not sure, sorry."
    if kind == "right":
        return str(entry.get("reference_answer") or "I think it is about learning from examples.")
    if kind == "question":
        return str((entry.get("questions") or [{"text": "Why does this matter?"}])[0]["text"])
    misconceptions = entry.get("misconceptions") or [{"text": "I have no idea."}]
    return str(misconceptions[0]["text"])


def chat_script(gos: List[str], bank: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """A sitting of five: a question and its follow-up for two objectives, then one more question."""
    entries = [bank[g] for g in gos if g in bank][:3]
    script: List[Dict[str, Any]] = []
    for i, e in enumerate(entries):
        qs = e["questions"]
        script.append({"kind": "question", "go_id": e["go_id"], "text": qs[int(qs[2]["follows"])]["text"]})
        if i < 2:
            script.append({"kind": "follow_up", "go_id": e["go_id"], "text": qs[2]["text"]})
    return script


def run_arm(label: str, services, bank: Dict[str, Dict[str, Any]], progress: Callable[[str], None] = print,
            week: int = 1, should_stop: Callable[[], Optional[str]] = lambda: None,
            parts: Sequence[str] = PARTS) -> Dict[str, Any]:
    """The scripted session against ``services``; returns everything that happened.
    ``should_stop`` returns a reason once a usage stop has happened (LEA swallows model
    errors, so the session is ended between steps rather than carried on)."""
    s = services

    def check() -> None:
        reason = should_stop()
        if reason:
            raise RuntimeError(f"stopped: {reason}")

    spy = RetrievalSpy(s.learning.orchestrator)
    started = time.monotonic()
    out: Dict[str, Any] = {"label": label, "parts": list(parts), "chat": [], "tutor": {}, "quiz": []}
    try:
        password = "not-a-real-password-1"
        s.accounts.register(USER, "Compare Learner", password, password, [COURSE])
        s.redis_client.get_redis().hset(f"user:{USER}", "session_kind", "simulated")
        s.events.forget_kind(USER)
        gos = [g["go_id"] for g in s.courses.week_objectives(COURSE, week)]

        if "chat" in parts:
            for step in chat_script(gos, bank):
                reply = s.chat.send(USER, COURSE, week, step["text"])
                check()
                out["chat"].append({**step, "student": step["text"], "ok": reply.ok, "lea": reply.message,
                                    "retrieved": sorted({x.get("source") for r in spy.take()
                                                         for x in r.get("sources", [])})})
                progress(f"[{label}] chat {len(out['chat'])} done")

        if "tutor" in parts:
            state = s.tutor.start(USER, COURSE, week)
            session = state.session
            opening = next((m.get("content") for m in reversed(session.conversation_history)
                            if m.get("role") == "tutor"), "")
            turns = []
            for kind in TUTOR_PLAN:
                if session.current_go_index >= len(session.go_list):
                    break
                go = session.go_list[session.current_go_index]["go_id"]
                text = tutor_text(kind, bank.get(go) or {})
                reply = s.tutor.respond(USER, text)
                check()
                session = reply.state.session
                turns.append({"intended": kind, "go_id": go, "student": text, "lea": reply.message,
                              "graded": reply.graded, "correct": reply.correct})
                progress(f"[{label}] tutor {len(turns)} ({kind}) done")
            s.tutor.end(USER)
            out["tutor"] = {"opening": opening, "turns": turns}

        if "quiz" in parts:
            state = s.quiz.start(USER, COURSE, week)
            position = 0
            while state.status == "question" and position < QUIZ_LIMIT:
                position += 1
                q = state.current_question or {}
                right = position % 2 == 1
                answer = quiz_answer(q, right, bank)
                state = s.quiz.answer(USER, answer)
                check()
                fb = state.feedback
                out["quiz"].append({
                    "position": position, "go_id": q.get("go_id"), "type": q.get("type"), "text": q.get("text"),
                    "options": q.get("options"), "keyed": q.get("correct_answer") or q.get("sample_answer"),
                    "intended": "right" if right else "wrong", "answer": answer,
                    "graded": fb.graded, "correct": fb.correct, "score": fb.score, "explanation": fb.explanation})
                progress(f"[{label}] quiz {position} done")
                state = s.quiz.next(USER)
            s.quiz.discard(USER)
    except Exception as e:  # a usage stop or a failed call: keep what happened so far
        out["error"] = should_stop() and f"stopped: {should_stop()}" or f"{type(e).__name__}: {e}"
    finally:
        spy.remove()
    out["seconds"] = round(time.monotonic() - started, 1)
    return out


# ---------------------------------------------------------------------------- statistics


def text_stats(texts: Sequence[str]) -> Dict[str, Any]:
    """How the replies are written: length, formatting, emoji, and whether they end on a question."""
    texts = [t for t in texts if t]
    if not texts:
        return {}

    def share(fn) -> str:
        return f"{round(100 * sum(1 for t in texts if fn(t)) / len(texts))}%"

    def last_line(t: str) -> str:
        return next((x for x in reversed([ln.strip() for ln in t.splitlines()]) if x), "")

    return {"n": len(texts), "words": round(sum(len(t.split()) for t in texts) / len(texts)),
            "headings": share(lambda t: re.search(r"(?m)^#{1,6} ", t)),
            "bullets_or_numbers": share(lambda t: re.search(r"(?m)^\s*(?:[-*] |\d+[.)] )", t)),
            "bold": share(lambda t: "**" in t), "emoji": share(lambda t: EMOJI.search(t)),
            "ends_with_question": share(lambda t: last_line(t).endswith("?"))}


def coaching_openers(questions: Sequence[str]) -> int:
    """Quiz questions that open with encouragement (a simple, transparent count)."""
    pattern = re.compile(r"^(?:no worries|no pressure|nice|great|good|you'?re|you are|don'?t worry|let'?s take|"
                         r"take a moment|well done|take your time|you'?ve got)", re.I)
    return sum(1 for q in questions if pattern.match(str(q or "").strip()))


def summarise(arm: Dict[str, Any]) -> Dict[str, Any]:
    quiz = arm["quiz"]
    graded = [q for q in quiz if q["graded"] and q["correct"] is not None]
    agree = sum((q["correct"] is True) == (q["intended"] == "right") for q in graded)
    mc = [q for q in quiz if q["type"] == "multiple_choice"]
    return {"questions": len(quiz), "types": {t: sum(1 for q in quiz if q["type"] == t) for t in
                                             sorted({q["type"] for q in quiz})},
            "graded": len(graded), "grade_agrees_with_intent": f"{agree}/{len(graded)}" if graded else "–",
            "avg_question_words": round(sum(len(str(q["text"]).split()) for q in quiz) / len(quiz), 1) if quiz else None,
            "questions_opening_with_coaching": f"{coaching_openers([q['text'] for q in quiz])}/{len(quiz)}" if quiz else "–",
            "mc_with_4_distinct_options": sum(1 for q in mc if len({str(o)[2:].strip().lower() for o in
                                                                      q["options"] or []}) == 4),
            "mc_total": len(mc),
            "chat_replies": text_stats([c["lea"] for c in arm["chat"]]),
            "tutor_replies": text_stats([t["lea"] for t in arm["tutor"].get("turns", [])])}


# ---------------------------------------------------------------------------- the report


def _quote(text: Any) -> List[str]:
    return [f"> {ln}" if ln.strip() else ">" for ln in str(text or "").splitlines()] or [">"]


def _stats_line(s: Dict[str, Any]) -> str:
    if not s:
        return "–"
    return (f"{s['words']} words; headings {s['headings']}, lists {s['bullets_or_numbers']}, bold {s['bold']}, "
            f"emoji {s['emoji']}; ends with a question {s['ends_with_question']}")


def write_comparison(path: Path, arms: List[Dict[str, Any]], costs: Dict[str, Dict[str, Any]],
                     notes: Optional[str] = None) -> None:
    labels = [a["label"] for a in arms]
    lines = ["# LEA on OpenAI vs LEA on Claude Sonnet", "",
             "The same scripted learner, week 1 of AIML101, against LEA unchanged; only the model behind LEA's "
             "client differs. One learner and one script, so this shows what each model writes; it is not a "
             "measurement. Retrieval embeddings are OpenAI throughout. Claude ran with extended thinking off and no "
             "temperature control (`claude -p` has none); OpenAI ran as deployed.", ""]
    if notes:
        lines += [notes, ""]
    rows = {a["label"]: summarise(a) for a in arms}
    lines += ["## Summary", "", "| | " + " | ".join(labels) + " |", "|---|" + "---|" * len(arms)]

    def row(name, fn):
        lines.append(f"| {name} | " + " | ".join(str(fn(a)) for a in arms) + " |")

    row("Quiz questions", lambda a: rows[a["label"]]["questions"] or "–")
    row("Types", lambda a: rows[a["label"]]["types"] or "–")
    row("Avg question words", lambda a: rows[a["label"]]["avg_question_words"] or "–")
    row("Questions opening with coaching", lambda a: rows[a["label"]]["questions_opening_with_coaching"])
    row("MC with 4 distinct options", lambda a: f"{rows[a['label']]['mc_with_4_distinct_options']}/"
                                                 f"{rows[a['label']]['mc_total']}" if a["quiz"] else "–")
    row("LEA's grade agrees with the scripted right/wrong", lambda a: rows[a["label"]]["grade_agrees_with_intent"])
    row("Chat replies", lambda a: _stats_line(rows[a["label"]]["chat_replies"]))
    row("Tutor replies", lambda a: _stats_line(rows[a["label"]]["tutor_replies"]))
    row("Wall time (s)", lambda a: a["seconds"])
    for key in sorted({k for c in costs.values() for k in c}):
        row(key, lambda a, k=key: costs.get(a["label"], {}).get(k, "–"))
    for a in arms:
        if a.get("error"):
            lines += ["", f"**{a['label']} stopped early:** {a['error']}"]

    quiz_arms = [a for a in arms if a["quiz"]]
    lines += ["", "## Quiz questions, side by side", ""]
    for i in range(max((len(a["quiz"]) for a in quiz_arms), default=0)):
        lines += [f"### Question {i + 1}", ""]
        for a in quiz_arms:
            q = a["quiz"][i] if i < len(a["quiz"]) else None
            lines.append(f"**{a['label']}**" + (f" ({q['type']}, {q['go_id']})" if q else ""))
            if q:
                lines += _quote(q["text"])
                if q["options"]:
                    lines += [f"> - {o}" for o in q["options"]]
                lines += [f"> Keyed answer: {q['keyed']}", "", f"Scripted answer ({q['intended']}): {q['answer']}", "",
                          f"LEA graded: {'not graded' if not q['graded'] else ('correct' if q['correct'] else 'incorrect')}"
                          f" (score {q['score']}). Feedback: {q['explanation']}"]
            lines.append("")

    chat_arms = [a for a in arms if a["chat"]]
    if chat_arms:
        lines += ["## Chat, turn by turn", ""]
        for i in range(max(len(a["chat"]) for a in chat_arms)):
            first = next(a["chat"][i] for a in chat_arms if i < len(a["chat"]))
            lines += [f"### Turn {i + 1} ({first['kind'].replace('_', ' ')})", "", f"**Student:** {first['student']}", ""]
            for a in chat_arms:
                c = a["chat"][i] if i < len(a["chat"]) else None
                if c:
                    lines += [f"**{a['label']}**", "", *_quote(c["lea"]), "",
                              f"*retrieved: {', '.join(map(str, c['retrieved'])) or 'nothing'}*", ""]

    tutor_arms = [a for a in arms if a["tutor"]]
    if tutor_arms:
        lines += ["## Tutor, turn by turn", ""]
        for a in tutor_arms:
            lines += [f"**{a['label']} opening:**", "", *_quote(a["tutor"].get("opening")), ""]
        for i in range(max(len(a["tutor"].get("turns", [])) for a in tutor_arms)):
            first = next(a["tutor"]["turns"][i] for a in tutor_arms if i < len(a["tutor"]["turns"]))
            lines += [f"### Turn {i + 1} (scripted: {first['intended']})", ""]
            for a in tutor_arms:
                t = a["tutor"]["turns"][i] if i < len(a["tutor"]["turns"]) else None
                if t:
                    lines += [f"**{a['label']}**", "", f"Student: {t['student']}", "", *_quote(t["lea"]), "",
                              f"*objective {t['go_id']}; graded {t['graded']}, correct {t['correct']}*", ""]
    Path(path).write_text("\n".join(lines), encoding="utf-8")
    Path(path).with_suffix(".json").write_text(json.dumps({"arms": arms, "costs": costs}, indent=1, default=str),
                                               encoding="utf-8")


def openai_costs(meter: OpenAIMeter) -> Dict[str, Any]:
    return {"OpenAI calls": len(meter.calls), "OpenAI $": round(meter.usd, 4), "OpenAI models": meter.models()}


def bank_for(course: str = COURSE, path: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    return load_bank(course, path)
