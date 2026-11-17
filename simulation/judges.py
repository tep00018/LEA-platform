"""LLM judges (docs/simulation/PLAN.md, section 4).

- **Batched:** one call per tutor session (M16 checklist and M17 coherence for every
  tutor reply), one per quiz (M18 per item), one per chat sitting (M3 for the follow-up),
  and one per session for the M0a fidelity checks. ``--json-schema`` makes Claude return
  the declared shape; the reply is validated again here (every unit present, values from
  the allowed set). Invalid output is retried once, then recorded as **missing**. There
  are no default scores and no fallback judge.
- **Blind:** judges see only what the metric needs (the transcript, the retrieved
  content, the item, the reference answer). Never the profile, the hidden state, the
  intent, or LEA's internal scores. The one exception is the SC3 support unit, which shows
  the support level LEA chose for each reply because that is what is judged (never the
  simulator's state). ``unit_*`` builders take whitelisted
  fields from the saved events; the tests check the prompts.
- **Versioned rubrics** in ``simulation/rubrics/*.yaml``; every judgement records the
  rubric version, the judge model returned, and the repeat number.
- **Run once, judge many times:** everything here works from a run's ``events.jsonl``
  (``python -m simulation judge``), without calling LEA or OpenAI.
"""

from __future__ import annotations

import csv
import json
import math
import random
import threading
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import jsonschema
import yaml

from simulation import PACKAGE_DIR
from simulation.llm.claude_cli import ClaudeCallError

RUBRIC_DIR = PACKAGE_DIR / "rubrics"
YES_NO = {"type": "string", "enum": ["yes", "no"]}
SYSTEM_PROMPT = """You are a careful, consistent evaluator for a research study of an AI tutor. Apply the
rubric exactly as written, judge each numbered unit independently, and reply only with the JSON
the schema asks for. Never invent information that isn't shown."""


def load_rubrics(folder: Path = RUBRIC_DIR) -> Dict[str, Dict[str, Any]]:
    out = {}
    for path in sorted(Path(folder).glob("*.yaml")):
        rubric = yaml.safe_load(path.read_text(encoding="utf-8"))
        out[rubric["id"]] = rubric
    return out


def rubric_text(rubric: Dict[str, Any]) -> str:
    lines = [f"RUBRIC {rubric['id']} (version {rubric['version']}): {rubric['title']}",
             " ".join(str(rubric.get("instructions", "")).split())]
    for key, item in (rubric.get("items") or {}).items():
        lines += [f"- {key}: {item['question']}", f"    yes if: {item['yes_if']}", f"    no if: {item['no_if']}"]
        lines += [f"    example ({ex['answer']}): {ex['text']}" for ex in item["examples"]]
    for score, text in (rubric.get("scale") or {}).items():
        lines.append(f"- {score}: {text}")
    for ex in rubric.get("examples") or []:
        tag = ex.get("score", ex.get("label"))
        lines.append(f"  example ({tag}): {ex['text']}")
    if rubric.get("labels"):
        lines.append("Labels: " + ", ".join(rubric["labels"]))
    return "\n".join(lines)


def _clip(text: Any, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


# ---------------------------------------------------------------------------- units from saved events

def read_events(path: Path) -> List[Dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def unit_key(r: Dict[str, Any], mode: str) -> str:
    return f"{r['learner']}|w{r['week']}|r{r.get('round', 1)}|{mode}"


def build_units(events: List[Dict[str, Any]], lessons: Optional[Dict[int, str]] = None,
                bank: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, List[Dict]]:
    """Judge units from a run's events: tutor sessions, quizzes, chat sittings, fidelity sets.
    Only whitelisted fields are copied; the ``strata`` field (profile) is kept outside the
    prompt, for sampling."""
    openings = {unit_key(r, "tutor"): r for r in events if r.get("kind") == "tutor_start"}
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in events:
        if r.get("kind") == "turn":
            groups[unit_key(r, r["mode"])].append(r)
    units: Dict[str, List[Dict[str, Any]]] = {"tutor": [], "quiz": [], "chat": [], "fidelity": [], "support": []}
    for key, turns in groups.items():
        turns.sort(key=lambda t: t["turn"])
        first = turns[0]
        meta = {"key": key, "learner": first["learner"], "week": first["week"], "round": first.get("round", 1),
                "profile": first.get("profile")}
        mode = first["mode"]
        if mode == "tutor":
            opening = openings.get(key, {})
            exchanges, previous = [], opening.get("message") or ""
            for t in turns:
                if not t.get("student_text") or not (t.get("lea") or {}).get("message"):
                    continue
                content = "\n".join(x.get("content", "") for x in t.get("retrieval") or [])
                exchanges.append({"id": t["turn"], "tutor_before": previous, "student": t["student_text"],
                                  "tutor": t["lea"]["message"], "content": content})
                previous = t["lea"]["message"]
            if exchanges:
                units["tutor"].append({**meta, "opening": opening.get("message") or "", "exchanges": exchanges})
                support = _support_exchanges(exchanges,
                                             [x for x in turns if x.get("student_text") and (x.get("lea") or {}).get("message")])
                if support:
                    units["support"].append({**meta, "key": key.replace("|tutor", "|support"), "exchanges": support})
            answers = [{"id": f"t{e['id']}", "question": e["tutor_before"], "answer": e["student"],
                        "reference": _reference(t, bank), "passage": _passage(t, bank)}
                       for e, t in zip(exchanges, [x for x in turns if x.get("student_text") and
                                                   (x.get("lea") or {}).get("message")])
                       if (t.get("intent") or {}).get("kind") == "answer"]
            if answers:
                units["fidelity"].append({**meta, "key": key.replace("|tutor", "|fid-tutor"), "answers": answers})
        elif mode == "quiz":
            items = [{"id": t["turn"], "go": t.get("go_id"), "objective": (t.get("question") or {}).get("skill_name"),
                      "type": (t.get("question") or {}).get("type"), "text": (t.get("question") or {}).get("text"),
                      "options": (t.get("question") or {}).get("options"),
                      "correct": (t.get("question") or {}).get("correct_answer")
                      or (t.get("question") or {}).get("sample_answer")} for t in turns if t.get("question")]
            if items:
                units["quiz"].append({**meta, "items": items, "content": (lessons or {}).get(first["week"], "")})
            free = [{"id": f"q{t['turn']}", "question": (t.get("question") or {}).get("text"), "answer": t["student_text"],
                     "reference": (t.get("question") or {}).get("correct_answer")
                     or (t.get("question") or {}).get("sample_answer") or _reference(t, bank)}
                    for t in turns if t.get("student_text") and t.get("qtype") in ("fill_in", "open_ended")]
            if free:
                units["fidelity"].append({**meta, "key": key.replace("|quiz", "|fid-quiz"), "answers": free})
        elif mode == "chat":
            follow = []
            for i, t in enumerate(turns):
                if t.get("follow_up") and i > 0:
                    prev = turns[i - 1]
                    follow.append({"id": t["turn"], "earlier_question": prev.get("student_text"),
                                   "earlier_answer": (prev.get("lea") or {}).get("message"),
                                   "follow_up": t.get("student_text"), "answer": (t.get("lea") or {}).get("message")})
            if follow:
                units["chat"].append({**meta, "follow_ups": follow})
    for kind in units:
        units[kind].sort(key=lambda u: u["key"])
    return units


def _support_exchanges(exchanges: List[Dict[str, Any]], turns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Exchanges with the support LEA chose for each reply, and the last five exchanges as context.
    This kind of unit deliberately shows LEA's own support decision (it is what is judged) and
    nothing about the simulator: no profile, hidden state or intent."""
    out = []
    for i, (e, t) in enumerate(zip(exchanges, turns)):
        answer = next((d["payload"] for d in t.get("decisions") or [] if d.get("type") == "answer"), None) or {}
        cog = next((d["payload"] for d in t.get("decisions") or [] if d.get("type") == "cognitive_decision"), None) or {}
        level = answer.get("scaffolding_intensity")
        if not level:
            continue
        recent = [{"tutor": x["tutor_before"], "student": x["student"]} for x in exchanges[max(0, i - 4):i + 1]]
        out.append({"id": e["id"], "recent": recent, "reply": e["tutor"], "support_level": level,
                    "strategy": answer.get("scaffolding_strategy"),
                    "intervention": cog.get("intervention_type"), "difficulty": cog.get("difficulty_adjustment")})
    return out


def _reference(turn: Dict[str, Any], bank: Optional[Dict[str, Dict[str, Any]]]) -> str:
    """The bank's reference answer for the turn's objective (never anything from LEA)."""
    return turn.get("reference_answer") or ((bank or {}).get(turn.get("go_id")) or {}).get("reference_answer", "")


def _passage(turn: Dict[str, Any], bank: Optional[Dict[str, Dict[str, Any]]]) -> str:
    return ((bank or {}).get(turn.get("go_id")) or {}).get("source_quote", "")


# ---------------------------------------------------------------------------- prompts and schemas

def tutor_prompt(unit: Dict[str, Any], rubrics: Dict[str, Dict[str, Any]]) -> str:
    parts = [rubric_text(rubrics["M16"]), "", rubric_text(rubrics["M17"]), "",
             "For EVERY numbered tutor reply below, give the five M16 answers and an M17 coherence score (1-5).",
             "", f"Tutor's opening message: {_clip(unit['opening'], 1500)}", ""]
    for e in unit["exchanges"]:
        parts += [f"--- Exchange {e['id']} ---", f"Student: {_clip(e['student'], 1500)}",
                  f"Course content retrieved for this reply: {_clip(e['content'], 2500) or '(none)'}",
                  f"TUTOR REPLY {e['id']}: {_clip(e['tutor'], 3000)}", ""]
    return "\n".join(parts)


def tutor_schema(unit: Dict[str, Any], rubrics) -> Dict[str, Any]:
    items = {k: YES_NO for k in rubrics["M16"]["items"]}
    return {"type": "object", "additionalProperties": False, "required": ["replies"], "properties": {"replies": {
        "type": "array", "items": {"type": "object", "additionalProperties": False,
                                   "required": ["id", *items, "coherence"],
                                   "properties": {"id": {"type": "integer"}, **items,
                                                  "coherence": {"type": "integer", "minimum": 1, "maximum": 5}}}}}}


def quiz_prompt(unit: Dict[str, Any], rubrics) -> str:
    parts = [rubric_text(rubrics["M18"]), "", "Answer the five M18 items for EVERY numbered quiz item below.", "",
             f"Week's course content: {_clip(unit['content'], 12000) or '(not available)'}", ""]
    for it in unit["items"]:
        options = "; ".join(it["options"] or []) or "(no options)"
        parts += [f"--- QUIZ ITEM {it['id']} ({it['type']}) ---", f"Objective: {it['objective'] or it['go']}",
                  f"Question: {_clip(it['text'], 1500)}", f"Options: {options}", f"Keyed answer: {it['correct']}", ""]
    return "\n".join(parts)


def quiz_schema(unit, rubrics) -> Dict[str, Any]:
    items = {k: YES_NO for k in rubrics["M18"]["items"]}
    return {"type": "object", "additionalProperties": False, "required": ["items"], "properties": {"items": {
        "type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["id", *items],
                                   "properties": {"id": {"type": "integer"}, **items}}}}}


def chat_prompt(unit: Dict[str, Any], rubrics) -> str:
    parts = [rubric_text(rubrics["M3"]), "", "Answer M3 for EVERY numbered follow-up below.", ""]
    for f in unit["follow_ups"]:
        parts += [f"--- FOLLOW-UP {f['id']} ---", f"Earlier question: {_clip(f['earlier_question'], 1000)}",
                  f"Earlier answer: {_clip(f['earlier_answer'], 2500)}", f"Follow-up: {_clip(f['follow_up'], 500)}",
                  f"Answer to the follow-up: {_clip(f['answer'], 2500)}", ""]
    return "\n".join(parts)


def chat_schema(unit, rubrics) -> Dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "required": ["follow_ups"], "properties": {"follow_ups": {
        "type": "array", "items": {"type": "object", "additionalProperties": False,
                                   "required": ["id", "resolves_reference"],
                                   "properties": {"id": {"type": "integer"}, "resolves_reference": YES_NO}}}}}


def support_prompt(unit: Dict[str, Any], rubrics) -> str:
    parts = [rubric_text(rubrics["SC3"]), "", "Label EVERY numbered exchange below.", ""]
    for e in unit["exchanges"]:
        parts.append(f"--- Exchange {e['id']} ---")
        for n, x in enumerate(e["recent"], 1):
            parts += [f"[{n}] Tutor: {_clip(x['tutor'], 700)}", f"[{n}] Student: {_clip(x['student'], 700)}"]
        parts += [f"Support chosen for the reply: level {e['support_level']}; strategy {e['strategy']}; "
                  f"intervention {e['intervention']}; difficulty {e['difficulty']}",
                  f"Tutor's reply: {_clip(e['reply'], 1200)}", ""]
    return "\n".join(parts)


def support_schema(unit, rubrics) -> Dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "required": ["exchanges"], "properties": {"exchanges": {
        "type": "array", "items": {"type": "object", "additionalProperties": False,
                                   "required": ["id", "support_fit", "intervention_fit"],
                                   "properties": {"id": {"type": "integer"},
                                                  "support_fit": {"type": "string", "enum": rubrics["SC3"]["labels"]},
                                                  "intervention_fit": YES_NO}}}}}


def fidelity_prompt(unit: Dict[str, Any], rubrics) -> str:
    parts = [rubric_text(rubrics["M0a"]), "", "Label EVERY numbered student answer below.", ""]
    for a in unit["answers"]:
        parts += [f"--- ANSWER {a['id']} ---", f"Question: {_clip(a['question'], 1500)}",
                  f"Reference answer: {_clip(a['reference'], 800) or '(none given)'}",
                  *([f"Lesson passage: {_clip(a['passage'], 800)}"] if a.get("passage") else []),
                  f"Student's answer: {_clip(a['answer'], 1500)}", ""]
    return "\n".join(parts)


def fidelity_schema(unit, rubrics) -> Dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "required": ["answers"], "properties": {"answers": {
        "type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["id", "label"],
                                   "properties": {"id": {"type": "string"},
                                                  "label": {"type": "string", "enum": rubrics["M0a"]["labels"]}}}}}}


KINDS = {
    "support": {"metrics": ["SC3"], "prompt": support_prompt, "schema": support_schema, "list": "exchanges",
                "ids": lambda u: [e["id"] for e in u["exchanges"]]},
    "tutor": {"metrics": ["M16", "M17"], "prompt": tutor_prompt, "schema": tutor_schema, "list": "replies",
              "ids": lambda u: [e["id"] for e in u["exchanges"]]},
    "quiz": {"metrics": ["M18"], "prompt": quiz_prompt, "schema": quiz_schema, "list": "items",
             "ids": lambda u: [i["id"] for i in u["items"]]},
    "chat": {"metrics": ["M3"], "prompt": chat_prompt, "schema": chat_schema, "list": "follow_ups",
             "ids": lambda u: [f["id"] for f in u["follow_ups"]]},
    "fidelity": {"metrics": ["M0a"], "prompt": fidelity_prompt, "schema": fidelity_schema, "list": "answers",
                 "ids": lambda u: [a["id"] for a in u["answers"]]},
}


# ---------------------------------------------------------------------------- judging

def validate(data: Any, schema: Dict[str, Any], list_key: str, ids: List[Any]) -> Optional[str]:
    """None if the reply is complete and valid, else what's wrong."""
    try:
        jsonschema.validate(data, schema)
    except jsonschema.ValidationError as e:
        return f"schema: {e.message}"
    got = [row["id"] for row in data[list_key]]
    if sorted(map(str, got)) != sorted(map(str, ids)):
        return f"units: expected {ids}, got {got}"
    return None


class Judge:
    def __init__(self, client, model: str, effort: Optional[str] = "low", rubrics=None, role: str = "judge",
                 max_thinking_tokens: Optional[int] = None):
        self.client = client
        self.model = model
        self.effort = effort
        self.max_thinking_tokens = max_thinking_tokens  # None: the model's default (judging may benefit)
        self.rubrics = rubrics or load_rubrics()
        self.role = role

    def judge(self, kind: str, unit: Dict[str, Any], repeat: int = 0) -> Dict[str, Any]:
        """One batched call (retried once if invalid). Returns a judgement record; values
        None when missing."""
        spec = KINDS[kind]
        prompt = spec["prompt"](unit, self.rubrics)
        schema = spec["schema"](unit, self.rubrics)
        ids = spec["ids"](unit)
        record = {"kind": kind, "unit": unit["key"], "learner": unit["learner"], "week": unit["week"],
                  "round": unit["round"], "metrics": spec["metrics"], "judge_role": self.role,
                  "model_requested": self.model, "repeat": repeat,
                  "rubric_versions": {m: self.rubrics[m]["version"] for m in spec["metrics"]},
                  "values": None, "missing_reason": None, "attempts": 0, "model": None, "cost_usd": 0.0}
        problem = None
        for attempt in range(2):
            record["attempts"] = attempt + 1
            text = prompt if not problem else prompt + f"\n\nYour previous reply was invalid ({problem}). Answer every unit."
            try:
                result = self.client.call(text, system_prompt=SYSTEM_PROMPT, model=self.model, role=self.role,
                                          json_schema=schema, effort=self.effort,
                                          max_thinking_tokens=self.max_thinking_tokens)
            except ClaudeCallError as e:
                problem = f"call failed: {str(e)[:200]}"
                continue
            record["model"] = result.model
            record["cost_usd"] = round(record["cost_usd"] + (result.cost_usd or 0), 6)
            data = result.structured
            if data is None:
                try:
                    data = json.loads(result.text)
                except (TypeError, json.JSONDecodeError):
                    data = None
            problem = validate(data, schema, spec["list"], ids) if data is not None else "no JSON"
            if problem is None:
                record["values"] = {str(row["id"]): {k: v for k, v in row.items() if k != "id"}
                                    for row in data[spec["list"]]}
                return record
        record["missing_reason"] = problem
        return record


class JudgementWriter:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def write(self, record: Dict[str, Any]) -> None:
        with self._lock, open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------- reliability samples

def stratified_sample(units: List[Dict[str, Any]], frac: float, seed: int, strata=lambda u: u.get("profile")
                      ) -> List[Dict[str, Any]]:
    """At least one unit per stratum, about ``frac`` of each, chosen with ``seed``."""
    by: Dict[Any, List[Dict[str, Any]]] = defaultdict(list)
    for u in units:
        by[strata(u)].append(u)
    rng = random.Random(seed)
    out = []
    for key in sorted(by, key=str):
        group = sorted(by[key], key=lambda u: u["key"])
        out += rng.sample(group, max(1, math.ceil(frac * len(group))))
    return sorted(out, key=lambda u: u["key"])


def plan_judging(units: Dict[str, List[Dict]], *, tutor_share: float = 1.0, repeat_frac: float = 0.10,
                 repeats: int = 3, second_frac: float = 0.10, seed: int = 0,
                 support_share: float = 0.20) -> List[Tuple[str, Dict, int, str]]:
    """(kind, unit, repeat, role) for every judge call: the main pass (a stratified share of
    tutor sessions if ``tutor_share`` < 1), ``repeats`` - 1 extra passes on a 10% sample
    (M20), and one second-judge pass on a 10% sample (M21)."""
    jobs = []
    for kind, group in units.items():
        main = stratified_sample(group, tutor_share, seed) if (kind == "tutor" and tutor_share < 1) else group
        if kind == "support" and support_share < 1:  # judged on a sample of sessions; a session is judged whole
            main = stratified_sample(group, support_share, seed + 3)
        jobs += [(kind, u, 0, "judge") for u in main]
        for u in stratified_sample(main, repeat_frac, seed + 1) if main else []:
            jobs += [(kind, u, r, "judge") for r in range(1, repeats)]
        for u in stratified_sample(main, second_frac, seed + 2) if main else []:
            jobs.append((kind, u, 0, "second_judge"))
    return jobs


# ---------------------------------------------------------------------------- the labelling sheet (M22)

SHEET_COLUMNS = ["item_id", "kind", "context", "questions", "label_1", "label_2", "label_3", "label_4", "label_5",
                 "label_coherence", "notes"]


def labelling_sheet(units: Dict[str, List[Dict]], path: Path, *, tutor: int = 60, quiz: int = 40, chat: int = 40,
                    seed: int = 7, rubrics=None) -> int:
    """A CSV for the owner, in random order, with no judge answers. Returns the row count."""
    rubrics = rubrics or load_rubrics()
    rng = random.Random(seed)
    rows = []
    tutor_items = [(u, e) for u in units["tutor"] for e in u["exchanges"]]
    for u, e in rng.sample(tutor_items, min(tutor, len(tutor_items))):
        rows.append({"item_id": f"{u['key']}#{e['id']}", "kind": "tutor_turn",
                     "context": f"TUTOR BEFORE: {_clip(e['tutor_before'], 1200)}\nSTUDENT: {_clip(e['student'], 800)}\n"
                                f"CONTENT: {_clip(e['content'], 1500)}\nTUTOR REPLY: {_clip(e['tutor'], 2000)}",
                     "questions": "; ".join(f"{i + 1}={k}" for i, k in enumerate(rubrics["M16"]["items"])) +
                                  "; coherence=1-5 (M17)"})
    quiz_items = [(u, i) for u in units["quiz"] for i in u["items"]]
    for u, i in rng.sample(quiz_items, min(quiz, len(quiz_items))):
        rows.append({"item_id": f"{u['key']}#{i['id']}", "kind": "quiz_item",
                     "context": f"OBJECTIVE: {i['objective']}\nQUESTION ({i['type']}): {i['text']}\n"
                                f"OPTIONS: {'; '.join(i['options'] or [])}\nKEYED ANSWER: {i['correct']}",
                     "questions": "; ".join(f"{n + 1}={k}" for n, k in enumerate(rubrics["M18"]["items"]))})
    chat_items = [(u, f) for u in units["chat"] for f in u["follow_ups"]]
    for u, f in rng.sample(chat_items, min(chat, len(chat_items))):
        rows.append({"item_id": f"{u['key']}#{f['id']}", "kind": "chat_follow_up",
                     "context": f"EARLIER QUESTION: {f['earlier_question']}\nEARLIER ANSWER: {_clip(f['earlier_answer'], 1500)}\n"
                                f"FOLLOW-UP: {f['follow_up']}\nANSWER: {_clip(f['answer'], 1500)}",
                     "questions": "1=resolves_reference"})
    rng.shuffle(rows)
    # Opaque item ids: the unit keys name the learner (and so the profile); the owner labels
    # blind, and the mapping stays in a separate key file used only for scoring.
    import hashlib

    key = {}
    for row in rows:
        code = "L" + hashlib.sha256(f"{seed}:{row['item_id']}".encode()).hexdigest()[:10]
        key[code] = row["item_id"]
        row["item_id"] = code
    Path(path).with_name(Path(path).stem + "_key.json").write_text(json.dumps(key, indent=1), encoding="utf-8")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=SHEET_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row.get(c, "") for c in SHEET_COLUMNS})
    return len(rows)


def read_labels(path: Path) -> Dict[str, Dict[str, str]]:
    """The owner's labels back from the sheet, keyed by the real item (unit key#id) via the
    key file: {item: {label_1: 'yes', ...}} (blank cells dropped)."""
    key = json.loads(Path(path).with_name(Path(path).stem + "_key.json").read_text(encoding="utf-8"))
    with open(path, newline="", encoding="utf-8") as fh:
        return {key[row["item_id"]]: {k: v.strip().lower() for k, v in row.items()
                                      if k.startswith("label_") and v and v.strip()}
                for row in csv.DictReader(fh)}


def run_jobs(jobs: Iterable[Tuple[str, Dict, int, str]], judges: Dict[str, Judge], writer: JudgementWriter,
             concurrency: int = 2) -> List[Dict[str, Any]]:
    from concurrent.futures import ThreadPoolExecutor

    def one(job):
        kind, unit, repeat, role = job
        record = judges[role].judge(kind, unit, repeat)
        writer.write(record)
        return record

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        return list(pool.map(one, list(jobs)))


# ---------------------------------------------------------------------------- judging a run

def week_lessons(data_dir: Path, course: str) -> Dict[int, str]:
    """Each week's lecture text (the content M18 items are judged against)."""
    import re

    out: Dict[int, List[str]] = defaultdict(list)
    for md in sorted((Path(data_dir) / "md_docs" / course).glob("Week*-Lecture*.md")):
        m = re.match(r"Week(\d+)-", md.name)
        if m:
            out[int(m.group(1))].append(md.read_text(encoding="utf-8"))
    return {w: "\n\n".join(texts) for w, texts in out.items()}


def judge_run(run_dir: Path, config: Dict[str, Any], client, bank: Dict[str, Dict[str, Any]], *,
              pass_id: str, tutor_share: float = 1.0, support_share: float = 0.20, reliability: bool = True,
              kinds: Optional[List[str]] = None,
              sheet: bool = True) -> Dict[str, Any]:
    """Judge a finished run from its saved events (no LEA or OpenAI calls). Appends to
    ``judgements.jsonl`` (each record tagged with ``pass_id``) and writes the labelling sheet."""
    run_dir = Path(run_dir)
    events = read_events(run_dir / "events.jsonl")
    units = build_units(events, week_lessons(run_dir / "data", config["course"]), bank)
    rubrics = load_rubrics()
    c = config["claude"]
    judges = {"judge": Judge(client, c["judge_model"], c["judge_effort"], rubrics, role="judge",
                             max_thinking_tokens=c.get("judge_max_thinking_tokens")),
              "second_judge": Judge(client, c["second_judge_model"], c["judge_effort"], rubrics, role="second_judge",
                                    max_thinking_tokens=c.get("judge_max_thinking_tokens"))}
    jobs = plan_judging(units, tutor_share=tutor_share, repeat_frac=0.10 if reliability else 0.0,
                        repeats=3 if reliability else 1, second_frac=0.10 if reliability else 0.0,
                        seed=int(config["seed"]), support_share=support_share)
    if kinds:
        jobs = [j for j in jobs if j[0] in kinds]
    if not reliability:
        jobs = [j for j in jobs if j[2] == 0 and j[3] == "judge"]
    writer = JudgementWriter(run_dir / "judgements.jsonl")

    class Tagged(JudgementWriter):
        def write(self, record):
            writer.write({**record, "pass_id": pass_id})

    records = run_jobs(jobs, judges, Tagged(writer.path), concurrency=int(c["concurrency"]))
    rows = 0
    if sheet:
        rows = labelling_sheet(units, run_dir / "labelling_sheet.csv", seed=int(config["seed"]), rubrics=rubrics)
    return {"jobs": len(jobs), "missing": sum(1 for r in records if r["values"] is None),
            "units": {k: len(v) for k, v in units.items()}, "sheet_rows": rows,
            "api_equivalent_usd": round(sum(r["cost_usd"] for r in records), 4)}
