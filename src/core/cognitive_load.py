"""Cognitive load: the fixed equation and a personalised one, selectable per process.

``fixed`` is the equation LEA has always used (``agent_orchestrator_mcp``: difficulty,
recent accuracy, interaction count, task type). ``personal`` adds signals a client can log
without hardware and learns each student's own normal, so that "slow for this student" is
what raises load, not "slow".

Selected by ``LEA_COGNITIVE_LOAD_MODEL`` (``fixed`` by default; nothing changes unless it is
set to ``personal``). Both values are computed on every turn and the selected one drives
scaffolding, so a single run records both for comparison.

The personal equation, on a 0 to 10 scale::

    CL = 10 * clip(b0 + b_demand*demand + b_err*errors + g*(b_slow*slow + b_help*help + b_typing*typing)
                   + b_fatigue*fatigue + b_df*demand*fatigue + b_task*task, 0, 1)

- demand: 0.5 + item difficulty - the learner's mastery of the objective (0 to 1).
- errors: recent error rate, each earlier answer counting 0.6 as much as the next.
- slow: how far this answer's thinking time is above the student's own norm, after allowing
  for the length of the prompt and the task type; a z-score against the student's running
  baseline (shrunk toward the population's while the history is short), capped, scaled to -1..1.
  Rapid guesses (very fast and well below the norm) and away times (over ten minutes) don't
  update the baseline, and a rapid guess adds nothing to load.
- help: a decayed rate of hint requests.
- typing: typing pace slower than the student's own norm (characters per second).
- fatigue: 1 - exp(-minutes on task / 25); the client reports elapsed time.
- g: a personal sensitivity to the behavioural terms, learned from the student's optional
  one-tap effort ratings ("easier / harder than the last objective") and shrunk toward 1.

The population coefficients are in ``cognitive_load_population.json``, fitted offline
(``python -m simulation fit-cognitive-load``) on simulated students until classroom data
replaces them. Nothing here is a validated model of real students.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

MODEL_ENV = "LEA_COGNITIVE_LOAD_MODEL"
POPULATION_PATH = Path(__file__).with_name("cognitive_load_population.json")

DEFAULT_POPULATION: Dict[str, Any] = {
    "version": "default",
    "coef": {"b0": 0.05, "demand": 0.30, "errors": 0.20, "slow": 0.12, "help": 0.12, "typing": 0.06,
             "fatigue": 0.12, "demand_fatigue": 0.10, "task": 0.05},
    "norms": {"think_mu": 7.1, "think_sd": 0.6, "pace_mu": 1.1, "pace_sd": 0.5},
    "kappa": 8.0,          # how many observations the population's baseline is worth
    "rating_kappa": 6.0,   # how many ratings the population's sensitivity (g = 1) is worth
    "rating_scale": 1.0,   # population slope of a rating on the behavioural change between objectives
}
ERROR_DECAY = 0.6
HELP_ALPHA = 0.3
FATIGUE_MINUTES = 25.0
AWAY_MS = 10 * 60 * 1000
RAPID_MS = 2500
MIN_TYPING_CHARS, MIN_TYPING_MS = 15, 1500


def selected_model() -> str:
    return "personal" if os.getenv(MODEL_ENV, "fixed").strip().lower() == "personal" else "fixed"


def load_population(path: Path = POPULATION_PATH) -> Dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return DEFAULT_POPULATION
    return {**DEFAULT_POPULATION, **data, "coef": {**DEFAULT_POPULATION["coef"], **data.get("coef", {})},
            "norms": {**DEFAULT_POPULATION["norms"], **data.get("norms", {})}}


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def parse_timing(raw: Any) -> Optional[Dict[str, Any]]:
    """The client's timing block, validated. Anything missing or absurd simply isn't used."""
    if not isinstance(raw, dict):
        return None
    out: Dict[str, Any] = {}
    for key in ("response_ms", "typing_ms", "chars", "prompt_chars", "elapsed_ms"):
        try:
            v = float(raw.get(key))
        except (TypeError, ValueError):
            continue
        if math.isfinite(v) and 0 <= v <= 24 * 3600 * 1000:
            out[key] = v
    out["hint_requested"] = bool(raw.get("hint_requested"))
    try:
        rating = int(raw.get("effort_rating"))
        if -2 <= rating <= 2:
            out["effort_rating"] = rating
    except (TypeError, ValueError):
        pass
    return out if any(k in out for k in ("response_ms", "typing_ms", "chars", "elapsed_ms")) or "effort_rating" in out \
        or out["hint_requested"] else None


class MemoryStore:
    """Baselines in a dict (calibration and tests)."""

    def __init__(self):
        self.data: Dict[str, Dict[str, Any]] = {}

    def load(self, username: str) -> Dict[str, Any]:
        return json.loads(json.dumps(self.data.get(username, {})))

    def save(self, username: str, state: Dict[str, Any]) -> None:
        self.data[username] = json.loads(json.dumps(state))


class RedisStore:
    def __init__(self, redis_client):
        self.redis = redis_client

    def _key(self, username: str) -> str:
        return f"cl_baseline:{username}"

    def load(self, username: str) -> Dict[str, Any]:
        try:
            raw = self.redis.get_redis().get(self._key(username))
            return json.loads(raw) if raw else {}
        except Exception:
            return {}

    def save(self, username: str, state: Dict[str, Any]) -> None:
        try:
            self.redis.get_redis().set(self._key(username), json.dumps(state))
        except Exception:
            pass


class _Running:
    """Running mean and variance (Welford), with the population's value standing in early on."""

    def __init__(self, d: Optional[Dict[str, float]] = None):
        d = d or {}
        self.n, self.mean, self.m2 = int(d.get("n", 0)), float(d.get("mean", 0.0)), float(d.get("m2", 0.0))

    def shrunk(self, mu0: float, sd0: float, kappa: float):
        var = self.m2 / self.n if self.n > 1 else sd0 ** 2
        mu = (self.n * self.mean + kappa * mu0) / (self.n + kappa)
        sd = math.sqrt((self.n * var + kappa * sd0 ** 2) / (self.n + kappa))
        return mu, max(sd, 0.15)

    def add(self, x: float) -> None:
        self.n += 1
        delta = x - self.mean
        self.mean += delta / self.n
        self.m2 += delta * (x - self.mean)

    def dump(self) -> Dict[str, float]:
        return {"n": self.n, "mean": self.mean, "m2": self.m2}


def error_rate(correct_newest_last: List[bool]) -> float:
    """Recent error rate with geometric weights, newest answer heaviest (0.5 with no answers)."""
    if not correct_newest_last:
        return 0.5
    weights = [ERROR_DECAY ** k for k in range(len(correct_newest_last))]
    errs = [0.0 if c else 1.0 for c in reversed(correct_newest_last)]
    return sum(w * e for w, e in zip(weights, errs)) / sum(weights)


def demand(difficulty: float, mastery: Optional[float]) -> float:
    return _clip(0.5 + difficulty - (0.3 if mastery is None else mastery), 0.0, 1.0)


class PersonalLoad:
    def __init__(self, store, population: Optional[Dict[str, Any]] = None):
        self.store = store
        self.pop = population or load_population()

    def estimate(self, username: str, *, difficulty: float, mastery: Optional[float], correct_history: List[bool],
                 task_type: float, interaction_count: int, timing: Optional[Dict[str, Any]],
                 update: bool = True) -> Dict[str, Any]:
        """Personal load for this turn, with the terms that produced it. ``correct_history`` is the
        graded answers so far, oldest first (before this turn's own answer is known)."""
        pop, coef, norms = self.pop, self.pop["coef"], self.pop["norms"]
        state = self.store.load(username)
        think, pace = _Running(state.get("think")), _Running(state.get("pace"))
        timing = timing or {}
        details: Dict[str, Any] = {"model": "personal", "timing_used": bool(timing), "baseline_n": think.n}

        slow = typing = 0.0
        r_think_used = r_pace_used = None
        rapid = away = False
        response, typed = timing.get("response_ms"), timing.get("typing_ms", 0.0)
        if response is not None:
            think_ms = max(response - typed, 0.0)
            r_think = (math.log(max(think_ms, 500.0)) - 0.35 * math.log(max(timing.get("prompt_chars", 200.0), 20.0))
                       - 0.4 * task_type)
            r_think_used = r_think
            mu, sd = think.shrunk(norms["think_mu"], norms["think_sd"], pop["kappa"])
            z = (r_think - mu) / sd
            away = think_ms > AWAY_MS
            rapid = think_ms < RAPID_MS and z < -1.5
            slow = 0.0 if rapid else _clip(z, -2.0, 3.0) / 3.0
            details.update({"think_ms": think_ms, "think_z": round(z, 3)})
            if update and not (rapid or away):
                think.add(r_think)
        chars = timing.get("chars", 0.0)
        if chars >= MIN_TYPING_CHARS and typed >= MIN_TYPING_MS:
            r_pace = math.log(chars / (typed / 1000.0))
            r_pace_used = r_pace
            mu, sd = pace.shrunk(norms["pace_mu"], norms["pace_sd"], pop["kappa"])
            zp = -(r_pace - mu) / sd            # slower than usual is positive
            typing = _clip(zp, -2.0, 3.0) / 3.0
            details["typing_z"] = round(zp, 3)
            if update and not away:
                pace.add(r_pace)

        help_rate = float(state.get("help", 0.0))
        help_rate = HELP_ALPHA * float(bool(timing.get("hint_requested"))) + (1 - HELP_ALPHA) * help_rate
        elapsed = timing.get("elapsed_ms")
        minutes = elapsed / 60000.0 if elapsed is not None else 0.75 * max(interaction_count, 1)
        fatigue = 1.0 - math.exp(-minutes / FATIGUE_MINUTES)
        dem, err = demand(difficulty, mastery), error_rate(correct_history)
        gain = self._gain(state)

        behaviour = coef["slow"] * slow + coef["help"] * help_rate + coef["typing"] * typing
        raw = (coef["b0"] + coef["demand"] * dem + coef["errors"] * err + gain * behaviour + coef["fatigue"] * fatigue
               + coef["demand_fatigue"] * dem * fatigue + coef["task"] * task_type)
        load = 10.0 * _clip(raw, 0.0, 1.0)
        details.update({"load": round(load, 3), "demand": round(dem, 3), "errors": round(err, 3), "slow": round(slow, 3),
                        "help": round(help_rate, 3), "typing": round(typing, 3), "fatigue": round(fatigue, 3),
                        "gain": round(gain, 3), "rapid_guess": rapid, "away": away, "behaviour": round(behaviour, 4),
                        "demand_fatigue": round(dem * fatigue, 4), "task": task_type})
        if r_think_used is not None:
            details["r_think"] = round(r_think_used, 4)
        if r_pace_used is not None:
            details["r_pace"] = round(r_pace_used, 4)

        if update:
            state.update({"think": think.dump(), "pace": pace.dump(), "help": help_rate})
            self._record_rating(state, timing.get("effort_rating"), behaviour)
            self.store.save(username, state)
        return details

    # -- personal sensitivity g, from relative effort ratings ------------------------------
    def _gain(self, state: Dict[str, Any]) -> float:
        pairs = state.get("ratings") or []
        if len(pairs) < 3:
            return 1.0
        num = sum(r * d for r, d in pairs)
        den = sum(d * d for _, d in pairs)
        if den < 1e-9:
            return 1.0
        slope = num / den                                  # rating units per behaviour unit
        ratio = slope / max(self.pop["rating_scale"], 1e-6)  # 1.0 = the population's sensitivity
        w = len(pairs) / (len(pairs) + self.pop["rating_kappa"])
        return _clip(w * ratio + (1 - w) * 1.0, 0.5, 2.0)

    @staticmethod
    def _record_rating(state: Dict[str, Any], rating: Optional[int], behaviour: float) -> None:
        """Track the behavioural load of the objective in progress; a rating closes an objective and
        pairs itself with the change in behavioural load since the previous objective."""
        cur = state.setdefault("objective", {"sum": 0.0, "n": 0})
        cur["sum"] += behaviour
        cur["n"] += 1
        if rating is None or cur["n"] == 0:
            return
        mean_now = cur["sum"] / cur["n"]
        previous = state.get("previous_behaviour")
        if previous is not None:
            state.setdefault("ratings", []).append([float(rating), mean_now - previous])
            state["ratings"] = state["ratings"][-40:]
        state["previous_behaviour"] = mean_now
        state["objective"] = {"sum": 0.0, "n": 0}
