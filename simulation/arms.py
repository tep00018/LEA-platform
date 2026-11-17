"""Two cognitive-load equations, compared (the fixed one LEA has always used and the personal one).

Two views, both against the simulator's hidden true load (``true_load`` in each answered turn's event):

1. **Within a run** (``run_metrics``): every turn that carried client timing logs both equations'
   values (``load_details.fixed`` and ``.load``). Per learner: how well each tracks the true load
   (Pearson r within the learner, mean absolute error), and the paired difference over learners.
   This is the estimation question, answered from one run.
2. **Between two runs** (``compare``): the same simulated learners run twice, once with each
   equation *driving* LEA's scaffolding (``lea.cognitive_load_model``). Per learner, the paired
   difference (personal minus fixed) in how well the load that drove scaffolding tracked the truth
   and how well the support level matched what the hidden load called for.

Pre-registered primary outcomes (Holm-corrected together): P1, within-learner r of the load that
drove scaffolding with the true load (higher is better); P2, SC2L, the share of turns two or more
support levels from what the true load calls for (lower is better). Everything else is secondary.
Tests: paired Wilcoxon signed-rank and a cluster bootstrap over learners for the mean difference.

Limits, stated: the true load is this study's model (``signals.py``), and it does not change whether
an answer is right, so this cannot show that either equation improves learning, and the personal
equation was calibrated on students from the same generator (in-distribution).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from scipy import stats as sp

from simulation import stats as S
from simulation.metrics import RunData, _decision, _level, _metric
from simulation.support_metrics import _reversals, needed_level

# support level the true load calls for (an assumption fixed in advance): load 0-10 -> level 0-4
LOAD_BANDS = [(8.0, 4), (6.0, 3), (4.0, 2), (2.0, 1), (0.0, 0)]


def load_needed_level(load: float) -> int:
    return next(level for edge, level in LOAD_BANDS if load >= edge)


def turn_table(data: RunData) -> List[Dict[str, Any]]:
    rows = []
    for t in data.turns:
        if t.get("true_load") is None or (t.get("intent") or {}).get("kind") == "quit":
            continue
        state = (_decision(t, "learner_state") or {}).get("cognitive_state") or {}
        details = state.get("load_details") or {}
        if "fixed" not in details:
            continue
        cog = _decision(t, "cognitive_decision") or {}
        rows.append({"learner": t["learner"], "week": t["week"], "round": t.get("round", 1), "mode": t["mode"],
                     "turn": t["turn"], "true": float(t["true_load"]), "fixed": float(details["fixed"]),
                     "zpd": cog.get("zpd_score"),
                     "p": float((t.get("intent") or {}).get("p_correct") or 0.0)
                     if (t.get("intent") or {}).get("kind") == "answer" else None,
                     "personal": float(details["load"]), "selected": float(state.get("cognitive_load", details["fixed"])),
                     "level": _level(t), "rapid_guess": bool(details.get("rapid_guess")), "gain": details.get("gain")})
    history: Dict[Tuple, List[float]] = {}
    for r in sorted(rows, key=lambda r: (r["learner"], r["week"], r["round"], r["mode"], r["turn"])):
        h = history.setdefault((r["learner"], r["week"], r["round"], r["mode"]), [])
        if r["p"] is not None:
            h.append(r["p"])
        r["recent"] = float(np.mean(h[-4:])) if len(h) >= 2 else None
    return rows


def _r(a, b) -> Optional[float]:
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) < 4 or a.std() < 1e-9 or b.std() < 1e-9:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def per_learner(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for name, rr in S.group_by(rows, "learner").items():
        rr = sorted(rr, key=lambda r: (r["week"], r["round"], r["mode"], r["turn"]))
        true = [r["true"] for r in rr]
        out[name] = {"n": len(rr),
                     **{f"r_{k}": _r([r[k] for r in rr], true) for k in ("fixed", "personal", "selected")},
                     **{f"mae_{k}": float(np.mean([abs(r[k] - r["true"]) for r in rr])) for k in ("fixed", "personal", "selected")}}
        lv = [(r["level"], load_needed_level(r["true"])) for r in rr if r["level"] is not None]
        if lv:
            diffs = [a - b for a, b in lv]
            out[name].update({"sc2l": float(np.mean([abs(d) >= 2 for d in diffs])),
                              "over": float(np.mean([d >= 2 for d in diffs])), "under": float(np.mean([d <= -2 for d in diffs]))})
        ls = [(r["level"], needed_level(r["recent"])) for r in rr if r["level"] is not None and r["recent"] is not None]
        if ls:
            ds = [a - b for a, b in ls]
            out[name].update({"sc2": float(np.mean([abs(d) >= 2 for d in ds])),
                              "over_s": float(np.mean([d >= 2 for d in ds])), "under_s": float(np.mean([d <= -2 for d in ds]))})
        zr = [(r["zpd"], r["recent"]) for r in rr if r["zpd"] is not None and r["recent"] is not None]
        out[name]["r_zpd"] = _r([a for a, _ in zr], [b for _, b in zr]) if zr else None
        seq = [r for r in rr if r["mode"] == "tutor" and r["level"] is not None]
        flips, flat = _reversals([r["level"] for r in seq], [r["recent"] for r in seq], 1.0)
        out[name]["flips_per_10"] = 10 * flips / flat if flat else None
    return out


def paired(pl_a: Dict[str, Dict[str, Any]], pl_b: Dict[str, Dict[str, Any]], key_a: str, key_b: Optional[str] = None
           ) -> Dict[str, Any]:
    """B minus A over learners present in both with the value defined in both."""
    key_b = key_b or key_a
    names = sorted(n for n in pl_a if n in pl_b and pl_a[n].get(key_a) is not None and pl_b[n].get(key_b) is not None)
    d = np.array([pl_b[n][key_b] - pl_a[n][key_a] for n in names], float)
    if len(d) < 2:
        return {"n": len(d), "mean_diff": None, "lo": None, "hi": None, "p_wilcoxon": None, "a": None, "b": None}
    boot = S.cluster_bootstrap({n: [v] for n, v in zip(names, d)}, lambda xs: float(np.mean(xs)), n=2000)
    try:
        p = float(sp.wilcoxon(d).pvalue) if np.any(d != 0) else 1.0
    except ValueError:
        p = 1.0
    return {"n": len(d), "mean_diff": float(d.mean()), "lo": boot["lo"], "hi": boot["hi"], "p_wilcoxon": p,
            "a": float(np.mean([pl_a[n][key_a] for n in names])), "b": float(np.mean([pl_b[n][key_b] for n in names]))}


# ---------------------------------------------------------------------------- within one run

def run_metrics(data: RunData) -> List[Dict[str, Any]]:
    rows = turn_table(data)
    if not rows:
        return []
    pl = per_learner(rows)
    fixed_vs_personal = paired(pl, pl, "r_fixed", "r_personal")
    mae = paired(pl, pl, "mae_fixed", "mae_personal")
    r_fixed = S.cluster_bootstrap({n: [v["r_fixed"]] for n, v in pl.items() if v["r_fixed"] is not None}, S.mean)
    r_personal = S.cluster_bootstrap({n: [v["r_personal"]] for n, v in pl.items() if v["r_personal"] is not None}, S.mean)
    return [
        _metric("CLT.fixed", "I", "Fixed load equation: within-learner r with the hidden true load", "GT", r_fixed, None, None,
                details={"turns": len(rows)}),
        _metric("CLT.personal", "I", "Personal load equation: within-learner r with the hidden true load", "GT", r_personal, None,
                None, details={"turns": len(rows)}),
        _metric("CLT.diff_r", "I", "Personal minus fixed: within-learner r with the true load (paired over learners)", "GT",
                {"value": fixed_vs_personal["mean_diff"], "lo": fixed_vs_personal["lo"], "hi": fixed_vs_personal["hi"],
                 "n": fixed_vs_personal["n"]}, 0.0, ">=", details={"p_wilcoxon": fixed_vs_personal["p_wilcoxon"]}),
        _metric("CLT.diff_mae", "I", "Personal minus fixed: mean absolute error against the true load (load points; lower is better)",
                "GT", {"value": mae["mean_diff"], "lo": mae["lo"], "hi": mae["hi"], "n": mae["n"]}, 0.0, "<=",
                details={"p_wilcoxon": mae["p_wilcoxon"], "fixed_mae": mae["a"], "personal_mae": mae["b"]}),
    ]


# ---------------------------------------------------------------------------- two runs

PRIMARY = {"P1": ("r_selected", "higher"), "P2": ("sc2l", "lower")}
SECONDARY = {"mae_selected": "lower", "over": "lower", "under": "lower"}
# Amendment A2 (scaffolding rules; the load equation is the same in both runs): support against the support
# the true load calls for (P2) and against what the learner's true recent success calls for (P3).
PRIMARY_SCAFFOLDING = {"P2": ("sc2l", "lower"), "P3": ("sc2", "lower")}
SECONDARY_SCAFFOLDING = {"over": "lower", "under": "lower", "over_s": "lower", "under_s": "lower",
                         "r_zpd": "higher", "flips_per_10": "lower"}


def compare(data_a: RunData, data_b: RunData, scaffolding: bool = False) -> Dict[str, Any]:
    primary, secondary = (PRIMARY_SCAFFOLDING, SECONDARY_SCAFFOLDING) if scaffolding else (PRIMARY, SECONDARY)
    pl_a, pl_b = per_learner(turn_table(data_a)), per_learner(turn_table(data_b))
    out: Dict[str, Any] = {"learners_a": len(pl_a), "learners_b": len(pl_b),
                           "matched": sorted(set(pl_a) & set(pl_b)), "primary": {}, "secondary": {}}
    for name, (key, better) in primary.items():
        out["primary"][name] = {**paired(pl_a, pl_b, key), "metric": key, "better": better}
    p = {n: v["p_wilcoxon"] for n, v in out["primary"].items() if v["p_wilcoxon"] is not None}
    holm = S.holm(p) if p else {}
    for n in out["primary"]:
        out["primary"][n]["p_holm"] = holm.get(n)
        v = out["primary"][n]
        v["favours_b"] = None if v["mean_diff"] is None else (v["mean_diff"] > 0) == (v["better"] == "higher")
        v["significant"] = bool(v["p_holm"] is not None and v["p_holm"] < 0.05 and v["lo"] is not None
                                and (v["lo"] > 0 or v["hi"] < 0))
    for key, better in secondary.items():
        out["secondary"][key] = {**paired(pl_a, pl_b, key), "better": better}
    return out


def format_comparison(result: Dict[str, Any], a_name: str, b_name: str, kind: str = "the load equation") -> str:
    def fmt(v):
        if v["mean_diff"] is None:
            return "n/a"
        return f"{v['mean_diff']:+.3f} [{v['lo']:+.3f}, {v['hi']:+.3f}]" if v["lo"] is not None else f"{v['mean_diff']:+.3f}"

    lines = [f"# {kind.capitalize()} compared: A = {a_name}, B = {b_name}", "",
             f"{len(result['matched'])} learners matched across the two runs. Differences are B minus A, averaged over learners, "
             "with a 95% cluster bootstrap interval; p is a paired Wilcoxon signed-rank test, Holm-corrected across the two primary "
             "outcomes.", "", "## Primary (pre-registered)", "", "| Outcome | A | B | B - A | p (Holm) | Favours B | Significant |",
             "|---|---|---|---|---|---|---|"]
    names = {"P1": "P1 within-learner r of the driving load with the true load (higher is better)",
             "P2": "P2 support two or more levels from what the true load calls for (lower is better)",
             "P3": "P3 support two or more levels from what true recent success calls for (lower is better)"}
    for n, v in result["primary"].items():
        a = "n/a" if v["a"] is None else f"{v['a']:.3f}"
        b = "n/a" if v["b"] is None else f"{v['b']:.3f}"
        p = "n/a" if v.get("p_holm") is None else f"{v['p_holm']:.3f}"
        lines.append(f"| {names[n]} | {a} | {b} | {fmt(v)} | {p} | {v.get('favours_b')} | {v.get('significant')} |")
    lines += ["", "## Secondary (not corrected)", "", "| Outcome | A | B | B - A | p |", "|---|---|---|---|---|"]
    for n, v in result["secondary"].items():
        a = "n/a" if v["a"] is None else f"{v['a']:.3f}"
        b = "n/a" if v["b"] is None else f"{v['b']:.3f}"
        p = "n/a" if v["p_wilcoxon"] is None else f"{v['p_wilcoxon']:.3f}"
        lines.append(f"| {n} ({v['better']} is better) | {a} | {b} | {fmt(v)} | {p} |")
    lines += ["", "The hidden load is this study's model of students and does not change whether an answer is right, so this "
                  "compares how well each equation tracks and drives support against that model; it cannot show learning gains."]
    return "\n".join(lines) + "\n"
