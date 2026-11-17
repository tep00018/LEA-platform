"""Cognitive load, ZPD and scaffolding over time (metric group I; see PREREGISTRATION.md).

LEA's cognitive load, ZPD score and scaffolding level are fixed formulas today. These metrics
ask whether they track what the simulator knows, and whether the scaffolding they drive
responds sensibly over a session. They use only what every run already records (LEA's
decisions per turn, the simulator's hidden success probabilities), so any finished run can be
re-analysed.

Truth signal: ``recent`` = the mean true success probability (``p_correct``) of the learner's
last four answers in the session (at least two). It is what the item-by-item task really
demanded of the learner recently, and LEA never sees it. The "needed support" bands in SC2
are an assumption fixed in advance (below), not a fact about learners.

- CL1  load validity: r(LEA cognitive load, 1 - recent).
- CL2  load vs difficulty: mean load when recent < 0.5 minus mean load when recent >= 0.75.
- ZPD1 ZPD calibration: true success rises with LEA's ZPD level (low < medium < high).
- SC1  fade appropriateness: share of faded turns where recent >= 0.75.
- SC2  support mismatch: share of turns two or more levels away from the support the band asks for.
- T1   lag: after the true state shifts, share of shifts LEA's support follows within 3 turns.
- T2   oscillation: direction reversals per 10 turns while the true state is flat.
- T3   recovery: after a run of errors then two right answers, support eases within 4 turns.
- T4   session arc: how load, ZPD, support, fatigue and true success trend over a session.
- SC3  (judged; see judges.py) support appropriateness.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional

import numpy as np

from simulation import stats as S
from simulation.metrics import RunData, _clusters, _decision, _level, _metric, _sessions

WINDOW = 4
NEED_BANDS = [(0.90, 0), (0.75, 1), (0.60, 2), (0.40, 3), (0.0, 4)]  # recent >= edge -> support level needed
SHIFT = 0.20        # a shift in the true state: recent moves by this much over 3 answers
FLAT = 0.10         # "flat": recent moves by less than this
RESPONSE_TURNS = 3
LOAD_STEP, ZPD_STEP = 0.5, 0.15


def needed_level(recent: float) -> int:
    return next(level for edge, level in NEED_BANDS if recent >= edge)


def session_series(data: RunData) -> List[Dict[str, Any]]:
    """One record per tutor session: the ordered answer turns with LEA's signals and the truth."""
    out = []
    for (learner, week, rnd), turns in _sessions(data).items():
        rows, history = [], []
        for t in turns:
            if t["intent"]["kind"] != "answer":
                continue
            cog = _decision(t, "cognitive_decision") or {}
            sc = _decision(t, "scaffolding_decision") or {}
            history.append(float(t["intent"]["p_correct"]))
            level = _level(t)
            rows.append({
                "learner": learner, "load": cog.get("cognitive_load"), "zpd": cog.get("zpd_score"),
                "fatigue": cog.get("fatigue"), "zpd_level": sc.get("zpd_level"), "level": level,
                "faded": bool(sc.get("was_faded")), "p": history[-1], "correct": bool(t["intent"]["correct"]),
                "recent": S.mean(history[-WINDOW:]) if len(history) >= 2 else None})
        if rows:
            out.append({"learner": learner, "week": week, "round": rnd, "rows": rows})
    return out


def _all_rows(series) -> List[Dict[str, Any]]:
    return [r for s in series for r in s["rows"] if r["recent"] is not None]


def cl1(series) -> Dict[str, Any]:
    rows = [r for r in _all_rows(series) if r["load"] is not None]
    res = S.cluster_bootstrap(_clusters(rows), lambda rs: S.pearson([r["load"] for r in rs], [1 - r["recent"] for r in rs]))
    return _metric("CL1", "I", "Cognitive load tracks demand: r(LEA load, 1 - recent true success)", "GT", res, 0.4, ">=",
                   details={"points": len(rows)})


def cl2(series) -> Dict[str, Any]:
    rows = [r for r in _all_rows(series) if r["load"] is not None]

    def gap(rs):
        hard = [r["load"] for r in rs if r["recent"] < 0.5]
        easy = [r["load"] for r in rs if r["recent"] >= 0.75]
        return S.mean(hard) - S.mean(easy) if hard and easy else None

    res = S.cluster_bootstrap(_clusters(rows), gap)
    return _metric("CL2", "I", "Load is higher on hard stretches: mean load (recent < 0.5) minus (recent >= 0.75)", "GT",
                   res, 1.0, ">=", details={"hard_turns": sum(r["recent"] < 0.5 for r in rows),
                                            "easy_turns": sum(r["recent"] >= 0.75 for r in rows), "unit": "load points"})


def zpd1(series) -> Dict[str, Any]:
    rows = [r for r in _all_rows(series) if r["zpd_level"] in ("low", "medium", "high")]
    by = {}
    for name in ("low", "medium", "high"):
        subset = [r for r in rows if r["zpd_level"] == name]
        if subset:
            by[name] = S.cluster_bootstrap(_clusters(subset, lambda r: r["recent"]), S.mean)
    present = [n for n in ("low", "medium", "high") if n in by]
    means = [by[n]["value"] for n in present]
    monotone = all(x < y for x, y in zip(means, means[1:])) if len(means) >= 2 else None
    separated = all(by[a]["hi"] is not None and by[b]["lo"] is not None and by[a]["hi"] < by[b]["lo"]
                    for a, b in zip(present, present[1:])) if len(present) >= 2 else None
    value = None if monotone is None else float(bool(monotone and separated))
    out = _metric("ZPD1", "I", "ZPD calibration: true success rises from low to high ZPD level", "GT", {"value": value},
                  1.0, ">=", details={"by_zpd_level": by, "monotone": monotone, "adjacent_cis_separated": separated,
                                      "turns_by_level": {n: sum(r["zpd_level"] == n for r in rows) for n in present}})
    out["value_note"] = "1 = monotone with non-overlapping adjacent CIs"
    return out


def sc1(series) -> Dict[str, Any]:
    faded = [r for r in _all_rows(series) if r["faded"]]
    res = S.cluster_bootstrap(_clusters(faded, lambda r: r["recent"] >= 0.75), S.share)
    return _metric("SC1", "I", "Fades are earned: share of faded turns where recent true success >= 0.75", "GT", res, 0.70,
                   ">=", details={"faded_turns": len(faded), "all_turns": len(_all_rows(series))})


def sc2(series) -> Dict[str, Any]:
    rows = [r for r in _all_rows(series) if r["level"] is not None]
    diffs = [(r["learner"], r["level"] - needed_level(r["recent"])) for r in rows]
    clusters: Dict[str, List[int]] = defaultdict(list)
    for learner, d in diffs:
        clusters[learner].append(d)
    res = S.cluster_bootstrap(clusters, lambda ds: S.share(abs(d) >= 2 for d in ds))
    over = S.cluster_bootstrap(clusters, lambda ds: S.share(d >= 2 for d in ds))
    under = S.cluster_bootstrap(clusters, lambda ds: S.share(d <= -2 for d in ds))
    return _metric("SC2", "I", "Support mismatch: share of turns two or more levels from the support the true state calls for",
                   "GT", res, 0.25, "<=", details={"over_supported": over, "under_supported": under, "turns": len(rows),
                                                   "bands": "recent >= .90 minimal, .75 low, .60 medium, .40 high, else very high"})


def _followed(levels: List[Optional[int]], i: int, direction: int, span: int) -> Optional[int]:
    """Turns after ``i`` until the level has moved one step in ``direction`` (+1 up, -1 down), or None."""
    base = levels[i]
    if base is None:
        return None
    for j in range(1, span + 1):
        if i + j >= len(levels):
            return None
        if levels[i + j] is not None and (levels[i + j] - base) * direction >= 1:
            return j
    return None


def t1(series) -> Dict[str, Any]:
    events = []
    for s in series:
        rows = s["rows"]
        levels = [r["level"] for r in rows]
        i = 3
        while i < len(rows) - 1:
            a, b = rows[i]["recent"], rows[i - 3]["recent"]
            if a is None or b is None or abs(a - b) < SHIFT or levels[i] is None:
                i += 1
                continue
            direction = -1 if a > b else +1  # success up: support should ease; success down: it should rise
            lag = _followed(levels, i, direction, 6)
            events.append({"learner": s["learner"], "lag": lag, "within": lag is not None and lag <= RESPONSE_TURNS,
                           "direction": "success_up" if a > b else "success_down"})
            i += 3
    res = S.cluster_bootstrap(_clusters(events, lambda e: e["within"]), S.share)
    lags = [e["lag"] for e in events if e["lag"] is not None]
    by_dir = {d: S.share(e["within"] for e in events if e["direction"] == d) for d in ("success_up", "success_down")}
    return _metric("T1", "I", f"Lag: support follows a shift in the true state within {RESPONSE_TURNS} turns", "GT", res, 0.60,
                   ">=", details={"shifts": len(events), "median_lag_turns_when_followed": float(np.median(lags)) if lags else None,
                                  "never_followed_within_6": sum(e["lag"] is None for e in events), "by_direction": by_dir})


def _reversals(xs: List[Optional[float]], recent: List[Optional[float]], step: float):
    """(reversals, flat_turns): direction reversals among changes of at least ``step`` made while the true state was flat."""
    changes, flat = [], 0
    for k in range(1, len(xs)):
        if xs[k] is None or xs[k - 1] is None or recent[k] is None or recent[k - 1] is None:
            continue
        if abs(recent[k] - recent[k - 1]) < FLAT:
            flat += 1
            d = xs[k] - xs[k - 1]
            if abs(d) >= step:
                changes.append(1 if d > 0 else -1)
    return sum(1 for a, b in zip(changes, changes[1:]) if a != b), flat


def t2(series) -> List[Dict[str, Any]]:
    out = []
    for name, key, step, target in (("level", "level", 1.0, 1.5), ("load", "load", LOAD_STEP, 1.5), ("zpd", "zpd", ZPD_STEP, 1.5)):
        rows = []
        for s in series:
            flips, flat = _reversals([r[key] for r in s["rows"]], [r["recent"] for r in s["rows"]], step)
            rows.append({"learner": s["learner"], "flips": flips, "flat": flat})
        res = S.cluster_bootstrap(_clusters(rows), lambda rs: 10 * sum(r["flips"] for r in rs) / sum(r["flat"] for r in rs)
                                  if sum(r["flat"] for r in rs) else None)
        out.append(_metric(f"T2.{name}", "I", f"Oscillation: {name} direction reversals per 10 turns while the true state is flat",
                           "GT", res, target, "<=", details={"flat_turns": sum(r["flat"] for r in rows), "step": step}))
    return out


def t3(series) -> Dict[str, Any]:
    events = []
    for s in series:
        rows = s["rows"]
        i = 0
        while i < len(rows) - 2:
            j = i
            while j < len(rows) and not rows[j]["correct"]:
                j += 1
            if j - i >= 2 and j + 1 < len(rows) and rows[j]["correct"] and rows[j + 1]["correct"]:
                run_levels = [r["level"] for r in rows[i:j] if r["level"] is not None]
                after = [r["level"] for r in rows[j:j + 4] if r["level"] is not None]
                if run_levels and after:
                    events.append({"learner": s["learner"], "eased": min(after) <= max(run_levels) - 1})
                i = j + 2
            else:
                i = max(j, i + 1)
    res = S.cluster_bootstrap(_clusters(events, lambda e: e["eased"]), S.share)
    return _metric("T3", "I", "Recovery: after 2+ errors then 2 right answers, support eases within 4 turns", "GT", res, 0.60,
                   ">=", details={"recoveries_observed": len(events)})


def t4(series) -> Dict[str, Any]:
    slopes = defaultdict(lambda: defaultdict(list))
    for s in series:
        n = len(s["rows"])
        if n < 5:
            continue
        x = np.arange(n, dtype=float)
        for key in ("load", "zpd", "level", "fatigue", "p"):
            ys = [r[key] for r in s["rows"]]
            if all(y is not None for y in ys):
                slopes[key][s["learner"]].append(float(np.polyfit(x, np.array(ys, float), 1)[0]))
    details = {k: S.cluster_bootstrap(v, S.mean) for k, v in slopes.items()}
    return _metric("T4", "I", "Session arc: mean per-turn slope of cognitive load (see details for ZPD, support, fatigue, true success)",
                   "GT", details.get("load", {"value": None}), None, None, details=details)


def compute(data: RunData) -> List[Dict[str, Any]]:
    series = session_series(data)
    from simulation import arms

    return [cl1(series), cl2(series), zpd1(series), sc1(series), sc2(series), t1(series), *t2(series), t3(series), t4(series),
            *arms.run_metrics(data)]


# ---------------------------------------------------------------------------- SC3: the judged one

SUPPORT_ITEMS = ["support_fit"]


def sc3(data: RunData) -> Dict[str, Any]:
    rows = [{"learner": j["learner"], "fit": v["support_fit"]}
            for j in data.main_judgements("support") if j["values"] for v in j["values"].values()]
    res = S.cluster_bootstrap(_clusters(rows, lambda r: r["fit"] == "about_right"), S.share)
    return _metric("SC3", "I", "Judged: support level and intervention were about right for the recent dialogue", "J", res, 0.70,
                   ">=", details={"too_much": S.share(r["fit"] == "too_much" for r in rows) if rows else None,
                                  "too_little": S.share(r["fit"] == "too_little" for r in rows) if rows else None,
                                  "judged_turns": len(rows)})
