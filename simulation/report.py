"""Writing a run's results: metrics.json, metrics.csv and report.md (docs/simulation/PLAN.md, section 8).

One table per metric group (value, 95% CI, target, met or not, judge reliability where
relevant), the missing-judgement counts, and the run's costs. Figures (mastery tracking,
scaffolding level against true need, the motivation confusion matrix) are drawn when
matplotlib is installed. ``reanalyse`` recomputes all of it from saved events.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

GROUPS = {"0": "0. Simulator validity", "A": "A. Retrieval and Chat", "B": "B. Grading",
          "C": "C. Learner model tracking", "D": "D. Adaptation", "E": "E. Motivation",
          "F": "F. Tutor dialogue quality", "G": "G. Quiz items",
          "I": "I. Cognitive load, ZPD and scaffolding over time"}


def fmt(v: Any, digits: int = 3) -> str:
    if v is None:
        return "–"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        return f"{v:.{digits}f}"
    return str(v)


def ci(m: Dict[str, Any]) -> str:
    return "–" if m.get("lo") is None else f"[{fmt(m['lo'])}, {fmt(m['hi'])}]"


def target(m: Dict[str, Any]) -> str:
    return "report" if m.get("target") is None else f"{'≥' if m['op'] == '>=' else '≤'} {fmt(m['target'], 2)}"


def met(m: Dict[str, Any]) -> str:
    if m.get("target") is None:
        return "–"
    if m.get("met") is None:
        return "no data"
    note = " (unreliable)" if m.get("reliability_note") else ""
    return ("met" if m["met"] else "**not met**") + note


def write(run_dir: Path, results: Dict[str, Any], manifest: Optional[Dict[str, Any]] = None,
          costs: Optional[Dict[str, Any]] = None) -> Dict[str, Path]:
    run_dir = Path(run_dir)
    (run_dir / "metrics.json").write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    with open(run_dir / "metrics.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "group", "name", "source", "value", "ci_lo", "ci_hi", "target", "op", "met", "n", "reliable"])
        for m in results["metrics"]:
            w.writerow([m["id"], m["group"], m["name"], m["source"], m.get("value"), m.get("lo"), m.get("hi"),
                        m.get("target"), m.get("op"), m.get("met"), m.get("n"),
                        (m.get("reliability") or {}).get("reliable")])
    lines = [f"# Simulation report: {run_dir.name}", ""]
    if manifest:
        lines += [f"Course {manifest.get('course')} · git {str(manifest.get('git_commit'))[:10]}"
                  f"{' (dirty)' if manifest.get('git_dirty') else ''} · config {str(manifest.get('config_hash'))[:10]} · "
                  f"status {manifest.get('status')} · {manifest.get('learner_weeks_done')} learner-weeks", ""]
    lines += [f"{results['counts']['learners']} learners, {results['counts']['learner_weeks']} learner-weeks, "
              f"{results['counts']['turns']} turns. Judging pass: {results.get('pass_id') or 'none'}. "
              "CIs: cluster bootstrap over learners (2,000 resamples). All metrics are reported whatever the outcome.",
              ""]
    for group, title in GROUPS.items():
        rows = [m for m in results["metrics"] if m["group"] == group]
        if not rows:
            continue
        lines += [f"## {title}", "", "| ID | Metric | Value | 95% CI | Target | Result | n |", "|---|---|---|---|---|---|---|"]
        for m in rows:
            value = fmt(m.get("value"))
            if m.get("value_note"):
                value += "¹"
            lines.append(f"| {m['id']} | {m['name']} | {value} | {ci(m)} | {target(m)} | {met(m)} | {fmt(m.get('n'))} |")
        notes = sorted({m["value_note"] for m in rows if m.get("value_note")})
        lines += [""] + [f"¹ {n}" for n in notes] + ([""] if notes else [])
        for m in rows:
            if m["id"] in ("M4", "M5", "M13", "M0b") and m.get("details"):
                lines += [f"**{m['id']} details**", "", "```", json.dumps(m["details"], indent=1, default=str)[:4000],
                          "```", ""]
    lines += ["## H. Judge reliability", "", "| Metric | M20 test-retest | M21 inter-judge | M22 judge-human | Reliable |",
              "|---|---|---|---|---|"]
    for metric, r in results["reliability"].items():
        lines.append(f"| {metric} | {fmt(r['M20_test_retest'])} (n {r['M20_items']}) | {fmt(r['M21_inter_judge'])} "
                     f"(n {r['M21_items']}) | {fmt(r['M22_judge_human']) if r['M22_status'] == 'done' else 'pending'} | "
                     f"{fmt(r['reliable'])} |")
    lines += ["", "Targets: M20 ≥ 0.70, M21 ≥ 0.60, M22 ≥ 0.60. A judged metric that fails is marked unreliable, "
              "not dropped.", "", "**Judgements (judged / missing):** " +
              ", ".join(f"{k} {v['judged']}/{v['missing']}" for k, v in results["judgements"].items()), ""]
    if costs:
        lines += ["## Costs", "", "```", json.dumps(costs, indent=1, default=str), "```", ""]
    figures = draw_figures(run_dir, results)
    if figures:
        lines += ["## Figures", ""] + [f"![{p.stem}]({p.name})" for p in figures] + [""]
    (run_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")
    return {"json": run_dir / "metrics.json", "csv": run_dir / "metrics.csv", "report": run_dir / "report.md"}


def draw_figures(run_dir: Path, results: Dict[str, Any]) -> List[Path]:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return []
    out = []
    by_id = {m["id"]: m for m in results["metrics"]}
    m12 = (by_id.get("M12") or {}).get("details", {}).get("by_level") or {}
    if m12:
        fig, ax = plt.subplots(figsize=(5, 3.2))
        names = list(m12)
        vals = [m12[n]["value"] for n in names]
        err = [[v - (m12[n]["lo"] if m12[n]["lo"] is not None else v) for n, v in zip(names, vals)],
               [(m12[n]["hi"] if m12[n]["hi"] is not None else v) - v for n, v in zip(names, vals)]]
        ax.bar(names, vals, yerr=err, color="#6b8f71")
        ax.set_ylabel("true success probability")
        ax.set_title("Scaffolding level vs true need (M12)")
        fig.tight_layout()
        out.append(run_dir / "fig_scaffolding_need.png")
        fig.savefig(out[-1], dpi=130)
        plt.close(fig)
    conf = (by_id.get("M15") or {}).get("details", {}).get("confusion")
    if conf:
        labels = list(conf)
        grid = [[conf[t][p] for p in labels] for t in labels]
        fig, ax = plt.subplots(figsize=(4.2, 3.6))
        ax.imshow(grid, cmap="Greens")
        ax.set_xticks(range(len(labels)), labels, rotation=30)
        ax.set_yticks(range(len(labels)), labels)
        for i, row in enumerate(grid):
            for j, v in enumerate(row):
                ax.text(j, i, v, ha="center", va="center")
        ax.set_xlabel("LEA's motivation state (mapped)")
        ax.set_ylabel("hidden engagement")
        ax.set_title("Motivation confusion (M15)")
        fig.tight_layout()
        out.append(run_dir / "fig_motivation_confusion.png")
        fig.savefig(out[-1], dpi=130)
        plt.close(fig)
    return out
