"""Statistics for the simulation (docs/simulation/PLAN.md, section 5).

The unit of analysis is the simulated learner: 95% CIs come from a cluster bootstrap over
learners (2,000 resamples), never from treating turns as independent. Agreement uses
Cohen's kappa (two raters), Fleiss' kappa (repeats) and ICC(2,1) (scales). Profile
comparisons use a mixed model (profile fixed, learner random) when ``statsmodels`` is
installed, with Holm's correction across the pre-registered tests.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Any, Callable, Dict, Hashable, Iterable, List, Optional, Sequence, Tuple

import numpy as np
from scipy import stats as sps

B = 2000


def cluster_bootstrap(clusters: Dict[Hashable, Sequence[Any]], statistic: Callable[[List[Any]], Optional[float]],
                      n: int = B, seed: int = 0, alpha: float = 0.05) -> Dict[str, Optional[float]]:
    """``statistic`` over all observations, with a percentile CI from resampling whole
    clusters (learners) with replacement. Resamples where the statistic is undefined are
    skipped (and counted)."""
    keys = sorted(clusters, key=str)
    flat = [x for k in keys for x in clusters[k]]
    value = statistic(flat) if flat else None
    if value is None or len(keys) < 2:
        return {"value": value, "lo": None, "hi": None, "n_clusters": len(keys), "n": len(flat), "undefined": 0}
    rng = np.random.default_rng(seed)
    draws, undefined = [], 0
    for _ in range(n):
        picked = rng.integers(0, len(keys), len(keys))
        sample = [x for i in picked for x in clusters[keys[i]]]
        v = statistic(sample)
        if v is None or (isinstance(v, float) and math.isnan(v)):
            undefined += 1
            continue
        draws.append(v)
    if not draws:
        return {"value": value, "lo": None, "hi": None, "n_clusters": len(keys), "n": len(flat), "undefined": undefined}
    lo, hi = np.percentile(draws, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return {"value": float(value), "lo": float(lo), "hi": float(hi), "n_clusters": len(keys), "n": len(flat),
            "undefined": undefined}


def mean(xs: Iterable[float]) -> Optional[float]:
    xs = [float(x) for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def share(xs: Iterable[bool]) -> Optional[float]:
    xs = [bool(x) for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def cohen_kappa(a: Sequence[Hashable], b: Sequence[Hashable]) -> Optional[float]:
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if not pairs:
        return None
    n = len(pairs)
    po = sum(x == y for x, y in pairs) / n
    ca, cb = Counter(x for x, _ in pairs), Counter(y for _, y in pairs)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    if pe == 1:
        return 1.0 if po == 1 else 0.0
    return (po - pe) / (1 - pe)


def fleiss_kappa(ratings: Sequence[Sequence[Hashable]]) -> Optional[float]:
    """Each row: the labels one item got from its repeats (same number per row)."""
    rows = [list(r) for r in ratings if r and None not in r]
    if not rows or len({len(r) for r in rows}) != 1 or len(rows[0]) < 2:
        return None
    m = len(rows[0])
    cats = sorted({x for r in rows for x in r}, key=str)
    counts = np.array([[r.count(c) for c in cats] for r in rows], dtype=float)
    p_i = ((counts * (counts - 1)).sum(axis=1)) / (m * (m - 1))
    p_bar = p_i.mean()
    p_j = counts.sum(axis=0) / (len(rows) * m)
    pe = (p_j ** 2).sum()
    if pe == 1:
        return 1.0 if p_bar == 1 else 0.0
    return float((p_bar - pe) / (1 - pe))


def icc_2_1(ratings: Sequence[Sequence[float]]) -> Optional[float]:
    """ICC(2,1): two-way random effects, absolute agreement, single rater."""
    x = np.array([list(map(float, r)) for r in ratings if r and None not in r])
    if x.ndim != 2 or x.shape[0] < 2 or x.shape[1] < 2:
        return None
    n, k = x.shape
    grand = x.mean()
    ss_rows = k * ((x.mean(axis=1) - grand) ** 2).sum()
    ss_cols = n * ((x.mean(axis=0) - grand) ** 2).sum()
    ss_err = ((x - grand) ** 2).sum() - ss_rows - ss_cols
    ms_r, ms_c, ms_e = ss_rows / (n - 1), ss_cols / (k - 1), ss_err / ((n - 1) * (k - 1))
    denom = ms_r + (k - 1) * ms_e + k * (ms_c - ms_e) / n
    return float((ms_r - ms_e) / denom) if denom else None


def macro_f1(truth: Sequence[Hashable], predicted: Sequence[Hashable], labels: Sequence[Hashable]) -> Optional[float]:
    pairs = [(t, p) for t, p in zip(truth, predicted) if t is not None and p is not None]
    if not pairs:
        return None
    scores = []
    for c in labels:
        tp = sum(1 for t, p in pairs if t == c and p == c)
        fp = sum(1 for t, p in pairs if t != c and p == c)
        fn = sum(1 for t, p in pairs if t == c and p != c)
        if tp + fp + fn == 0:
            continue
        scores.append(2 * tp / (2 * tp + fp + fn))
    return sum(scores) / len(scores) if scores else None


def confusion(truth: Sequence[Hashable], predicted: Sequence[Hashable], labels_t: Sequence, labels_p: Sequence
              ) -> Dict[str, Dict[str, int]]:
    out = {str(t): {str(p): 0 for p in labels_p} for t in labels_t}
    for t, p in zip(truth, predicted):
        if str(t) in out and str(p) in out[str(t)]:
            out[str(t)][str(p)] += 1
    return out


def spearman(x: Sequence[float], y: Sequence[float]) -> Optional[float]:
    pairs = [(a, b) for a, b in zip(x, y) if a is not None and b is not None]
    if len(pairs) < 3 or len({a for a, _ in pairs}) < 2 or len({b for _, b in pairs}) < 2:
        return None
    return float(sps.spearmanr([a for a, _ in pairs], [b for _, b in pairs]).statistic)


def pearson(x: Sequence[float], y: Sequence[float]) -> Optional[float]:
    pairs = [(a, b) for a, b in zip(x, y) if a is not None and b is not None]
    if len(pairs) < 3 or len({a for a, _ in pairs}) < 2 or len({b for _, b in pairs}) < 2:
        return None
    return float(sps.pearsonr([a for a, _ in pairs], [b for _, b in pairs]).statistic)


def kendall_tau(x: Sequence[float], y: Sequence[float]) -> Optional[float]:
    if len(x) < 2:
        return None
    return float(sps.kendalltau(x, y).statistic)


def holm(pvalues: Dict[str, float]) -> Dict[str, float]:
    """Holm-adjusted p-values (monotone)."""
    items = sorted(pvalues.items(), key=lambda kv: kv[1])
    m, running, out = len(items), 0.0, {}
    for i, (name, p) in enumerate(items):
        running = max(running, min(1.0, (m - i) * p))
        out[name] = running
    return out


def profile_contrasts(rows: List[Dict[str, Any]], outcome: str, order: List[str]) -> Dict[str, Any]:
    """Adjacent-profile differences in ``outcome`` from a mixed model (profile fixed,
    learner random), Holm-corrected. Needs statsmodels; otherwise says so."""
    try:
        import pandas as pd
        import statsmodels.formula.api as smf
    except ImportError:
        return {"available": False, "reason": "statsmodels is not installed (pip install -e .[sim])"}
    df = pd.DataFrame([r for r in rows if r.get(outcome) is not None])
    if df.empty or df["learner"].nunique() < 3 or df["profile"].nunique() < 2:
        return {"available": False, "reason": "too few learners or profiles"}
    out, pvals = {}, {}
    present = [p for p in order if p in set(df["profile"])]
    for a, b in zip(present, present[1:]):
        sub = df[df["profile"].isin([a, b])].copy()
        sub["is_b"] = (sub["profile"] == b).astype(float)
        try:
            fit = smf.mixedlm(f"{outcome} ~ is_b", sub, groups=sub["learner"]).fit(reml=True, method="lbfgs")
            est, ci = float(fit.params["is_b"]), fit.conf_int().loc["is_b"].tolist()
            out[f"{b} - {a}"] = {"estimate": est, "lo": float(ci[0]), "hi": float(ci[1])}
            pvals[f"{b} - {a}"] = float(fit.pvalues["is_b"])
        except Exception as e:  # singular fits with tiny samples
            out[f"{b} - {a}"] = {"estimate": None, "error": str(e)[:120]}
    for name, p in holm(pvals).items():
        out[name]["p_holm"] = p
    return {"available": True, "contrasts": out}


def group_by(rows: Iterable[Dict[str, Any]], key: str) -> Dict[Any, List[Dict[str, Any]]]:
    out: Dict[Any, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        out[r[key]].append(r)
    return out


def ci_tuple(result: Dict[str, Any]) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    return result.get("value"), result.get("lo"), result.get("hi")
