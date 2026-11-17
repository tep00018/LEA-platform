"""Can cognitive load and ZPD be personalised from behaviour alone? (a numerical study, no LLM calls)

LEA computes both from fixed formulas (``agent_orchestrator_mcp``):

    CL  = 0.5 + 1.0*difficulty + 4.5*(1 - recent_accuracy) + 0.1*interaction_count + 1.0*task_type   (0-10)
    ZPD = recent_accuracy                                                                           (last 5 answers)

This module builds simulated learners whose *true* load and ZPD follow personal equations that
differ from LEA's (individual coefficients, a fatigue interaction, a load effect on performance),
emits the signals a real classroom would log (correctness, response time, hint requests, and an
occasional one-item self-rating of mental effort), and compares estimators that never see the
truth:

  E0  LEA's fixed formulas.
  E1  the same inputs plus response time and hints, coefficients fitted on a separate cohort's
      self-ratings (a population model).
  E2  E1 personalised per learner from that learner's own sparse self-ratings, shrunk toward E1.
  E3  no self-ratings at all: a per-learner latent factor from behaviour, mapped to the load scale
      by the population.

ZPD: Z0 = LEA's recent accuracy; Z1 = a population success model; Z2 = the same personalised from
the learner's own answers (no self-rating needed). Success predictions feed ``zpd = exp(-((p-0.7)/0.15)^2)``;
the truth uses each learner's own optimum and width.

Evaluation is prequential (each turn is estimated from earlier turns only) on turns after a cold
start of ``cold_start`` turns. Nothing here changes LEA; it says what is worth building.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import numpy as np

from simulation import stats as S

PROFILE_ABILITY = {"advanced_eager": 1.5, "capable_disengaged": 1.0, "moderate_reflective": 0.5,
                   "inconsistent_adaptive": 0.0, "struggling_eager": -1.0, "novice_variable": -1.5}
ZPD_CENTRE, ZPD_WIDTH = 0.70, 0.15
FEATURES = ["const", "difficulty", "inaccuracy", "interactions", "task", "rt_z", "hint"]


def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


@dataclass
class Config:
    learners_per_profile: int = 20
    turns: int = 40
    cold_start: int = 10
    sr_every: int = 5               # a self-rating every N turns (sparse calibration)
    train_learners: int = 60        # the separate cohort the population model is fitted on
    train_sr_every: int = 3
    misspecification: float = 1.0   # 0: LEA's own linear form is right; 1: fatigue interaction present
    heterogeneity: float = 1.0      # scale of personal coefficient differences
    kappa: float = 4.0              # shrinkage of personal fits toward the population fit
    seed: int = 20260926


# ---------------------------------------------------------------------------- the hidden truth

def simulate_learner(rng: np.random.Generator, profile: str, cfg: Config) -> Dict[str, np.ndarray]:
    h, m, T = cfg.heterogeneity, cfg.misspecification, cfg.turns
    c = {"c0": rng.normal(0.15, 0.05 * h), "c1": max(0.1, rng.normal(0.50, 0.15 * h)), "c2": rng.normal(0.10, 0.06 * h),
         "c3": max(0.0, rng.normal(0.20, 0.10 * h)), "c4": max(0.0, rng.normal(0.30, 0.15 * h))}
    gamma = max(0.0, rng.normal(1.0, 0.4 * h))
    r1 = max(0.2, rng.normal(1.0, 0.3 * h))
    centre, width = rng.normal(ZPD_CENTRE, 0.07 * h), max(0.08, rng.normal(0.18, 0.03 * h))
    tau = 30 * np.exp(rng.normal(0, 0.4 * h))
    ability = PROFILE_ABILITY[profile] + rng.normal(0, 0.3) + 0.6 * np.arange(T) / T
    difficulty = rng.uniform(0.2, 0.9, T)
    task = (rng.random(T) < 0.3).astype(float)
    t = np.arange(1, T + 1)
    fatigue = 1 - np.exp(-t / tau)
    skill = sigmoid(ability)
    demand = sigmoid(6 * (difficulty - skill))
    noise = np.zeros(T)
    for i in range(1, T):
        noise[i] = 0.6 * noise[i - 1] + rng.normal(0, 0.05)
    load = np.clip(c["c0"] + c["c1"] * demand + c["c2"] * task + c["c3"] * fatigue + m * c["c4"] * demand * fatigue + noise, 0, 1)
    p = 0.15 + 0.80 * sigmoid(5 * (skill - difficulty) - gamma * (load - 0.4) * 4)
    correct = (rng.random(T) < p).astype(float)
    log_rt = np.log(20) + r1 * load * 1.5 + 0.5 * task + 0.6 * difficulty + rng.normal(0, 0.35, T)
    hint = (rng.random(T) < sigmoid(-3 + 4 * load + (1 - p))).astype(float)
    sr = np.clip(np.round(1 + 8 * load + rng.normal(0, 0.8, T)), 1, 9)
    return {"difficulty": difficulty, "task": task, "n": t.astype(float), "load_true": 10 * load, "p_true": p,
            "correct": correct, "log_rt": log_rt, "hint": hint, "sr": (sr - 1) / 8 * 10,
            "zpd_true": np.exp(-((p - centre) / width) ** 2), "profile": profile}


def cohort(cfg: Config, n_per_profile: int, seed: int) -> List[Dict[str, Any]]:
    rng = np.random.default_rng(seed)
    out = []
    for profile in PROFILE_ABILITY:
        for k in range(n_per_profile):
            L = simulate_learner(rng, profile, cfg)
            L["learner"] = f"{profile}_{k}"
            out.append(L)
    return out


# ---------------------------------------------------------------------------- what a system can see

def recent_accuracy(correct: np.ndarray, upto: int, window: int = 5) -> float:
    """Accuracy over the last ``window`` answers up to and including ``upto`` (0.5 before any answer)."""
    lo = max(0, upto - window + 1)
    return float(correct[lo:upto + 1].mean()) if upto >= 0 else 0.5


class Norms:
    """Population reference for response time (a system would learn this from all its students)."""

    def __init__(self, train: List[Dict[str, Any]]):
        self.mu = {k: float(np.mean(np.concatenate([L["log_rt"][L["task"] == k] for L in train]))) for k in (0.0, 1.0)}
        self.sd = float(np.std(np.concatenate([L["log_rt"] for L in train])))

    def rt_z(self, L, t: int) -> float:
        return float((L["log_rt"][t] - self.mu[float(L["task"][t])]) / self.sd)


def load_features(L, t: int, norms: Norms) -> np.ndarray:
    acc = recent_accuracy(L["correct"], t)
    return np.array([1.0, L["difficulty"][t], 1 - acc, L["n"][t] / 10, L["task"][t], norms.rt_z(L, t), L["hint"][t]])


def success_features(L, t: int, norms: Norms) -> np.ndarray:
    """Known BEFORE answering turn t: this item's difficulty and type, the position, and the last turn's behaviour."""
    prev = t - 1
    acc = recent_accuracy(L["correct"], prev)
    return np.array([1.0, L["difficulty"][t], acc, L["n"][t] / 10, L["task"][t],
                     norms.rt_z(L, prev) if prev >= 0 else 0.0, L["hint"][prev] if prev >= 0 else 0.0])


def ridge(X, y, prior: Optional[np.ndarray], kappa: float) -> np.ndarray:
    prior = np.zeros(X.shape[1]) if prior is None else prior
    return np.linalg.solve(X.T @ X + kappa * np.eye(X.shape[1]), X.T @ y + kappa * prior)


def logistic(X, y, prior: Optional[np.ndarray], kappa: float, iters: int = 12) -> np.ndarray:
    prior = np.zeros(X.shape[1]) if prior is None else prior
    beta = prior.copy()
    for _ in range(iters):
        p = sigmoid(X @ beta)
        w = np.clip(p * (1 - p), 1e-4, None)
        grad = X.T @ (y - p) - kappa * (beta - prior)
        hess = (X * w[:, None]).T @ X + kappa * np.eye(X.shape[1])
        beta = beta + np.linalg.solve(hess, grad)
    return beta


# ---------------------------------------------------------------------------- estimators

LEA_CL = np.array([0.5, 1.0, 4.5, 1.0, 1.0, 0.0, 0.0])  # const, difficulty, 1-acc, interactions (x10), task ; LEA's 0.1/turn = 1.0 per 10


def lea_load(x: np.ndarray) -> float:
    return float(np.clip(x @ LEA_CL, 0, 10))


def fit_population(train, norms: Norms, cfg: Config) -> Dict[str, np.ndarray]:
    Xl, yl, Xs, ys = [], [], [], []
    for L in train:
        for t in range(len(L["correct"])):
            if t % cfg.train_sr_every == 0:
                Xl.append(load_features(L, t, norms))
                yl.append(L["sr"][t])
            Xs.append(success_features(L, t, norms))
            ys.append(L["correct"][t])
    beta_load = ridge(np.array(Xl), np.array(yl), None, 1e-3)
    beta_succ = logistic(np.array(Xs), np.array(ys), None, 1e-2)
    return {"load": beta_load, "success": beta_succ}


def proxy_factor_weights(P: np.ndarray, prior_cov: Optional[np.ndarray] = None, kappa: float = 20.0) -> np.ndarray:
    """Direction of most shared variation in behaviour (columns: rt_z, hint, inaccuracy), sign-anchored to
    inaccuracy. A learner's own covariance is blended with the population's, so a short history still gives a sane direction."""
    Z = P - P.mean(axis=0)
    n = len(Z)
    cov = Z.T @ Z / max(1, n - 1)
    if prior_cov is not None:
        cov = (n * cov + kappa * prior_cov) / (n + kappa)
    vals, vecs = np.linalg.eigh(cov)
    w = vecs[:, -1]
    return w if w[2] >= 0 else -w


def behaviour_matrix(L, norms: Norms) -> np.ndarray:
    return np.array([[norms.rt_z(L, t), L["hint"][t], 1 - recent_accuracy(L["correct"], t)] for t in range(len(L["correct"]))])


def population_covariance(train, norms: Norms) -> np.ndarray:
    Z = np.vstack([behaviour_matrix(L, norms) for L in train])
    Z = Z - Z.mean(axis=0)
    return Z.T @ Z / (len(Z) - 1)


def fit_factor_map(train, norms: Norms, cfg: Config, prior_cov: np.ndarray) -> np.ndarray:
    """Population map from the personal behaviour factor to the load scale (fitted with the cohort's self-ratings)."""
    f, y = [], []
    for L in train:
        P = behaviour_matrix(L, norms)
        for t in range(cfg.cold_start, len(P)):
            if t % cfg.train_sr_every == 0:
                w = proxy_factor_weights(P[:t], prior_cov)
                f.append(P[t] @ w)
                y.append(L["sr"][t])
    return ridge(np.column_stack([np.ones(len(f)), f]), np.array(y), None, 1e-3)


def run_learner(L, pop, factor_map, prior_cov, norms: Norms, cfg: Config) -> List[Dict[str, Any]]:
    T = len(L["correct"])
    rows = []
    X_hist = np.array([load_features(L, t, norms) for t in range(T)])
    S_hist = np.array([success_features(L, t, norms) for t in range(T)])
    P_hist = behaviour_matrix(L, norms)
    for t in range(cfg.cold_start, T):
        sr_idx = [i for i in range(t) if i % cfg.sr_every == 0]
        beta_i = ridge(X_hist[sr_idx], L["sr"][sr_idx], pop["load"], cfg.kappa) if sr_idx else pop["load"]
        w = proxy_factor_weights(P_hist[:t], prior_cov)
        succ_i = logistic(S_hist[:t], L["correct"][:t], pop["success"], cfg.kappa)
        est = {
            "E0": lea_load(X_hist[t]),
            "E1": float(np.clip(X_hist[t] @ pop["load"], 0, 10)),
            "E2": float(np.clip(X_hist[t] @ beta_i, 0, 10)),
            "E3": float(np.clip(factor_map[0] + factor_map[1] * (P_hist[t] @ w), 0, 10)),
        }
        acc_prev = recent_accuracy(L["correct"], t - 1)
        p_hat = {"Z0": acc_prev, "Z1": float(sigmoid(S_hist[t] @ pop["success"])), "Z2": float(sigmoid(S_hist[t] @ succ_i))}
        row = {"learner": L["learner"], "profile": L["profile"], "t": t, "load_true": L["load_true"][t],
               "zpd_true": L["zpd_true"][t], "correct": L["correct"][t], "p_true": L["p_true"][t]}
        row.update({k: v for k, v in est.items()})
        for k, v in p_hat.items():
            row[f"{k}_p"] = v
            row[k] = float(np.exp(-((v - ZPD_CENTRE) / ZPD_WIDTH) ** 2))
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------- scoring

LOAD_EST = ["E0", "E1", "E2", "E3"]
ZPD_EST = ["Z0", "Z1", "Z2"]


def _within_r(rows: List[Dict[str, Any]], est: str, truth: str) -> Optional[float]:
    by: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        by.setdefault(r["learner"], []).append(r)
    rs = []
    for rr in by.values():
        a, b = np.array([r[est] for r in rr]), np.array([r[truth] for r in rr])
        if a.std() > 1e-9 and b.std() > 1e-9:
            rs.append(np.corrcoef(a, b)[0, 1])
    return float(np.mean(rs)) if rs else None


def score(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    clusters = S.group_by(rows, "learner")

    def stat(fn):
        return S.cluster_bootstrap(clusters, fn, n=400)

    out: Dict[str, Any] = {"turns_scored": len(rows), "learners": len(clusters), "load": {}, "zpd": {}}
    for e in LOAD_EST:
        out["load"][e] = {
            "r_pooled": stat(lambda rs, e=e: S.pearson([r[e] for r in rs], [r["load_true"] for r in rs])),
            "mae": stat(lambda rs, e=e: float(np.mean([abs(r[e] - r["load_true"]) for r in rs]))),
            "r_within_learner": _within_r(rows, e, "load_true")}
    for e in ZPD_EST:
        out["zpd"][e] = {
            "r_with_true_zpd": stat(lambda rs, e=e: S.pearson([r[e] for r in rs], [r["zpd_true"] for r in rs])),
            "brier": stat(lambda rs, e=e: float(np.mean([(r[f"{e}_p"] - r["correct"]) ** 2 for r in rs]))),
            "r_p_with_true_p": stat(lambda rs, e=e: S.pearson([r[f"{e}_p"] for r in rs], [r["p_true"] for r in rs]))}
    by_learner = {}
    for name, rr in clusters.items():
        by_learner[name] = {e: float(np.mean([abs(r[e] - r["load_true"]) for r in rr])) for e in LOAD_EST}
    out["share_of_learners_where_personal_beats_population"] = {
        "E2_vs_E1": float(np.mean([v["E2"] < v["E1"] for v in by_learner.values()])),
        "E3_vs_E0": float(np.mean([v["E3"] < v["E0"] for v in by_learner.values()]))}
    return out


def study(cfg: Optional[Config] = None) -> Dict[str, Any]:
    cfg = cfg or Config()
    train = cohort(cfg, cfg.train_learners // len(PROFILE_ABILITY) + 1, cfg.seed + 1)
    norms = Norms(train)
    pop = fit_population(train, norms, cfg)
    prior_cov = population_covariance(train, norms)
    factor_map = fit_factor_map(train, norms, cfg, prior_cov)
    test = cohort(cfg, cfg.learners_per_profile, cfg.seed)
    rows = [r for L in test for r in run_learner(L, pop, factor_map, prior_cov, norms, cfg)]
    result = score(rows)
    result["config"] = cfg.__dict__.copy()
    result["population_load_coefficients"] = dict(zip(FEATURES, map(float, pop["load"])))
    return result


def sensitivity(base: Optional[Config] = None) -> Dict[str, Any]:
    """The same study with one setting changed at a time."""
    base = base or Config()
    grid = {"sr_every": [3, 5, 10], "cold_start": [5, 10, 20], "turns": [40, 80], "misspecification": [0.0, 1.0],
            "heterogeneity": [0.0, 1.0, 1.5], "kappa": [1.0, 4.0, 20.0, 80.0]}
    out = {}
    for key, values in grid.items():
        for v in values:
            cfg = Config(**{**base.__dict__, key: v})
            r = study(cfg)
            out[f"{key}={v}"] = {"load_r_within": {e: r["load"][e]["r_within_learner"] for e in LOAD_EST},
                                 "load_r_pooled": {e: r["load"][e]["r_pooled"]["value"] for e in LOAD_EST},
                                 "zpd_r": {e: r["zpd"][e]["r_with_true_zpd"]["value"] for e in ZPD_EST},
                                 "brier": {e: r["zpd"][e]["brier"]["value"] for e in ZPD_EST}}
    return out


def format_report(main: Dict[str, Any], sens: Optional[Dict[str, Any]] = None) -> str:
    def ci(d):
        return f"{d['value']:.2f} [{d['lo']:.2f}, {d['hi']:.2f}]" if d.get("lo") is not None else f"{d['value']:.2f}"

    names = {"E0": "E0 LEA fixed formula", "E1": "E1 population model", "E2": "E2 personal, sparse self-ratings",
             "E3": "E3 personal, no self-ratings", "Z0": "Z0 LEA recent accuracy", "Z1": "Z1 population success model",
             "Z2": "Z2 personal success model"}
    c = main["config"]
    lines = ["# Personalised cognitive load and ZPD: simulation study", "",
             f"{main['learners']} learners, {c['turns']} turns each, cold start {c['cold_start']}, a self-rating every "
             f"{c['sr_every']} turns (E2 only), fatigue-interaction strength {c['misspecification']}, personal "
             f"differences x{c['heterogeneity']}. {main['turns_scored']} turns scored after the cold start; "
             "CIs are cluster bootstrap over learners.", "", "## Cognitive load (truth: the hidden personal load, 0-10)", "",
             "| Estimator | r, pooled | MAE (load points) | r, within learner |", "|---|---|---|---|"]
    for e, v in main["load"].items():
        lines.append(f"| {names[e]} | {ci(v['r_pooled'])} | {ci(v['mae'])} | {v['r_within_learner']:.2f} |")
    lines += ["", "## ZPD", "", "| Estimator | r with true ZPD | Brier (lower is better) | r(p, true p) |", "|---|---|---|---|"]
    for e, v in main["zpd"].items():
        lines.append(f"| {names[e]} | {ci(v['r_with_true_zpd'])} | {ci(v['brier'])} | {ci(v['r_p_with_true_p'])} |")
    share = main["share_of_learners_where_personal_beats_population"]
    lines += ["", f"Learners for whom E2 has lower load error than E1: {share['E2_vs_E1']:.0%}; E3 lower than LEA's formula: "
                  f"{share['E3_vs_E0']:.0%}."]
    if sens:
        lines += ["", "## Sensitivity (within-learner load r; ZPD r with truth)", "",
                  "| Setting | E0 | E1 | E2 | E3 | Z0 | Z1 | Z2 |", "|---|---|---|---|---|---|---|---|"]
        for k, v in sens.items():
            cells = [f"{v['load_r_within'][e]:.2f}" if v["load_r_within"][e] is not None else "-" for e in LOAD_EST]
            cells += [f"{v['zpd_r'][e]:.2f}" for e in ZPD_EST]
            lines.append(f"| {k} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"
