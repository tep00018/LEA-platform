"""Readable transcripts and the pilot report (for the owner, not for judges).

Transcripts show what judges never see: the learner's profile, hidden knowledge and
engagement, and the intent behind each message, next to LEA's replies, grades, mastery and
decisions, so the owner can see whether the simulation behaves sensibly.
"""

from __future__ import annotations

import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

from simulation.metrics import MOTIVATION


def _clip(text: Any, n: int = 1200) -> str:
    text = str(text or "").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def sessions(events: List[Dict[str, Any]]) -> Dict[tuple, List[Dict[str, Any]]]:
    out: Dict[tuple, List[Dict[str, Any]]] = defaultdict(list)
    for e in events:
        if e.get("kind") in ("turn", "tutor_start"):
            mode = e.get("mode", "tutor")
            out[(e["learner"], e["week"], e.get("round", 1), mode)].append(e)
    return out


def pick(events: List[Dict[str, Any]], n: int = 10, seed: int = 11) -> List[tuple]:
    """Mostly tutor sessions, spread over profiles, plus a quiz and a chat sitting."""
    keys = sorted(sessions(events))
    rng = random.Random(seed)
    tutor = [k for k in keys if k[3] == "tutor"]
    by_learner: Dict[str, List[tuple]] = defaultdict(list)
    for k in tutor:
        by_learner[k[0]].append(k)
    chosen = [rng.choice(v) for _, v in sorted(by_learner.items())][: max(0, n - 2)]
    for mode in ("quiz", "chat"):
        pool = [k for k in keys if k[3] == mode]
        if pool:
            chosen.append(rng.choice(pool))
    rest = [k for k in tutor if k not in chosen]
    rng.shuffle(rest)
    return (chosen + rest)[:n]


def render(key: tuple, rows: List[Dict[str, Any]]) -> str:
    learner, week, round_no, mode = key
    rows = sorted(rows, key=lambda r: (r.get("kind") != "tutor_start", r.get("turn", 0)))
    profile = next((r.get("profile") for r in rows if r.get("profile")), "?")
    out = [f"# {learner} ({profile}), week {week}, round {round_no}, {mode}", ""]
    for r in rows:
        if r.get("kind") == "tutor_start":
            out += [f"**LEA (opening):** {_clip(r.get('message'))}", ""]
            continue
        i = r.get("intent") or {}
        hb = r.get("hidden_before") or {}
        lea = r.get("lea") or {}
        state = next((d["payload"] for d in r.get("decisions") or [] if d["type"] == "learner_state"), {}) or {}
        answer = next((d["payload"] for d in r.get("decisions") or [] if d["type"] == "answer"), {}) or {}
        m = r.get("mastery") or {}
        truth = (f"{i.get('kind')}" + (f", meant {'right' if i.get('correct') else 'wrong'}" if i.get("kind") == "answer" else "")
                 + f"; knows {r.get('go_id')}: {hb.get('known')} (p {hb.get('p_know')}); {i.get('engagement')}")
        out.append(f"*[{r.get('turn')}] hidden: {truth}*")
        if mode == "quiz" and r.get("question"):
            q = r["question"]
            out.append(f"**Quiz ({q.get('type')}):** {_clip(q.get('text'), 600)}" +
                       (f"  \nOptions: {'; '.join(q.get('options') or [])}" if q.get("options") else ""))
        out.append(f"**Student:** {_clip(r.get('student_text'), 800) if r.get('student_text') else '(left the session)'}")
        if mode == "chat":
            sources = sorted({s.get("source") for x in r.get("retrieval") or [] for s in x.get("sources") or []})
            out.append(f"*source lesson {r.get('source_file')}; retrieved {', '.join(map(str, sources)) or 'nothing'}"
                       f"{'; follow-up' if r.get('follow_up') else ''}*")
        if lea.get("message") or lea.get("explanation"):
            out.append(f"**LEA:** {_clip(lea.get('message') or lea.get('explanation'))}")
        grade = ("not graded" if not lea.get("graded") else ("correct" if lea.get("correct") else "incorrect")) \
            if mode != "chat" else None
        extras = [x for x in (
            f"grade {grade}" if grade else None,
            f"mastery {m.get('before')} → {m.get('after')} (threshold {m.get('threshold')})" if m.get("after") is not None else None,
            f"scaffolding {answer.get('scaffolding_intensity')}" if answer.get("scaffolding_intensity") else None,
            f"motivation {state.get('motivation_state')} (~{MOTIVATION.get(state.get('motivation_state'), '?')})"
            if state.get("motivation_state") else None) if x]
        if extras:
            out.append(f"*LEA: {'; '.join(extras)}*")
        out.append("")
    return "\n".join(out)


def write_transcripts(run_dir: Path, n: int = 10) -> List[Path]:
    run_dir = Path(run_dir)
    events = [json.loads(line) for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    groups = sessions(events)
    folder = run_dir / "transcripts"
    folder.mkdir(exist_ok=True)
    paths = []
    for i, key in enumerate(pick(events, n), 1):
        path = folder / f"{i:02d}_{key[0]}_w{key[1]}_r{key[2]}_{key[3]}.md"
        path.write_text(render(key, groups[key]), encoding="utf-8")
        paths.append(path)
    return paths


def pilot_report(run_dir: Path, ledger_rows: List[Dict[str, Any]], metrics: Dict[str, Any]) -> str:
    """Per learner-week costs and time, pauses, and M0a-M0c (section 7 of the plan)."""
    run_dir = Path(run_dir)
    events = [json.loads(line) for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    judgements_path = run_dir / "judgements.jsonl"
    judgements = [json.loads(x) for x in judgements_path.read_text(encoding="utf-8").splitlines()] \
        if judgements_path.exists() else []
    rows: Dict[tuple, Dict[str, Any]] = defaultdict(lambda: {"openai_usd": 0.0, "openai_calls": 0, "student_calls": 0,
                                                             "student_usd": 0.0, "judge_calls": 0, "judge_usd": 0.0,
                                                             "second_judge_calls": 0, "second_judge_usd": 0.0,
                                                             "seconds": None, "stuck": None, "profile": None})
    for e in events:
        key = (e.get("learner"), e.get("week"))
        if e.get("kind") == "turn":
            r = rows[key]
            r["profile"] = e.get("profile")
            r["openai_usd"] += float((e.get("openai") or {}).get("usd") or 0)
            r["openai_calls"] += int((e.get("openai") or {}).get("calls") or 0)
            r["student_calls"] += int((e.get("claude_student") or {}).get("calls") or 0)
            r["student_usd"] += float((e.get("claude_student") or {}).get("cost_usd") or 0)
        elif e.get("kind") == "learner_week":
            rows[key]["seconds"] = e.get("seconds")
            rows[key]["stuck"] = e.get("stuck")
    for j in judgements:
        r = rows[(j["learner"], j["week"])]
        prefix = "second_judge" if j["judge_role"] == "second_judge" else "judge"
        r[f"{prefix}_calls"] += int(j.get("attempts") or 1)
        r[f"{prefix}_usd"] += float(j.get("cost_usd") or 0)
    lines = [f"# Pilot report: {run_dir.name}", "",
             f"Status {manifest.get('status')}; {manifest.get('learner_weeks_done')} learner-weeks; git "
             f"{str(manifest.get('git_commit'))[:10]}; Claude Code {manifest['claude'].get('code_version')}; "
             f"models: OpenAI {sorted((manifest.get('openai') or {}).get('models', {}))}, Claude "
             f"{manifest['claude'].get('models')}.", "",
             "Claude figures are API-equivalent dollars (total_cost_usd), an estimate under a subscription, not a bill.",
             "", "| Learner-week | Profile | OpenAI $ (calls) | Student calls / $ | Judge calls / $ | Opus calls / $ | "
             "Minutes | Stuck |", "|---|---|---|---|---|---|---|---|"]
    tot = defaultdict(float)
    for (learner, week), r in sorted(rows.items(), key=lambda kv: str(kv[0])):
        if learner is None:
            continue
        lines.append(f"| {learner} w{week} | {r['profile']} | {r['openai_usd']:.3f} ({r['openai_calls']}) | "
                     f"{r['student_calls']} / {r['student_usd']:.3f} | {r['judge_calls']} / {r['judge_usd']:.3f} | "
                     f"{r['second_judge_calls']} / {r['second_judge_usd']:.3f} | "
                     f"{(r['seconds'] or 0) / 60:.1f} | {r['stuck']} |")
        for k in ("openai_usd", "student_usd", "judge_usd", "second_judge_usd", "student_calls", "judge_calls",
                  "second_judge_calls"):
            tot[k] += r[k]
        tot["seconds"] += r["seconds"] or 0
    lines += [f"| **Total** | | {tot['openai_usd']:.3f} | {int(tot['student_calls'])} / {tot['student_usd']:.3f} | "
              f"{int(tot['judge_calls'])} / {tot['judge_usd']:.3f} | {int(tot['second_judge_calls'])} / "
              f"{tot['second_judge_usd']:.3f} | {tot['seconds'] / 60:.1f} | |", ""]
    by_role = defaultdict(lambda: {"calls": 0, "usd": 0.0, "tokens": 0})
    for r in ledger_rows:
        d = by_role[r.get("role")]
        d["calls"] += 1
        d["usd"] += float(r.get("cost_usd") or 0)
        d["tokens"] += sum(int(r.get(k) or 0) for k in ("input_tokens", "output_tokens", "cache_read_input_tokens",
                                                         "cache_creation_input_tokens"))
    lines += ["## Claude use by role (from the ledger)", "", "| Role | Calls | Tokens | API-equivalent $ |", "|---|---|---|---|"]
    lines += [f"| {role} | {d['calls']} | {d['tokens']:,} | {d['usd']:.3f} |" for role, d in sorted(by_role.items())]
    lines += ["", f"Pauses: {manifest.get('pauses') or 'none'}", "", "## Simulator validity", "",
              "| ID | Value | 95% CI | Target | Result |", "|---|---|---|---|---|"]
    for m in metrics["metrics"]:
        if m["id"] in ("M0a", "M0b", "M0c"):
            ci = "–" if m.get("lo") is None else f"[{m['lo']:.3f}, {m['hi']:.3f}]"
            value = "–" if m.get("value") is None else f"{m['value']:.3f}"
            result = "–" if m.get("met") is None else ("met" if m["met"] else "not met")
            lines.append(f"| {m['id']} | {value} | {ci} | {m.get('op') or ''} {m.get('target')} | {result} |")
    m0b = next((m for m in metrics["metrics"] if m["id"] == "M0b"), None)
    if m0b and m0b.get("details"):
        lines += ["", "M0b by profile:", "", "```", json.dumps(m0b["details"], indent=1), "```"]
    return "\n".join(lines) + "\n"
