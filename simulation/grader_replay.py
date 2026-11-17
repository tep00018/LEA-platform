"""Offline replay of the tutor grader on saved pilot events (docs/simulation/PLAN.md; the researcher's decision 2026-09-27,
made after Amendment A3 found LEA's tutor grader disagreeing with the simulator's intent on a large share of answers).

No simulation runs and no Claude calls: this reads events and judgements already on disk (pilot-1 through pilot-4)
and calls only OpenAI's ``gpt-4o-mini`` (the model LEA's grader already uses), to test candidate grader prompts
against a fixed dataset. Everything here is read-only with respect to LEA and the simulation; nothing is written
back into ``src/``.

Dataset (``build_dataset``): every tutor-reply and free-text quiz answer (fill-in, open-ended) from the four pilots,
with the tutor's actual question (or the quiz question text), the reference answer and source passage, the
simulator's intended correctness, and the blind fidelity judge's label (``correct``, ``incorrect``, ``not_an_answer``,
or, from rubric v2 onward, ``no_checkable_question``). Pilot-1 predates v2, so its items have no
``no_checkable_question`` signal (``checkable_by_judge`` is ``None`` there).

Candidates (``CANDIDATES``), each a prompt variant of ``src.core.grading``'s own grader (imported, not copied, for
everything except the added instruction, so V0 is byte-for-byte what LEA runs today):
- ``V0_current``: today's grader, unchanged.
- ``V1_actual_question``: adds an instruction to judge only the question actually asked, not other reference facts.
- ``V2_quote_concept``: V1, plus a requirement to name a matched concept before marking an answer correct.
- ``V3_checkable_gate``: V1, plus asking the grader whether the tutor's message was checkable at all (the same
  ``with_confidence`` fields LEA's ``load_led`` scaffolding model already asks for); an answer to a non-checkable
  message is scored as not graded, whatever ``correct`` says.

Each candidate is run ``REPEATS`` times per item to check consistency, and every OpenAI call's usage is recorded so
the true cost is known, not estimated.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from simulation import PACKAGE_DIR, RUNS_DIR
from simulation.harness import load_bank
from simulation.judges import _passage, _reference, read_events
from src.core.grading import GRADER_MODEL, _GRADER_SYSTEM, _RUBRICS, _neutralise_tags, graded, parse_json_object, ungraded

DATASET_DIR = PACKAGE_DIR / "grader_replay"
DATASET_PATH = DATASET_DIR / "dataset.json"
REPEATS = 2

# Prices per LEA_next's OpenAI billing as of this replay (USD per 1M tokens); recorded here, not assumed silently.
PRICE_PER_M = {"gpt-4o-mini": {"input": 0.15, "output": 0.60}}

PILOTS = [("pilot-1", "pilot-judge-1"), ("pilot-2", "pilot2-judge-1"), ("pilot-3", "pilot3-fid"), ("pilot-4", "pilot4-fid")]


# ---------------------------------------------------------------------------- 1. the fixed dataset

def _fidelity_labels(run_dir: Path, pass_id: str) -> Dict[tuple, str]:
    out = {}
    for line in (run_dir / "judgements.jsonl").read_text(encoding="utf-8").splitlines():
        j = json.loads(line)
        if j.get("pass_id") != pass_id or j["kind"] != "fidelity" or not j["values"]:
            continue
        mode = "tutor" if j["unit"].endswith("fid-tutor") else "quiz"
        for item, v in j["values"].items():
            out[(j["learner"], j["week"], j["round"], mode, int(item[1:]))] = v["label"]
    return out


def build_dataset(pilots: List[tuple] = PILOTS, runs_dir: Path = RUNS_DIR) -> List[Dict[str, Any]]:
    """One record per tutor-reply or free-text quiz answer across the given pilots."""
    rows: List[Dict[str, Any]] = []
    for run_id, pass_id in pilots:
        run_dir = runs_dir / run_id
        if not (run_dir / "events.jsonl").exists():
            continue
        events = read_events(run_dir / "events.jsonl")
        bank = load_bank("AIML101")
        fid = _fidelity_labels(run_dir, pass_id)
        rubric_versions = set()
        for line in (run_dir / "judgements.jsonl").read_text(encoding="utf-8").splitlines():
            j = json.loads(line)
            if j.get("pass_id") == pass_id and j["kind"] == "fidelity":
                rubric_versions.add(j.get("rubric_versions", {}).get("M0a"))
        rubric_v2 = rubric_versions == {2}

        by_session: Dict[tuple, List[Dict[str, Any]]] = {}
        for e in events:
            if e.get("kind") == "turn":
                by_session.setdefault((e["learner"], e["week"], e.get("round", 1), e["mode"]), []).append(e)
        openings = {(e["learner"], e["week"], e.get("round", 1)): e.get("message")
                   for e in events if e.get("kind") == "tutor_start"}
        for (learner, week, rnd, mode), turns in by_session.items():
            turns.sort(key=lambda t: t["turn"])
            if mode == "tutor":
                previous = openings.get((learner, week, rnd)) or ""
                for t in turns:
                    student_text, lea_msg = t.get("student_text"), (t.get("lea") or {}).get("message")
                    if not student_text or not lea_msg:
                        continue
                    if (t.get("intent") or {}).get("kind") == "answer":
                        label = fid.get((learner, week, rnd, "tutor", t["turn"]))
                        checkable = None if not rubric_v2 or label is None else label != "no_checkable_question"
                        rows.append({
                            "run": run_id, "learner": learner, "week": week, "round": rnd, "turn": t["turn"],
                            "mode": "tutor", "qtype": "tutor", "question": previous, "answer": student_text,
                            "reference": _reference(t, bank), "passage": _passage(t, bank),
                            "intent_correct": bool(t["intent"]["correct"]), "judge_label": label,
                            "checkable_by_judge": checkable,
                        })
                    previous = lea_msg
            elif mode == "quiz":
                for t in turns:
                    if t.get("qtype") not in ("fill_in", "open_ended") or not t.get("student_text"):
                        continue
                    q = t.get("question") or {}
                    label = fid.get((learner, week, rnd, "quiz", t["turn"]))
                    checkable = None if not rubric_v2 or label is None else label != "no_checkable_question"
                    reference = q.get("correct_answer") or q.get("sample_answer") or _reference(t, bank)
                    rows.append({
                        "run": run_id, "learner": learner, "week": week, "round": rnd, "turn": t["turn"],
                        "mode": "quiz", "qtype": t["qtype"], "question": str(q.get("text", "")),
                        "answer": t["student_text"], "reference": reference, "passage": _passage(t, bank),
                        "intent_correct": bool(t["intent"]["correct"]), "judge_label": label,
                        "checkable_by_judge": checkable,
                    })
    return rows


def save_dataset(rows: List[Dict[str, Any]], path: Path = DATASET_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    return path


def load_dataset(path: Path = DATASET_PATH) -> List[Dict[str, Any]]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------- 2. candidate graders

ACTUAL_QUESTION_NOTE = ("\n\nJudge only whether the answer correctly addresses the specific question or task in "
                        "<question> (or, for a quiz item, the question given). Do not require the answer to cover "
                        "other facts from the reference material that were not asked about, and do not mark an "
                        "answer correct for stating other true facts that do not address what was actually asked.")
QUOTE_CONCEPT_NOTE = ("\n\nTo mark an answer \"correct\", you must be able to name at least one specific concept "
                      "from the reference material that the answer correctly addresses, and put it in "
                      "matched_concepts. If you cannot name one, mark the answer incorrect.")
CHECKABLE_NOTE = ("\n\nAlso add two fields: \"checkable\" (true only if <question> asked something with a right "
                  "answer that can be judged against the reference material; false if it asked about preferences, "
                  "readiness, plans, or asked nothing) and \"confidence\" (0.0 to 1.0, how sure you are of "
                  "\"correct\").")


def _kind_for(row: Dict[str, Any]) -> str:
    return {"tutor": "tutor", "fill_in": "fill_in_blank", "open_ended": "open_ended"}[row["qtype"]]


def _reference_dict(row: Dict[str, Any]) -> Dict[str, str]:
    if row["mode"] == "tutor":
        return {"learning objective": "", "question the tutor asked": row["question"][-800:],
                "reference answer": row["reference"], "lesson passage": row["passage"]}
    key = "expected answer" if row["qtype"] == "fill_in" else "sample answer"
    return {"question": row["question"], key: row["reference"]}


@dataclass
class Candidate:
    name: str
    extra: str = ""
    ask_checkable: bool = False
    gate_on_checkable: bool = False


CANDIDATES = [
    Candidate("V0_current"),
    Candidate("V1_actual_question", extra=ACTUAL_QUESTION_NOTE),
    Candidate("V2_quote_concept", extra=ACTUAL_QUESTION_NOTE + QUOTE_CONCEPT_NOTE),
    Candidate("V3_checkable_gate", extra=ACTUAL_QUESTION_NOTE, ask_checkable=True, gate_on_checkable=True),
]


@dataclass
class Usage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    def add(self, u) -> None:
        self.calls += 1
        if u is not None:
            self.input_tokens += getattr(u, "prompt_tokens", 0) or 0
            self.output_tokens += getattr(u, "completion_tokens", 0) or 0

    def cost_usd(self, model: str = GRADER_MODEL) -> float:
        p = PRICE_PER_M[model]
        return self.input_tokens / 1e6 * p["input"] + self.output_tokens / 1e6 * p["output"]


def grade_one(client, row: Dict[str, Any], candidate: Candidate, usage: Usage) -> Dict[str, Any]:
    """One grading call for one dataset row under one candidate. Never raises: a failure is ``ungraded``."""
    kind = _kind_for(row)
    reference = _reference_dict(row)
    system = _GRADER_SYSTEM.format(rubric=_RUBRICS.get(kind, _RUBRICS["open_ended"]),
                                   reference="\n".join(f"- {k}: {v}" for k, v in reference.items() if v))
    system += candidate.extra
    if candidate.ask_checkable:
        system += CHECKABLE_NOTE
    user = f"<answer>\n{_neutralise_tags(row['answer'])}\n</answer>"
    if row["mode"] == "tutor":
        user = f"<question>\n{_neutralise_tags(row['question'][-800:])}\n</question>\n" + user
    try:
        response = client.chat.completions.create(
            model=GRADER_MODEL, messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.0, max_tokens=400, response_format={"type": "json_object"},
        )
        usage.add(getattr(response, "usage", None))
        text = response.choices[0].message.content
    except Exception as e:
        return ungraded(f"grading request failed: {e}")
    data = parse_json_object(text)
    if data is None:
        return ungraded("grader did not return JSON")
    correct, score = data.get("correct"), data.get("score")
    if not isinstance(correct, bool) or not isinstance(score, (int, float)) or isinstance(score, bool):
        return ungraded(f"grader JSON missing boolean 'correct' or numeric 'score': {data}")
    result = graded(correct, score, str(data.get("explanation", "")).strip(),
                    matched_concepts=[str(c) for c in data.get("matched_concepts", []) if c][:5])
    if candidate.ask_checkable:
        checkable = data.get("checkable")
        result["checkable"] = checkable if isinstance(checkable, bool) else None
        if candidate.gate_on_checkable and checkable is False:
            result = {**result, "graded": False, "gated_not_checkable": True}
    return result


# ---------------------------------------------------------------------------- 3. running the replay

def run_replay(dataset: List[Dict[str, Any]], client, candidates: List[Candidate] = CANDIDATES,
               repeats: int = REPEATS, concurrency: int = 8, on_progress: Optional[Callable[[int, int], None]] = None
               ) -> Dict[str, Any]:
    """{candidate_name: [[repeat0 results...], [repeat1 results...]]} aligned with ``dataset``, plus usage."""
    usage = Usage()
    out: Dict[str, List[List[Dict[str, Any]]]] = {c.name: [[None] * len(dataset) for _ in range(repeats)]
                                                  for c in candidates}
    jobs = [(c, r, i) for c in candidates for r in range(repeats) for i in range(len(dataset))]
    done = [0]

    def one(job):
        c, r, i = job
        result = grade_one(client, dataset[i], c, usage)
        out[c.name][r][i] = result
        done[0] += 1
        if on_progress and done[0] % 50 == 0:
            on_progress(done[0], len(jobs))
        return None

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        list(pool.map(one, jobs))
    return {"results": out, "usage": {"calls": usage.calls, "input_tokens": usage.input_tokens,
                                      "output_tokens": usage.output_tokens, "cost_usd": round(usage.cost_usd(), 4)}}


def estimate_cost(dataset: List[Dict[str, Any]], client, sample: int = 20, candidates: List[Candidate] = CANDIDATES,
                  repeats: int = REPEATS) -> Dict[str, Any]:
    """Grade a small sample with every candidate once each to get a real $/call, then project the full plan."""
    import random

    rng = random.Random(0)
    probe = rng.sample(dataset, min(sample, len(dataset)))
    usage = Usage()
    for c in candidates:
        for row in probe:
            grade_one(client, row, c, usage)
    per_call = usage.cost_usd() / max(usage.calls, 1)
    total_calls = len(dataset) * len(candidates) * repeats
    return {"probe_items": len(probe), "probe_calls": usage.calls, "probe_cost_usd": round(usage.cost_usd(), 4),
            "cost_per_call_usd": per_call, "planned_calls": total_calls,
            "projected_cost_usd": round(per_call * total_calls, 2),
            "avg_input_tokens": usage.input_tokens / max(usage.calls, 1),
            "avg_output_tokens": usage.output_tokens / max(usage.calls, 1)}


# ---------------------------------------------------------------------------- 4. scoring

TYPES = ["tutor", "fill_in", "open_ended"]


def _verdict(result: Optional[Dict[str, Any]]) -> Optional[bool]:
    """The graded correct/incorrect verdict, or None if not graded (including gated-not-checkable)."""
    return result["correct"] if result and result.get("graded") else None


def score_candidate(dataset: List[Dict[str, Any]], repeats_results: List[List[Dict[str, Any]]],
                    judge_agreed_only: bool = True) -> Dict[str, Any]:
    """One candidate's results (``repeats_results``: one list of per-item results per repeat, same order as
    ``dataset``). Uses the first repeat as the reported run; the second is for consistency only."""
    from simulation import stats as S

    first = repeats_results[0]
    out: Dict[str, Any] = {"by_type": {}, "not_graded_rate_all_types": None}
    all_graded = all_total = 0
    for t in TYPES:
        rows = [(row, res) for row, res in zip(dataset, first) if row["qtype"] == t]
        if not rows:
            continue
        eligible = [(row, res) for row, res in rows
                   if not judge_agreed_only or row["judge_label"] in ("correct", "incorrect")]
        truth = [row["intent_correct"] for row, res in eligible]
        verdicts = [_verdict(res) for row, res in eligible]
        pairs = [(a, b) for a, b in zip(truth, verdicts) if b is not None]
        kappa = S.cohen_kappa([a for a, _ in pairs], [b for _, b in pairs]) if pairs else None
        neg = [(a, b) for a, b in pairs if not a]
        pos = [(a, b) for a, b in pairs if a]
        fp = (sum(1 for _, b in neg if b) / len(neg)) if neg else None
        fn = (sum(1 for _, b in pos if not b) / len(pos)) if pos else None
        graded_n = sum(1 for res in [r for _, r in rows] if res and res.get("graded"))
        not_graded = 1 - graded_n / len(rows) if rows else None
        all_graded += graded_n
        all_total += len(rows)
        out["by_type"][t] = {"n_eligible": len(eligible), "n_total": len(rows), "kappa": kappa,
                             "false_positive_rate": fp, "false_negative_rate": fn, "not_graded_rate": not_graded,
                             "accuracy": (sum(1 for a, b in pairs if a == b) / len(pairs)) if pairs else None}
    out["not_graded_rate_all_types"] = 1 - all_graded / all_total if all_total else None
    if len(repeats_results) > 1:
        agree, compared = 0, 0
        for i in range(len(dataset)):
            v0, v1 = _verdict(repeats_results[0][i]), _verdict(repeats_results[1][i])
            if v0 is None and v1 is None:
                continue
            compared += 1
            agree += int(v0 == v1)
        out["consistency_between_two_runs"] = agree / compared if compared else None
        out["consistency_n"] = compared
    return out


def score_all(dataset: List[Dict[str, Any]], results: Dict[str, List[List[Dict[str, Any]]]]) -> Dict[str, Any]:
    return {"judge_agreed_only": {name: score_candidate(dataset, r, judge_agreed_only=True) for name, r in results.items()},
            "all_items_sensitivity": {name: score_candidate(dataset, r, judge_agreed_only=False) for name, r in results.items()}}


def format_report(dataset: List[Dict[str, Any]], scores: Dict[str, Any], usage: Dict[str, Any]) -> str:
    lines = ["# Tutor grader replay: candidates against the simulator's intent", "",
             f"{len(dataset)} saved answers from pilot-1 through pilot-4 (tutor replies and free-text quiz answers), "
             f"each graded by every candidate, {REPEATS} times each for consistency. No simulation or Claude calls; "
             f"gpt-4o-mini only. Actual cost: ${usage['cost_usd']:.2f} ({usage['calls']} calls, "
             f"{usage['input_tokens']:,} input + {usage['output_tokens']:,} output tokens).", "",
             "## Judge-agreed items (the main result: only answers the blind fidelity judge also called correct or "
             "incorrect)", ""]
    for name, s in scores["judge_agreed_only"].items():
        lines.append(f"### {name}")
        lines.append("| Type | n | kappa vs intent | false positives | false negatives | not graded |")
        lines.append("|---|---|---|---|---|---|")
        for t, d in s["by_type"].items():
            def f(x):
                return "-" if x is None else f"{x:.3f}"
            lines.append(f"| {t} | {d['n_eligible']} | {f(d['kappa'])} | {f(d['false_positive_rate'])} | "
                         f"{f(d['false_negative_rate'])} | {f(d['not_graded_rate'])} |")
        c = s.get("consistency_between_two_runs")
        lines.append(f"Consistency between the two runs (same verdict): {f'{c:.3f}' if c is not None else '-'} "
                     f"(n={s.get('consistency_n')})")
        lines.append("")
    lines += ["## All items (sensitivity check: includes answers the judge marked not_an_answer or "
             "no_checkable_question, so the grader's ungraded/not-checkable handling also counts)", ""]
    for name, s in scores["all_items_sensitivity"].items():
        lines.append(f"### {name}  (not-graded rate over every type: "
                     f"{s['not_graded_rate_all_types']:.3f})" if s['not_graded_rate_all_types'] is not None else f"### {name}")
        lines.append("| Type | n | kappa vs intent | false positives | false negatives | not graded |")
        lines.append("|---|---|---|---|---|---|")
        for t, d in s["by_type"].items():
            def f(x):
                return "-" if x is None else f"{x:.3f}"
            lines.append(f"| {t} | {d['n_total']} | {f(d['kappa'])} | {f(d['false_positive_rate'])} | "
                         f"{f(d['false_negative_rate'])} | {f(d['not_graded_rate'])} |")
        lines.append("")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------- 5. the researcher's review sheet

REVIEW_COLUMNS = ["item_id", "type", "question", "reference", "student_answer", "reviewer_a_verdict",
                  "reviewer_a_reason", "reviewer_b_verdict", "reviewer_b_reason", "your_pick", "notes"]


def _clip(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "..."


def build_review_sheet(dataset: List[Dict[str, Any]], v3_results: List[Dict[str, Any]], path: Path, *,
                       target: Dict[str, Dict[str, int]] = None, seed: int = 11,
                       clip_question: Optional[int] = 700) -> Dict[str, Any]:
    """40 disagreements between V3's grader and the simulator's intent (20 false negatives, 20 false
    positives), spread across answer type as far as each bucket has items for. Each row shows the
    grader's verdict and reason next to the blind fidelity judge's verdict, as anonymous "Reviewer A"
    and "Reviewer B" in a random order per row -- never the simulator's own intent, and never which
    reviewer is which. A separate key file (``<path>_key.json``) holds the mapping, the intent, and
    both verdicts, for scoring once the owner has filled in ``your_pick``.

    The fidelity judge (rubric M0a) gives only a label, never a reason; "Reviewer" rows built from it say
    a reason wasn't recorded rather than inventing one -- worded so it never names which reviewer that is.
    """
    import csv
    import hashlib
    import random

    target = target or {"fn": {"tutor": 10, "open_ended": 7, "fill_in": 3},
                        "fp": {"tutor": 15, "fill_in": 4, "open_ended": 1}}
    rng = random.Random(seed)
    buckets: Dict[tuple, List[int]] = {}
    for i, (row, r) in enumerate(zip(dataset, v3_results)):
        if not r.get("graded") or row["judge_label"] not in ("correct", "incorrect"):
            continue
        if row["intent_correct"] and not r["correct"]:
            buckets.setdefault(("fn", row["qtype"]), []).append(i)
        elif not row["intent_correct"] and r["correct"]:
            buckets.setdefault(("fp", row["qtype"]), []).append(i)

    chosen: List[int] = []
    shortfall: Dict[str, int] = {}
    for kind, by_type in target.items():
        for qtype, n in by_type.items():
            pool = buckets.get((kind, qtype), [])
            take = rng.sample(pool, min(n, len(pool)))
            chosen += take
            if len(pool) < n:
                shortfall[f"{kind}/{qtype}"] = n - len(pool)
    rng.shuffle(chosen)

    rows, key = [], {}
    for i in chosen:
        row, r = dataset[i], v3_results[i]
        grader = {"verdict": "correct" if r["correct"] else "incorrect", "reason": r.get("explanation") or "(none given)"}
        judge_verdict = "correct" if row["judge_label"] == "correct" else "incorrect"
        judge = {"verdict": judge_verdict, "reason": "(no written reason recorded for this verdict)"}
        order = [("grader", grader), ("judge", judge)]
        rng.shuffle(order)
        (name_a, a), (name_b, b) = order
        code = "R" + hashlib.sha256(f"{seed}:{row['run']}:{row['learner']}:{row['week']}:{row['round']}:"
                                    f"{row['turn']}:{row['qtype']}".encode()).hexdigest()[:10]
        reference = row["reference"] if row["qtype"] != "tutor" else f"{row['reference']} (lesson: {row['passage']})"
        question = row["question"] if clip_question is None else _clip(row["question"], clip_question)
        rows.append({"item_id": code, "type": row["qtype"], "question": question,
                    "reference": _clip(reference, 500), "student_answer": _clip(row["answer"], 500),
                    "reviewer_a_verdict": a["verdict"], "reviewer_a_reason": a["reason"],
                    "reviewer_b_verdict": b["verdict"], "reviewer_b_reason": b["reason"], "your_pick": "", "notes": ""})
        key[code] = {"a_is": name_a, "b_is": name_b, "intent_correct": row["intent_correct"],
                    "grader_correct": r["correct"], "judge_label": row["judge_label"],
                    "run": row["run"], "learner": row["learner"], "turn": row["turn"]}

    path = Path(path)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=REVIEW_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    path.with_name(path.stem + "_key.json").write_text(json.dumps(key, indent=1), encoding="utf-8")
    return {"rows": len(rows), "shortfall": shortfall, "path": str(path)}


def score_review_sheet(path: Path) -> Dict[str, Any]:
    """After the owner fills in ``your_pick`` (A or B): how often they agreed with the grader, the
    judge, and the simulator's actual intent, split by whether the item was a false negative or
    positive."""
    import csv

    key = json.loads(Path(path).with_name(Path(path).stem + "_key.json").read_text(encoding="utf-8"))
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    out = {"answered": 0, "agrees_with_grader": 0, "agrees_with_judge": 0, "agrees_with_intent": 0}
    for row in rows:
        pick = (row.get("your_pick") or "").strip().upper()
        if pick not in ("A", "B"):
            continue
        k = key[row["item_id"]]
        picked_is = k["a_is"] if pick == "A" else k["b_is"]
        out["answered"] += 1
        out["agrees_with_grader"] += int(picked_is == "grader")
        out["agrees_with_judge"] += int(picked_is == "judge")
        picked_verdict = k["grader_correct"] if picked_is == "grader" else (k["judge_label"] == "correct")
        out["agrees_with_intent"] += int(bool(picked_verdict) == bool(k["intent_correct"]))
    return out


# ---------------------------------------------------------------------------- 6. three more candidates
# (owner's decision after seeing the V3 replay: hold the baseline simulation, try these first, all offline)

NEXT_MODEL = "gpt-4o"
PRICE_PER_M["gpt-4o"] = {"input": 2.50, "output": 10.00}  # per OpenAI's published per-1M-token pricing

KEY_POINTS_SYSTEM = """From the tutor's question and the lesson passage below, write 2 to 3 short key points a
correct answer would need to cover. Reply with a single JSON object: {"key_points": ["...", "..."]}. Each point
is one sentence, specific enough to check an answer against, and drawn only from the passage given."""


def generate_key_points(client, row: Dict[str, Any], usage: Usage) -> List[str]:
    """2-3 key points for one tutor question, from the saved question and lesson passage (no student answer
    involved, so this is safe to cache and reuse across repeats)."""
    user = f"Tutor's question:\n{row['question'][-800:]}\n\nLesson passage:\n{row['passage'] or row['reference']}"
    try:
        response = client.chat.completions.create(
            model=GRADER_MODEL, messages=[{"role": "system", "content": KEY_POINTS_SYSTEM},
                                          {"role": "user", "content": user}],
            temperature=0.0, max_tokens=200, response_format={"type": "json_object"},
        )
        usage.add(getattr(response, "usage", None))
        data = parse_json_object(response.choices[0].message.content)
    except Exception:
        data = None
    points = (data or {}).get("key_points")
    return [str(p) for p in points][:3] if isinstance(points, list) and points else [row["reference"]]


def grade_one_keypoints(client, row: Dict[str, Any], key_points: List[str], usage: Usage) -> Dict[str, Any]:
    """V3 (actual-question note + checkable gate), with the reference replaced by generated key points."""
    kp_row = {**row, "reference": "; ".join(key_points)}
    return grade_one(client, kp_row, CANDIDATES[3], usage)  # V3_checkable_gate


def grade_one_bigger_model(client, row: Dict[str, Any], usage: Usage, model: str = NEXT_MODEL) -> Dict[str, Any]:
    """V3, called on ``model`` instead of gpt-4o-mini."""
    kind = _kind_for(row)
    reference = _reference_dict(row)
    system = (_GRADER_SYSTEM.format(rubric=_RUBRICS.get(kind, _RUBRICS["open_ended"]),
                                    reference="\n".join(f"- {k}: {v}" for k, v in reference.items() if v))
             + ACTUAL_QUESTION_NOTE + CHECKABLE_NOTE)
    user = f"<answer>\n{_neutralise_tags(row['answer'])}\n</answer>"
    if row["mode"] == "tutor":
        user = f"<question>\n{_neutralise_tags(row['question'][-800:])}\n</question>\n" + user
    try:
        response = client.chat.completions.create(
            model=model, messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.0, max_tokens=400, response_format={"type": "json_object"},
        )
        usage.add(getattr(response, "usage", None))
        text = response.choices[0].message.content
    except Exception as e:
        return ungraded(f"grading request failed: {e}")
    data = parse_json_object(text)
    if data is None:
        return ungraded("grader did not return JSON")
    correct, score = data.get("correct"), data.get("score")
    if not isinstance(correct, bool) or not isinstance(score, (int, float)) or isinstance(score, bool):
        return ungraded(f"grader JSON missing boolean 'correct' or numeric 'score': {data}")
    raw_checkable = data.get("checkable")
    checkable = raw_checkable if isinstance(raw_checkable, bool) else None
    if checkable is False:
        return ungraded("the question was not checkable", checkable=False)
    return graded(correct, score, str(data.get("explanation", "")).strip(),
                  matched_concepts=[str(c) for c in data.get("matched_concepts", []) if c][:5], checkable=checkable)


THREE_LEVEL_SYSTEM_SUFFIX = """

Instead of a boolean "correct", reply with "verdict": one of "correct", "partly_correct" or "incorrect".
"partly_correct" means the answer shows real understanding but is incomplete, imprecise, or only partly
addresses what was asked -- not a wrong answer, but not a complete one either. Reply as a single JSON object:
{"verdict": "correct" | "partly_correct" | "incorrect", "score": number 0.0-1.0, "explanation": "...",
 "matched_concepts": [strings], "checkable": true or false, "confidence": number 0.0-1.0}"""


def grade_one_three_level(client, row: Dict[str, Any], usage: Usage) -> Dict[str, Any]:
    """V3's actual-question and checkable framing, with a 3-level verdict instead of a boolean."""
    kind = _kind_for(row)
    reference = _reference_dict(row)
    system = _GRADER_SYSTEM.format(rubric=_RUBRICS.get(kind, _RUBRICS["open_ended"]),
                                   reference="\n".join(f"- {k}: {v}" for k, v in reference.items() if v))
    system += ACTUAL_QUESTION_NOTE + THREE_LEVEL_SYSTEM_SUFFIX
    user = f"<answer>\n{_neutralise_tags(row['answer'])}\n</answer>"
    if row["mode"] == "tutor":
        user = f"<question>\n{_neutralise_tags(row['question'][-800:])}\n</question>\n" + user
    try:
        response = client.chat.completions.create(
            model=GRADER_MODEL, messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.0, max_tokens=400, response_format={"type": "json_object"},
        )
        usage.add(getattr(response, "usage", None))
        text = response.choices[0].message.content
    except Exception as e:
        return ungraded(f"grading request failed: {e}")
    data = parse_json_object(text)
    verdict = (data or {}).get("verdict")
    if verdict not in ("correct", "partly_correct", "incorrect") or not isinstance(data.get("score"), (int, float)):
        return ungraded(f"grader JSON missing a valid 'verdict' or 'score': {data}")
    checkable = data.get("checkable")
    result = {"graded": True, "verdict": verdict, "correct": verdict == "correct",
             "score": max(0.0, min(1.0, float(data["score"]))), "explanation": str(data.get("explanation", "")).strip(),
             "checkable": checkable if isinstance(checkable, bool) else None}
    if checkable is False:
        return ungraded("the question was not checkable", verdict=verdict, correct=None)
    return result


def run_keypoints_candidate(dataset: List[Dict[str, Any]], client, repeats: int = REPEATS) -> Dict[str, Any]:
    usage = Usage()
    tutor_idx = [i for i, r in enumerate(dataset) if r["qtype"] == "tutor"]
    with ThreadPoolExecutor(max_workers=8) as pool:
        kp_list = list(pool.map(lambda i: generate_key_points(client, dataset[i], usage), tutor_idx))
    key_points = dict(zip(tutor_idx, kp_list))
    results = [[None] * len(dataset) for _ in range(repeats)]
    jobs = [(rep, i) for rep in range(repeats) for i in tutor_idx]

    def one(job):
        rep, i = job
        results[rep][i] = grade_one_keypoints(client, dataset[i], key_points[i], usage)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(one, jobs))
    return {"results": results, "key_points_by_row": {i: key_points[i] for i in tutor_idx},
            "usage": {"calls": usage.calls, "cost_usd": round(usage.cost_usd(), 4)}}


def run_bigger_model_candidate(dataset: List[Dict[str, Any]], client, repeats: int = REPEATS,
                               model: str = NEXT_MODEL, types: Optional[List[str]] = None) -> Dict[str, Any]:
    """``types``: only grade rows of these qtypes (e.g. ["tutor", "open_ended"]); others stay ``None`` in
    ``results``, so it aligns index-for-index with the full dataset for combining with another candidate."""
    usage = Usage()
    indices = [i for i, r in enumerate(dataset) if types is None or r["qtype"] in types]
    results = [[None] * len(dataset) for _ in range(repeats)]
    jobs = [(rep, i) for rep in range(repeats) for i in indices]

    def one(job):
        rep, i = job
        results[rep][i] = grade_one_bigger_model(client, dataset[i], usage, model)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(one, jobs))
    return {"results": results, "scored_indices": indices,
            "usage": {"calls": usage.calls, "input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens,
                      "cost_usd": round(usage.cost_usd(model), 4)}}


def probe_bigger_model_cost(dataset: List[Dict[str, Any]], client, sample: int = 20, repeats: int = REPEATS,
                            model: str = NEXT_MODEL, learner_weeks_in_dataset: int = 24) -> Dict[str, Any]:
    import random

    rng = random.Random(0)
    probe = rng.sample(dataset, min(sample, len(dataset)))
    usage = Usage()
    for row in probe:
        grade_one_bigger_model(client, row, usage, model)
    per_call = usage.cost_usd(model) / max(usage.calls, 1)
    full_calls = len(dataset) * repeats
    per_learner_week_calls = len(dataset) / learner_weeks_in_dataset
    return {"probe_items": len(probe), "probe_calls": usage.calls, "probe_cost_usd": round(usage.cost_usd(model), 4),
            "cost_per_call_usd": per_call, "full_replay_calls": full_calls,
            "full_replay_projected_cost_usd": round(per_call * full_calls, 2),
            "per_learner_week_grading_calls": round(per_learner_week_calls, 1),
            "projected_cost_per_learner_week_usd": round(per_call * per_learner_week_calls, 4),
            "projected_cost_per_288_learner_week_run_usd": round(per_call * per_learner_week_calls * 288, 2)}


def run_three_level_candidate(dataset: List[Dict[str, Any]], client, repeats: int = REPEATS) -> Dict[str, Any]:
    usage = Usage()
    results = [[None] * len(dataset) for _ in range(repeats)]
    jobs = [(rep, i) for rep in range(repeats) for i in range(len(dataset))]

    def one(job):
        rep, i = job
        results[rep][i] = grade_one_three_level(client, dataset[i], usage)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(one, jobs))
    return {"results": results, "usage": {"calls": usage.calls, "cost_usd": round(usage.cost_usd(), 4)}}


def score_three_level(dataset: List[Dict[str, Any]], repeats_results: List[List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Kappa with partly_correct treated as incorrect, plus how often each level was used, by type."""
    from collections import Counter

    from simulation import stats as S

    first = repeats_results[0]
    out: Dict[str, Any] = {"by_type": {}}
    for t in TYPES:
        rows = [(row, res) for row, res in zip(dataset, first) if row["qtype"] == t]
        eligible = [(row, res) for row, res in rows if row["judge_label"] in ("correct", "incorrect")]
        levels = Counter(res.get("verdict", "not_graded") if not res.get("graded") else res.get("verdict")
                         for _, res in rows)
        truth = [row["intent_correct"] for row, res in eligible]
        verdicts = [(res["verdict"] == "correct") if res.get("graded") else None for _, res in eligible]
        pairs = [(a, b) for a, b in zip(truth, verdicts) if b is not None]
        kappa = S.cohen_kappa([a for a, _ in pairs], [b for _, b in pairs]) if pairs else None
        out["by_type"][t] = {"n_eligible": len(eligible), "kappa_partly_as_incorrect": kappa,
                             "level_counts": dict(levels), "n_total": len(rows)}
    if len(repeats_results) > 1:
        agree = compared = 0
        for i in range(len(dataset)):
            r0, r1 = repeats_results[0][i], repeats_results[1][i]
            if not r0.get("graded") and not r1.get("graded"):
                continue
            compared += 1
            agree += int(r0.get("verdict") == r1.get("verdict"))
        out["consistency_between_two_runs"] = agree / compared if compared else None
    return out


# ---------------------------------------------------------------------------- 7. escalation policy

def escalate(mini_result: Optional[Dict[str, Any]], bigger_result: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """mini grades everything; only an answer mini marks "correct" gets a second opinion from the bigger
    model, which can downgrade it. mini's "incorrect" or "not graded" verdict is never escalated. If the
    bigger model itself couldn't grade the escalated item, mini's verdict stands."""
    if not mini_result or not mini_result.get("graded") or not mini_result.get("correct"):
        return mini_result or ungraded("no mini verdict")
    if bigger_result and bigger_result.get("graded"):
        return bigger_result
    return mini_result


def score_escalation(dataset: List[Dict[str, Any]], mini_results: List[Dict[str, Any]],
                     bigger_results: List[Optional[Dict[str, Any]]], types: List[str]) -> Dict[str, Any]:
    escalated = [escalate(m, b) for m, b in zip(mini_results, bigger_results)]
    subset_idx = [i for i, r in enumerate(dataset) if r["qtype"] in types]
    subset = [dataset[i] for i in subset_idx]
    mini_sub = [mini_results[i] for i in subset_idx]
    esc_sub = [escalated[i] for i in subset_idx]
    escalated_count = sum(1 for m in mini_sub if m.get("graded") and m.get("correct"))
    return {"mini": score_candidate(subset, [mini_sub]), "escalation": score_candidate(subset, [esc_sub]),
            "escalated_items": escalated_count, "escalated_share_of_graded": (
                escalated_count / sum(1 for m in mini_sub if m.get("graded")) if any(m.get("graded") for m in mini_sub) else None)}


def projected_grading_cost(n_items: int, learner_weeks_in_dataset: int, mini_cost_per_call: float,
                           bigger_cost_per_call: float, escalated_share: float, main_run_learner_weeks: int = 288
                           ) -> Dict[str, float]:
    per_lw = n_items / learner_weeks_in_dataset
    mini_only = per_lw * mini_cost_per_call * main_run_learner_weeks
    bigger_only = per_lw * bigger_cost_per_call * main_run_learner_weeks
    escalation = mini_only + per_lw * escalated_share * bigger_cost_per_call * main_run_learner_weeks
    return {"mini_only_usd": round(mini_only, 2), "bigger_only_usd": round(bigger_only, 2),
            "escalation_usd": round(escalation, 2), "main_run_learner_weeks": main_run_learner_weeks}


def split_review_sheet(path: Path) -> Dict[str, str]:
    """Two CSVs from an already-built review sheet: rows where the two reviewers disagree, and rows
    where they agree (with each other, not necessarily with the simulator's intent -- see the key file)."""
    import csv

    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    disagree = [r for r in rows if r["reviewer_a_verdict"] != r["reviewer_b_verdict"]]
    agree = [r for r in rows if r["reviewer_a_verdict"] == r["reviewer_b_verdict"]]
    out = {}
    for name, subset in (("disagree", disagree), ("agree", agree)):
        p = Path(path).with_name(f"{Path(path).stem}_{name}.csv")
        with open(p, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=REVIEW_COLUMNS)
            writer.writeheader()
            writer.writerows(subset)
        out[name] = str(p)
    return {**out, "disagree_n": len(disagree), "agree_n": len(agree)}


# ---------------------------------------------------------------------------- 8. V4: a broader checkable gate
# (draft for the researcher's approval, 2026-09-27; not wired into src/. Measures whether naming the cases the
# judge already treats as "no_checkable_question" -- warm-ups, opinion/choice prompts -- closes the gap
# between V3's 3.3-3.8% gate rate and the judge's 19.3%.)

BROADER_CHECKABLE_NOTE = """

Also add two fields: "checkable" and "confidence" (0.0 to 1.0, how sure you are of "correct"). "checkable" is
true ONLY if <question> (or the quiz question) asks something with one factually right answer that can be
checked against the reference material. It is FALSE for: a warm-up or diagnostic opener ("what do you already
know about X?"); a question about the student's preferences, readiness, plans, or which activity they want; an
opinion, reflection or choice prompt with no single right answer ("which approach would you choose and why",
"discuss your reasoning", "what do you think", "which would work best here"); or a message that asks nothing at
all."""


def grade_one_v4(client, row: Dict[str, Any], usage: Usage) -> Dict[str, Any]:
    kind = _kind_for(row)
    reference = _reference_dict(row)
    system = (_GRADER_SYSTEM.format(rubric=_RUBRICS.get(kind, _RUBRICS["open_ended"]),
                                    reference="\n".join(f"- {k}: {v}" for k, v in reference.items() if v))
             + ACTUAL_QUESTION_NOTE + BROADER_CHECKABLE_NOTE)
    user = f"<answer>\n{_neutralise_tags(row['answer'])}\n</answer>"
    if row["mode"] == "tutor":
        user = f"<question>\n{_neutralise_tags(row['question'][-800:])}\n</question>\n" + user
    try:
        response = client.chat.completions.create(
            model=GRADER_MODEL, messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.0, max_tokens=400, response_format={"type": "json_object"},
        )
        usage.add(getattr(response, "usage", None))
        text = response.choices[0].message.content
    except Exception as e:
        return ungraded(f"grading request failed: {e}")
    data = parse_json_object(text)
    if data is None:
        return ungraded("grader did not return JSON")
    correct, score = data.get("correct"), data.get("score")
    if not isinstance(correct, bool) or not isinstance(score, (int, float)) or isinstance(score, bool):
        return ungraded(f"grader JSON missing boolean 'correct' or numeric 'score': {data}")
    raw_checkable = data.get("checkable")
    checkable = raw_checkable if isinstance(raw_checkable, bool) else None
    if checkable is False:
        return ungraded("the question was not checkable (broader gate)", checkable=False)
    return graded(correct, score, str(data.get("explanation", "")).strip(),
                  matched_concepts=[str(c) for c in data.get("matched_concepts", []) if c][:5], checkable=checkable)


def run_v4_candidate(dataset: List[Dict[str, Any]], client, repeats: int = REPEATS) -> Dict[str, Any]:
    usage = Usage()
    results = [[None] * len(dataset) for _ in range(repeats)]
    jobs = [(rep, i) for rep in range(repeats) for i in range(len(dataset))]

    def one(job):
        rep, i = job
        results[rep][i] = grade_one_v4(client, dataset[i], usage)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(one, jobs))
    return {"results": results, "usage": {"calls": usage.calls, "cost_usd": round(usage.cost_usd(), 4)}}


def gate_rate(dataset: List[Dict[str, Any]], results: List[Dict[str, Any]], qtype: str = "tutor") -> float:
    rows = [(row, r) for row, r in zip(dataset, results) if row["qtype"] == qtype]
    return sum(1 for _, r in rows if not r.get("graded")) / len(rows) if rows else 0.0


# ---------------------------------------------------------------------------- 9. V5 (owner's decision 2026-09-27)

V5_NOTE = """

A brief answer that correctly answers the question is correct: do not require it to be long, and do not require
it to also cover every part of a multi-question or multi-request message -- answering the core question the
message was built around is enough. Accept synonyms, abbreviations, paraphrases and equivalent terms for a
fill-in-the-blank answer; a different concept is still incorrect. Mark the answer incorrect if what it says about
the question contradicts the reference material or the lesson passage, even if the wording sounds confident. If
the answer to the question is itself correct, but the reply also makes an unrelated, factually wrong side remark
that the question didn't ask about, still mark it correct; briefly correct that side remark in "explanation"
(this is different from a wrong answer to the question itself, which stays incorrect)."""


def grade_one_v5(client, row: Dict[str, Any], usage: Usage) -> Dict[str, Any]:
    """V3 (actual-question note + checkable gate) plus V5_NOTE."""
    kp_row = row
    kind = _kind_for(kp_row)
    reference = _reference_dict(kp_row)
    system = (_GRADER_SYSTEM.format(rubric=_RUBRICS.get(kind, _RUBRICS["open_ended"]),
                                    reference="\n".join(f"- {k}: {v}" for k, v in reference.items() if v))
             + ACTUAL_QUESTION_NOTE + V5_NOTE + CHECKABLE_NOTE)
    user = f"<answer>\n{_neutralise_tags(kp_row['answer'])}\n</answer>"
    if kp_row["mode"] == "tutor":
        user = f"<question>\n{_neutralise_tags(kp_row['question'][-800:])}\n</question>\n" + user
    try:
        response = client.chat.completions.create(
            model=GRADER_MODEL, messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.0, max_tokens=400, response_format={"type": "json_object"},
        )
        usage.add(getattr(response, "usage", None))
        text = response.choices[0].message.content
    except Exception as e:
        return ungraded(f"grading request failed: {e}")
    data = parse_json_object(text)
    if data is None:
        return ungraded("grader did not return JSON")
    correct, score = data.get("correct"), data.get("score")
    if not isinstance(correct, bool) or not isinstance(score, (int, float)) or isinstance(score, bool):
        return ungraded(f"grader JSON missing boolean 'correct' or numeric 'score': {data}")
    raw_checkable = data.get("checkable")
    checkable = raw_checkable if isinstance(raw_checkable, bool) else None
    if checkable is False:
        return ungraded("the question was not checkable", checkable=False)
    return graded(correct, score, str(data.get("explanation", "")).strip(),
                  matched_concepts=[str(c) for c in data.get("matched_concepts", []) if c][:5], checkable=checkable)


def run_v5_candidate(dataset: List[Dict[str, Any]], client, repeats: int = 1) -> Dict[str, Any]:
    usage = Usage()
    results = [[None] * len(dataset) for _ in range(repeats)]
    jobs = [(rep, i) for rep in range(repeats) for i in range(len(dataset))]

    def one(job):
        rep, i = job
        results[rep][i] = grade_one_v5(client, dataset[i], usage)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(one, jobs))
    return {"results": results, "usage": {"calls": usage.calls, "cost_usd": round(usage.cost_usd(), 4)}}


def score_against_corrected_intent(dataset: List[Dict[str, Any]], results: List[Dict[str, Any]],
                                   corrected: Dict[str, bool]) -> Dict[str, Any]:
    """Like score_candidate, but for rows in ``corrected`` the truth is the researcher's adjudicated verdict
    instead of the simulator's original recorded intent. ``corrected`` keys are "run:learner:turn" (unique
    across the dataset -- checked, not assumed)."""
    adj = [dict(row) for row in dataset]
    for row in adj:
        key = f"{row['run']}:{row['learner']}:{row['turn']}"
        if key in corrected:
            row["intent_correct"] = corrected[key]
    return score_candidate(adj, [results])
