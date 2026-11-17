"""The AIML101 question bank (docs/simulation/PLAN.md, section 1; built once, committed).

For every granular objective (GO): three learner questions for Chat (the third a
follow-up that refers back to one of the first two), a reference answer, the source lesson
file (named as the vector store names it, so retrieval can be checked against it), a
short supporting quote from that file, and 2-3 common misconceptions, seeded from the
wrong options of the ML-for-Beginners / AI-for-Beginners quizzes imported in Phase 6.

Generated with Claude (``claude.bank_model``, default ``sonnet``) through the researcher's
subscription, one call per week (a large week is split by learning objective), with a
JSON schema. Each call's output is checked (every GO present, three questions with one
follow-up, a known source file, the quote found in that file, distinct misconceptions);
a call that fails is retried once with the problems listed, then the build stops.

The prompt structure follows ``data_foundation/generate_ragas_questions.py`` (course,
week, LO and GO context), with the lesson text added so answers are grounded.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from simulation.llm.claude_cli import ClaudeCallError, ClaudeCLI

PROMPT_VERSION = "bank-v1"
SPLIT_ABOVE_TOKENS = 20_000   # a week's lesson text above this is sent in LO groups
MAX_GOS_PER_CALL = 12

SYSTEM_PROMPT = """You write evaluation material for a research simulation of an AI tutor used in an
introductory course on AI and machine learning. Everything you write must be grounded in the
lesson text you are given. Write the way real students write: plain words, sometimes unsure,
never quoting the lesson. Reply only with the JSON the schema asks for."""

SCHEMA = {
    "type": "object",
    "required": ["entries"],
    "additionalProperties": False,
    "properties": {"entries": {"type": "array", "items": {
        "type": "object",
        "additionalProperties": False,
        "required": ["go_id", "questions", "reference_answer", "source_file", "source_quote", "misconceptions"],
        "properties": {
            "go_id": {"type": "string"},
            "questions": {"type": "array", "minItems": 3, "maxItems": 3, "items": {
                "type": "object", "additionalProperties": False, "required": ["text", "kind", "follows"],
                "properties": {"text": {"type": "string"},
                               "kind": {"type": "string", "enum": ["question", "follow_up"]},
                               "follows": {"type": ["integer", "null"]}}}},
            "reference_answer": {"type": "string"},
            "source_file": {"type": "string"},
            "source_quote": {"type": "string"},
            "misconceptions": {"type": "array", "minItems": 2, "maxItems": 3, "items": {
                "type": "object", "additionalProperties": False, "required": ["text", "basis"],
                "properties": {"text": {"type": "string"},
                               "basis": {"type": "string", "enum": ["quiz_distractor", "lesson", "common_error"]}}}},
        }}}},
}

INSTRUCTIONS = """Course: {course}. Week {week}: {week_title}.

For EACH granular objective (GO) listed below, write:
1. "questions": exactly three questions a student might type into the course's chat assistant
   about this GO. Questions 1 and 2 ("kind": "question", "follows": null) stand on their own
   and must be answerable from the lesson text. Question 3 ("kind": "follow_up") refers back to
   question 1 or 2 without repeating it, the way a student continues a conversation (for
   example "can you give me an example of that?" or "why does that matter?"); set "follows"
   to 0 or 1 for the question it continues.
2. "reference_answer": a correct answer to question 1 in 2-4 sentences, using only the lesson.
3. "source_file": the ONE lesson file that best supports the answer, copied exactly from the
   list of file names below.
4. "source_quote": a short passage (8-40 words) copied word for word from that file that
   supports the answer.
5. "misconceptions": 2 or 3 wrong beliefs a student could plausibly hold about this GO,
   each written as the belief itself (not as a question). Where a quiz item below has a
   wrong option that fits this GO, turn it into a misconception and mark "basis":
   "quiz_distractor"; otherwise use "lesson" (a confusion the lesson warns about) or
   "common_error".

Granular objectives:
{gos}

Quiz items from this week (their GO tags are automatic and may be wrong; use them only as
seeds for misconceptions):
{quiz}

Lesson files (name, then full text):
{lessons}
"""


# ---------------------------------------------------------------------------- inputs

def load_inputs(data_dir: Path, course: str) -> Dict[str, Any]:
    """KC rows, lesson texts under their vector-store names, and the imported quiz items."""
    from src.onboarding import kc_model as K

    model = json.loads((data_dir / "kc_models" / course / f"kc_model_{course}.json").read_text(encoding="utf-8"))
    gos = K.gos_of(model)
    rows = [{**r, "cognitive_level": gos[r["go_id"]].get("cognitive_level"),
             "description": gos[r["go_id"]].get("description", "")} for r in K.rows_from_model(model)]
    week_titles = {int(r["week"]): r.get("week_title", "") for r in rows}
    sources = json.loads((data_dir / "metadata" / f"doc_metadata_{course}.json").read_text(encoding="utf-8"))
    by_stem = {Path(name).stem: name for name in sources}
    lessons: Dict[int, Dict[str, str]] = {}
    for md in sorted((data_dir / "md_docs" / course).glob("*.md")):
        m = re.match(r"Week(\d+)-", md.name)
        if not m:
            continue
        name = by_stem.get(md.stem, md.name)
        lessons.setdefault(int(m.group(1)), {})[name] = md.read_text(encoding="utf-8")
    quiz_path = data_dir / "course_sources" / course / "question_bank.json"
    quiz = json.loads(quiz_path.read_text(encoding="utf-8"))["questions"] if quiz_path.exists() else []
    return {"rows": rows, "week_titles": week_titles, "lessons": lessons, "quiz": quiz,
            "kc_model_sha256": hashlib.sha256(json.dumps(model, sort_keys=True).encode()).hexdigest()}


def plan_calls(inputs: Dict[str, Any]) -> List[Dict[str, Any]]:
    """One call per week; a week with long lessons or many GOs is split by LO."""
    calls = []
    for week in sorted(inputs["lessons"]):
        rows = [r for r in inputs["rows"] if int(r["week"]) == week]
        if not rows:
            continue
        tokens = sum(len(t) for t in inputs["lessons"][week].values()) // 4
        if tokens <= SPLIT_ABOVE_TOKENS and len(rows) <= MAX_GOS_PER_CALL:
            calls.append({"week": week, "rows": rows})
            continue
        groups: List[List[Dict[str, Any]]] = [[]]
        for lo in sorted({r["lo_id"] for r in rows}):
            lo_rows = [r for r in rows if r["lo_id"] == lo]
            if groups[-1] and len(groups[-1]) + len(lo_rows) > (len(rows) + 1) // 2:
                groups.append([])
            groups[-1].extend(lo_rows)
        calls.extend({"week": week, "rows": g} for g in groups if g)
    return calls


def prompt_for(call: Dict[str, Any], inputs: Dict[str, Any], course: str) -> str:
    week = call["week"]
    gos = "\n".join(f"- {r['go_id']} ({r.get('cognitive_level') or 'level not given'}), LO {r['lo_id']} "
                    f"\"{r.get('lo_title', '')}\": {r['skill_name']}. {r.get('description', '')}".rstrip()
                    for r in call["rows"])
    items = [q for q in inputs["quiz"] if int(q.get("week", 0)) == week]
    quiz = "\n".join(f"- [{q.get('go_id')}] {q['text']} Options: " +
                     "; ".join(f"{'(correct) ' if i == q.get('correct_index') else ''}{o}"
                               for i, o in enumerate(q.get("options") or []))
                     for q in items) or "(none this week)"
    lessons = "\n\n".join(f"=== {name} ===\n{text}" for name, text in sorted(inputs["lessons"][week].items()))
    return INSTRUCTIONS.format(course=course, week=week, week_title=inputs["week_titles"].get(week, ""),
                               gos=gos, quiz=quiz, lessons=lessons)


# ---------------------------------------------------------------------------- checking

def _norm(text: str) -> str:
    """Letters and digits only, so markdown, punctuation and quote styles don't matter."""
    return re.sub(r"\s+", " ", re.sub(r"[^0-9a-z]+", " ", (text or "").lower())).strip()


QUOTE_PROBLEM = "source_quote is not copied word for word"


def check_entries(entries: Any, call: Dict[str, Any], lessons: Dict[str, str]) -> List[str]:
    problems: List[str] = []
    if not isinstance(entries, list):
        return ["The reply has no list of entries."]
    wanted = {r["go_id"] for r in call["rows"]}
    got = [e.get("go_id") for e in entries if isinstance(e, dict)]
    if set(got) != wanted or len(got) != len(wanted):
        problems.append(f"GOs must be exactly {sorted(wanted)}; got {got}.")
    for e in entries:
        if not isinstance(e, dict):
            continue
        g = e.get("go_id")
        qs = e.get("questions") or []
        kinds = [q.get("kind") for q in qs]
        if kinds != ["question", "question", "follow_up"] or qs[2].get("follows") not in (0, 1):
            problems.append(f"{g}: questions must be two questions then one follow_up with follows 0 or 1.")
        if len({_norm(q.get("text", "")) for q in qs}) != len(qs) or any(len(q.get("text", "")) < 8 for q in qs):
            problems.append(f"{g}: the three questions must be distinct and complete.")
        source = e.get("source_file")
        if source not in lessons:
            problems.append(f"{g}: source_file {source!r} is not one of the lesson files.")
        else:
            quote = _norm(e.get("source_quote", ""))
            if len(quote.split()) < 5 or quote not in _norm(lessons[source]):
                problems.append(f"{g}: {QUOTE_PROBLEM} from {source}.")
        mis = [_norm(m.get("text", "")) for m in e.get("misconceptions") or []]
        if not 2 <= len(mis) <= 3 or len(set(mis)) != len(mis):
            problems.append(f"{g}: needs 2-3 distinct misconceptions.")
        if len((e.get("reference_answer") or "").split()) < 12:
            problems.append(f"{g}: the reference answer is too short.")
    return problems


def _entries(result) -> Any:
    data = result.structured
    if data is None:
        try:
            data = json.loads(result.text)
        except (TypeError, json.JSONDecodeError):
            return None
    return data.get("entries") if isinstance(data, dict) else None


# ---------------------------------------------------------------------------- the build

def build(client: ClaudeCLI, data_dir: Path, course: str, model: str, effort: Optional[str] = "medium",
          concurrency: int = 2, checkpoint_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Build the bank. Each call's accepted entries are saved to ``checkpoint_dir`` as soon as
    they pass, and reused on the next build, so a failure never throws away finished weeks.

    A call is retried once with its problems listed. After the retry, entries whose only
    problem is a quote not found in the source file are kept and flagged ``needs_review``
    for the researcher's spot check; any other problem leaves that call unfinished, the others
    finish, and the build raises at the end (a rerun redoes only what is missing)."""
    inputs = load_inputs(data_dir, course)
    calls = plan_calls(inputs)
    if checkpoint_dir is not None:
        Path(checkpoint_dir).mkdir(parents=True, exist_ok=True)

    def saved(key: str) -> Optional[Dict[str, Any]]:
        path = Path(checkpoint_dir) / f"{key}.json" if checkpoint_dir else None
        return json.loads(path.read_text(encoding="utf-8")) if path and path.exists() else None

    def run(item) -> Tuple[Dict[str, Any], Optional[List[Dict[str, Any]]]]:
        index, call = item
        key = f"week{call['week']:02d}-{index}"
        wanted = sorted(r["go_id"] for r in call["rows"])
        done = saved(key)
        if done and sorted(e["go_id"] for e in done["entries"]) == wanted:
            return {**done["record"], "reused": True}, done["entries"]
        lessons = inputs["lessons"][call["week"]]
        prompt = prompt_for(call, inputs, course)
        record = {"key": key, "week": call["week"], "gos": wanted, "attempts": []}
        entries, problems = None, ["not attempted"]
        for attempt in range(2):
            try:
                result = client.call(prompt, system_prompt=SYSTEM_PROMPT, model=model, role="bank",
                                     json_schema=SCHEMA, effort=effort)
            except ClaudeCallError as e:
                record["attempts"].append({"error": str(e)[:300]})
                continue
            entries = _entries(result)
            problems = check_entries(entries, call, lessons)
            record["attempts"].append({"model": result.model, "cost_usd": result.cost_usd,
                                       "usage": {k: result.usage.get(k) for k in (
                                           "input_tokens", "output_tokens", "cache_read_input_tokens",
                                           "cache_creation_input_tokens")},
                                       "problems": problems,
                                       "claude_code_version": result.init.get("claude_code_version")})
            if not problems:
                break
            prompt = prompt_for(call, inputs, course) + (
                "\n\nYour previous reply had these problems; fix all of them:\n- " + "\n- ".join(problems[:30]))
        quote_only = bool(problems) and entries is not None and all(QUOTE_PROBLEM in p for p in problems)
        if problems and not quote_only:
            record["failed"] = problems
            return record, None
        if quote_only:
            flagged = {p.split(":")[0] for p in problems}
            for e in entries:
                if e.get("go_id") in flagged:
                    e["needs_review"] = ["quote not found in the source file"]
        if checkpoint_dir is not None:
            (Path(checkpoint_dir) / f"{key}.json").write_text(
                json.dumps({"record": record, "entries": entries}, indent=2, ensure_ascii=False), encoding="utf-8")
        return record, entries

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        results = list(pool.map(run, list(enumerate(calls))))
    failed = [rec for rec, found in results if found is None]
    if failed:
        raise RuntimeError("Unfinished (the finished weeks are saved; building again redoes only these): " +
                           "; ".join(f"week {r['week']} {r['gos'][0]}..: {r['failed'][:3]}" for r in failed))

    rows = {r["go_id"]: r for r in inputs["rows"]}
    entries = []
    for _, found in results:
        for e in found:
            r = rows[e["go_id"]]
            entry = {"go_id": e["go_id"], "lo_id": r["lo_id"], "week": int(r["week"]),
                     "skill_name": r["skill_name"], "questions": e["questions"],
                     "reference_answer": e["reference_answer"].strip(), "source_file": e["source_file"],
                     "source_quote": e["source_quote"].strip(), "misconceptions": e["misconceptions"]}
            if e.get("needs_review"):
                entry["needs_review"] = e["needs_review"]
            entries.append(entry)
    entries.sort(key=lambda e: e["go_id"])
    attempts = [a for rec, _ in results for a in rec["attempts"]]
    models = sorted({a["model"] for a in attempts if a.get("model")})
    return {
        "course": course,
        "prompt_version": PROMPT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "generator": {"tool": "claude -p (subscription)", "model_alias": model, "models": models, "effort": effort,
                      "claude_code_version": next((a.get("claude_code_version") for a in attempts
                                                   if a.get("claude_code_version")), None)},
        "kc_model_sha256": inputs["kc_model_sha256"],
        "calls": [rec for rec, _ in results],
        "api_equivalent_usd": round(sum(a.get("cost_usd") or 0 for a in attempts), 4),
        "needs_review": [e["go_id"] for e in entries if e.get("needs_review")],
        "spot_check": {"status": "pending", "sample": spot_check_sample(entries)},
        "entries": entries,
    }


def spot_check_sample(entries: List[Dict[str, Any]], n: int = 20, seed: int = 20260925) -> List[str]:
    """A seeded sample of GOs for the researcher's spot check, spread across weeks."""
    ids = sorted(e["go_id"] for e in entries)
    return sorted(random.Random(seed).sample(ids, min(n, len(ids))))


def spot_check_sheet(bank: Dict[str, Any]) -> str:
    """Markdown for the owner: the sampled entries with a checklist."""
    by_id = {e["go_id"]: e for e in bank["entries"]}
    out = [f"# {bank['course']} question bank: spot check", "",
           f"Generated {bank['generated_at']} with {', '.join(bank['generator']['models'])}. "
           "For each entry, tick what holds and note anything wrong.", ""]
    for i, go in enumerate(bank["spot_check"]["sample"], 1):
        e = by_id[go]
        out += [f"## {i}. {go} (week {e['week']}): {e['skill_name']}", ""]
        for j, q in enumerate(e["questions"]):
            tag = f" (follow-up to {q['follows'] + 1})" if q["kind"] == "follow_up" else ""
            out.append(f"{j + 1}. {q['text']}{tag}")
        out += ["", f"**Reference answer:** {e['reference_answer']}", "",
                f"**Source:** `{e['source_file']}`: \"{e['source_quote']}\"", "", "**Misconceptions:**"]
        out += [f"- {m['text']} ({m['basis'].replace('_', ' ')})" for m in e["misconceptions"]]
        out += ["", "- [ ] Questions are on this objective and sound like a student",
                "- [ ] The follow-up refers back naturally",
                "- [ ] The reference answer is correct and matches the lesson",
                "- [ ] The source file and quote support it",
                "- [ ] The misconceptions are plausible and actually wrong", "", "Notes:", "", "---", ""]
    return "\n".join(out)
