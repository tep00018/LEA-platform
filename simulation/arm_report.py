"""One table of every metric, a column per arm, and which arm did best (``python -m simulation arm-report``).

Reads each run's ``metrics.json`` (from ``reanalyse``), so the runs must have been judged and analysed first.
"Best" follows each metric's direction (at least a target, or at most a target). An arm is called the best only
when its 95% interval is clear of the runner-up's; otherwise the row says the arms can't be told apart. Rows with
no target (reported only) name the arm with the higher or lower value only as a note.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

# Where a higher value is better even though the metric has no target, or lower is better.
LOWER_IS_BETTER = {"M5", "M11", "M16b_len", "T2.level", "T2.load", "T2.zpd", "SC2", "SC1_over"}


def load_metrics(run_dir: Path) -> Dict[str, Dict[str, Any]]:
    data = json.loads((Path(run_dir) / "metrics.json").read_text(encoding="utf-8"))
    return {m["id"]: m for m in data["metrics"]}


def fmt(m: Optional[Dict[str, Any]]) -> str:
    if not m or m.get("value") is None:
        return "n/a"
    v = f"{m['value']:.3f}"
    if m.get("lo") is not None and m.get("hi") is not None:
        v += f" [{m['lo']:.2f}, {m['hi']:.2f}]"
    if m.get("met") is True:
        v += " met"
    if m.get("n") is not None:
        v += f" (n {m['n']})"
    return v


def direction(m: Dict[str, Any]) -> Optional[str]:
    if m.get("op") == ">=":
        return "higher"
    if m.get("op") == "<=":
        return "lower"
    return "lower" if m["id"] in LOWER_IS_BETTER else None


def best_arm(row: Dict[str, Optional[Dict[str, Any]]]) -> str:
    present = {k: v for k, v in row.items() if v and v.get("value") is not None}
    if len(present) < 2:
        return "n/a"
    ref = next(iter(present.values()))
    way = direction(ref)
    if way is None:
        return "no target (descriptive)"
    ordered = sorted(present.items(), key=lambda kv: kv[1]["value"], reverse=(way == "higher"))
    (best, b), (_, s) = ordered[0], ordered[1]
    if b["value"] == s["value"]:
        return "tie"
    if None in (b.get("lo"), b.get("hi"), s.get("lo"), s.get("hi")):
        return f"{best} (no interval)"
    clear = (b["lo"] > s["hi"]) if way == "higher" else (b["hi"] < s["lo"])
    return f"{best}" if clear else f"{best} ahead, not distinguishable"


def why(row: Dict[str, Optional[Dict[str, Any]]]) -> str:
    """The ranking behind the verdict, in the metric's own direction, and whether the intervals separate it."""
    present = {k: v for k, v in row.items() if v and v.get("value") is not None}
    if len(present) < 2:
        return "not enough arms with a value"
    ref = next(iter(present.values()))
    way = direction(ref)
    ordered = sorted(present.items(), key=lambda kv: kv[1]["value"], reverse=(way == "higher"))
    text = " > ".join(f"{k} {v['value']:.3g}" for k, v in ordered) if way else ", ".join(f"{k} {v['value']:.3g}" for k, v in ordered)
    if way is None:
        return text + " (no target)"
    (_, b), (_, d) = ordered[0], ordered[1]
    lo = ("higher" if way == "higher" else "lower") + " is better"
    if None in (b.get("lo"), b.get("hi"), d.get("lo"), d.get("hi")):
        return f"{text} ({lo}; no interval)"
    clear = (b["lo"] > d["hi"]) if way == "higher" else (b["hi"] < d["lo"])
    return f"{text} ({lo}; " + ("intervals separate" if clear else "intervals overlap, so a difference isn't shown") + ")"


def build_table(runs: Dict[str, Path]) -> str:
    metrics = {name: load_metrics(path) for name, path in runs.items()}
    ids: List[str] = []
    for m in metrics.values():
        for k in m:
            if k not in ids:
                ids.append(k)
    names = list(runs)
    lines = ["| ID | Metric | Target | " + " | ".join(names) + " | Best | Why |", "|---|---|---|" + "---|" * len(names) + "---|---|"]
    for mid in ids:
        row = {n: metrics[n].get(mid) for n in names}
        ref = next((v for v in row.values() if v), None)
        if not ref:
            continue
        target = "" if ref.get("target") is None else f"{ref['op']} {ref['target']}"
        lines.append(f"| {mid} | {ref['name'][:90]} | {target} | " + " | ".join(fmt(row[n]) for n in names) +
                     f" | {best_arm(row)} | {why(row)} |")
    return "\n".join(lines) + "\n"
