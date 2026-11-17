"""Simulator validity checks that need no LEA and no model (docs/simulation/PLAN.md, M0c).

M0c: the simulated learners behave as the BKT formulas say. For every profile, with
``draws`` independent draws each:

- starting knowledge: the share of GOs known at the start against ``sigmoid(theta - b)``;
- answering: accuracy when known (session shift 0) against ``1 - slip - d_type``, and
  when unknown against ``guess[type]``, for every question type;
- learning: the share known after ``n`` tutor exchanges against
  ``1 - (1 - p0)(1 - p_learn)^n``.

Passes when every deviation is within ``tolerance`` (1 point).
"""

from __future__ import annotations

from typing import Any, Dict

from simulation.learner import QUESTION_TYPES, Intent, Learner, build_profiles, learner_seed, sigmoid


def m0c(config: Dict[str, Any], draws: int = 10_000, tolerance: float = 0.01, b: float = 0.0,
        exchanges: int = 3) -> Dict[str, Any]:
    profiles = build_profiles(config)
    cfg = config["learner"]
    rows = []
    for key, profile in profiles.items():
        gos = {f"G{i:05d}": b for i in range(draws)}
        learner = Learner(f"m0c_{key}", profile, gos, cfg, learner_seed(int(config["seed"]), f"m0c:{key}", 0))
        rows.append(_row(key, "start known", sum(learner.known.values()) / draws, sigmoid(profile.theta - b)))

        learner.eps = 0.0
        for qtype in QUESTION_TYPES:
            for known in (True, False):
                for g in gos:
                    learner.known[g] = known
                hits = sum(learner.turn(g, qtype, may_digress=False).correct for g in gos)
                expected = learner.p_correct_if_known(qtype) if known else float(cfg["guess"][qtype])
                rows.append(_row(key, f"{qtype} {'known' if known else 'unknown'}", hits / draws, expected))

        fresh = Learner(f"m0c_learn_{key}", profile, gos, cfg, learner_seed(int(config["seed"]), f"m0c-l:{key}", 0))
        engaged = Intent("answer", None, "tutor_reply", None, None, None, "steady", None)
        for g in gos:
            for _ in range(exchanges):
                fresh.after_tutor_exchange(g, engaged)
        p0 = sigmoid(profile.theta - b)
        expected = 1 - (1 - p0) * (1 - profile.p_learn) ** exchanges
        rows.append(_row(key, f"known after {exchanges} exchanges", sum(fresh.known.values()) / draws, expected))
        rows.append(_row(key, f"p_know after {exchanges} exchanges", fresh.p_know("G00000"), expected, exact=True))
    worst = max(r["deviation"] for r in rows)
    return {"metric": "M0c", "draws": draws, "tolerance": tolerance, "max_deviation": round(worst, 4),
            "passed": worst <= tolerance, "rows": rows}


def _row(profile: str, check: str, observed: float, expected: float, exact: bool = False) -> Dict[str, Any]:
    return {"profile": profile, "check": check, "observed": round(observed, 4), "expected": round(expected, 4),
            "deviation": round(abs(observed - expected), 4), "exact": exact}
