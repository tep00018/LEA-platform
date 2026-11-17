"""Fit the personal cognitive-load equation's population coefficients on simulated students.

No language models are called: students here are only the hidden-load generator in
``signals.py`` answering a stream of items. What this produces stands in for the calibration
study you would run in a real classroom (self-ratings plus logged behaviour); the coefficients
are only as good as that generator, and they are refitted on classroom data when it exists.

Three passes over the same simulated cohort:
1. the population norms (typical thinking-time residual and typing pace, and their within-student spread);
2. the equation's coefficients, by ridge regression of a noisy self-rating (as a real one would be,
   every third turn) on the features the equation uses;
3. how strongly a relative effort rating follows a change in behaviour, so a student's own ratings
   can be read as more or less sensitive than that.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

from simulation.learner import learner_seed
from simulation.signals import HumanSignals
from src.core.cognitive_load import DEFAULT_POPULATION, POPULATION_PATH, MemoryStore, PersonalLoad

PROFILE_SUCCESS = {"advanced_eager": 0.85, "capable_disengaged": 0.75, "moderate_reflective": 0.65,
                   "inconsistent_adaptive": 0.55, "struggling_eager": 0.45, "novice_variable": 0.35}
FEATURES = ["b0", "demand", "errors", "slow", "help", "typing", "fatigue", "demand_fatigue", "task"]
SR_EVERY = 3


def _stream(learner_index: int, profile: str, seed: int, turns: int, per_session: int = 25, per_objective: int = 8):
    """Yield (turn dict for PersonalLoad, truth) for one simulated learner."""
    sig = HumanSignals(learner_seed(seed, profile, learner_index))
    rng = np.random.default_rng(learner_seed(seed + 1, profile, learner_index))
    history: List[bool] = []
    base = PROFILE_SUCCESS[profile]
    engagement = "steady"
    for t in range(turns):
        if t % per_session == 0:
            sig.start_session()
        if t % 10 == 0:
            engagement = str(rng.choice(["engaged", "steady", "disengaging"], p=[0.3, 0.5, 0.2]))
        p = float(np.clip(base + 0.004 * t + rng.normal(0, 0.12), 0.05, 0.98))
        correct = bool(rng.random() < p)
        difficulty = float(rng.uniform(0.3, 0.8))
        mastery = float(np.clip(p + rng.normal(0, 0.1), 0, 1))
        task = float(rng.random() < 0.4)
        prompt_chars = int(rng.integers(80, 500))
        chars = int(rng.integers(3, 30) if task == 0 else rng.integers(60, 260))
        obs = sig.observe(f"go{t // per_objective}", demand=1 - p, task=task, prompt_chars=prompt_chars, chars=chars,
                          kind="answer", engagement=engagement, answer_attempt=True)
        yield {"difficulty": difficulty, "mastery": mastery, "correct_history": list(history), "task_type": task,
               "interaction_count": t + 1, "timing": obs["timing"]}, obs["true_load"]
        history.append(correct)


def _self_rating(true_load: float, rng: np.random.Generator) -> float:
    """A one-item effort rating (1 to 9) as it would be given, mapped back to 0..1."""
    return (float(np.clip(np.round(1 + 8 * true_load / 10 + rng.normal(0, 0.8)), 1, 9)) - 1) / 8


def collect(pop: Dict[str, Any], seed: int, learners: int, turns: int) -> Dict[str, Any]:
    rows, r_think, r_pace = [], {}, {}
    for profile in PROFILE_SUCCESS:
        for k in range(learners):
            model = PersonalLoad(MemoryStore(), pop)
            rng = np.random.default_rng(learner_seed(seed + 2, profile, k))
            name = f"{profile}_{k}"
            for t, (turn, truth) in enumerate(_stream(k, profile, seed, turns)):
                d = model.estimate(name, difficulty=turn["difficulty"], mastery=turn["mastery"],
                                   correct_history=turn["correct_history"], task_type=turn["task_type"],
                                   interaction_count=turn["interaction_count"], timing=turn["timing"])
                if "r_think" in d and not d["rapid_guess"] and not d["away"]:
                    r_think.setdefault(name, []).append(d["r_think"])
                if "r_pace" in d:
                    r_pace.setdefault(name, []).append(d["r_pace"])
                if t % SR_EVERY == 0 and t >= 5:
                    rows.append(([1.0, d["demand"], d["errors"], d["slow"], d["help"], d["typing"], d["fatigue"],
                                  d["demand_fatigue"], d["task"]], _self_rating(truth, rng), truth / 10))
    return {"rows": rows, "r_think": r_think, "r_pace": r_pace}


def within_stats(series: Dict[str, List[float]]):
    allv = np.concatenate([np.array(v) for v in series.values()])
    within = np.sqrt(np.mean([np.var(v) for v in series.values() if len(v) > 3]))
    return float(allv.mean()), float(within)


def rating_scale(pop: Dict[str, Any], seed: int, learners: int, turns: int) -> float:
    """Slope of a relative rating on the change in behavioural load between objectives, pooled over students."""
    xs, ys = [], []
    for profile in PROFILE_SUCCESS:
        for k in range(learners):
            model = PersonalLoad(MemoryStore(), pop)
            sig_seed = learner_seed(seed, profile, k)
            probe = HumanSignals(sig_seed)  # the same student: its rating gain and noise are what the client would send
            name = f"{profile}_{k}"
            prev, objective, mean_load, prev_load = None, [], [], None
            for t, (turn, truth) in enumerate(_stream(k, profile, seed, turns)):
                d = model.estimate(name, difficulty=turn["difficulty"], mastery=turn["mastery"],
                                   correct_history=turn["correct_history"], task_type=turn["task_type"],
                                   interaction_count=turn["interaction_count"], timing=turn["timing"], update=True)
                objective.append(d["behaviour"])
                mean_load.append(truth)
                if (t + 1) % 8 == 0:
                    b, ld = float(np.mean(objective)), float(np.mean(mean_load))
                    if prev is not None:
                        rating = probe.p["gain"] * (ld - prev_load) / 10 * 8
                        xs.append(b - prev)
                        ys.append(float(np.clip(rating + np.random.default_rng(t + k).normal(0, 0.5), -2, 2)))
                    prev, prev_load, objective, mean_load = b, ld, [], []
    x, y = np.array(xs), np.array(ys)
    return float((x @ y) / max(x @ x, 1e-9)) if len(x) else 1.0


def fit(seed: int = 20260927, learners: int = 20, turns: int = 60, kappa: float = 1.0) -> Dict[str, Any]:
    pop = json.loads(json.dumps(DEFAULT_POPULATION))
    first = collect(pop, seed, learners, turns)
    pop["norms"]["think_mu"], pop["norms"]["think_sd"] = within_stats(first["r_think"])
    pop["norms"]["pace_mu"], pop["norms"]["pace_sd"] = within_stats(first["r_pace"])
    second = collect(pop, seed, learners, turns)
    X = np.array([r[0] for r in second["rows"]])
    y = np.array([r[1] for r in second["rows"]])
    beta = np.linalg.solve(X.T @ X + kappa * np.eye(X.shape[1]), X.T @ y)
    pop["coef"] = dict(zip(["b0", "demand", "errors", "slow", "help", "typing", "fatigue", "demand_fatigue", "task"],
                           map(float, beta)))
    pop["rating_scale"] = rating_scale(pop, seed, learners, turns)
    fitted = X @ beta
    truth = np.array([r[2] for r in second["rows"]])
    pop["version"] = f"simulated-{date.today().isoformat()}"
    pop["fit"] = {"seed": seed, "learners": learners * len(PROFILE_SUCCESS), "turns_each": turns, "ratings_used": len(y),
                  "r_with_self_rating": float(np.corrcoef(fitted, y)[0, 1]), "r_with_true_load": float(np.corrcoef(fitted, truth)[0, 1]),
                  "note": "Fitted on simulated students (simulation/cl_calibration.py); replace with classroom data."}
    return pop


def write(pop: Dict[str, Any], path: Path = POPULATION_PATH) -> Path:
    Path(path).write_text(json.dumps(pop, indent=2), encoding="utf-8")
    return Path(path)
