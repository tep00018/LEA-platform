"""What a simulated student's hidden cognitive load does to how they answer (and what a client would log).

Cognitive load is not observable, so the simulator holds one: a hidden personal load that follows
its own equation (different coefficients for each learner, a fatigue interaction, a time-on-task
fatigue that differs by learner) and produces the signals a Flutter client could record without
hardware: time to answer (question shown to submit), typing time and characters, hint requests,
rapid guesses when disengaged, and an optional relative effort rating after each objective.

This is the study's assumption about students, not a finding. Load here does not change whether
an answer is right (the BKT model does that, unchanged), so a scaffolding decision can be scored
against the hidden load, but cannot be shown to improve learning.

Per-learner parameters come from a separate seeded stream, so they are the same however the
conversation goes; the stream's state is checkpointed with the learner.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

import numpy as np

DEFAULTS: Dict[str, Any] = {
    "c0": [0.15, 0.05], "c1": [0.50, 0.15], "c2": [0.10, 0.06], "c3": [0.20, 0.10], "c4": [0.30, 0.15],
    "tau_minutes": 25.0, "tau_sd": 0.4,
    "think_log_ms": [math.log(8000), 0.5],     # a student's usual thinking time (log ms), for a 200-character prompt
    "think_load_slope": [1.0, 0.3], "think_noise_sd": 0.35,
    "pace_log_chars_per_s": [1.1, 0.35], "pace_load_slope": 0.25,
    "hint_logit_intercept": [-3.0, 0.5], "hint_load_slope": 4.0,
    "rapid_guess_when_disengaging": 0.35,
    "rating_gain": [1.0, 0.3], "rating_noise_sd": 0.5,
    "reading_ms_between_turns": 8000,
    "noise_ar": 0.6, "noise_sd": 0.05,
}


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


class HumanSignals:
    def __init__(self, seed: int, cfg: Optional[Dict[str, Any]] = None):
        self.cfg = {**DEFAULTS, **(cfg or {})}
        self.rng = np.random.default_rng(np.random.SeedSequence([int(seed) % (2 ** 63), 7919]))
        c, g = self.cfg, self._draw
        self.p = {"c0": g(c["c0"]), "c1": max(0.1, g(c["c1"])), "c2": g(c["c2"]), "c3": max(0.0, g(c["c3"])),
                  "c4": max(0.0, g(c["c4"])), "tau": float(c["tau_minutes"] * math.exp(self.rng.normal(0, c["tau_sd"]))),
                  "think0": g(c["think_log_ms"]), "slope": max(0.2, g(c["think_load_slope"])),
                  "pace0": g(c["pace_log_chars_per_s"]), "hint0": g(c["hint_logit_intercept"]),
                  "gain": max(0.3, g(c["rating_gain"]))}
        self.noise = 0.0
        self.elapsed_ms = 0.0
        self.current_go: Optional[str] = None
        self.objective_loads: List[float] = []
        self.previous_mean: Optional[float] = None
        self.pending_rating: Optional[int] = None

    def _draw(self, pair) -> float:
        return float(self.rng.normal(pair[0], pair[1]))

    # -- checkpoint
    def state(self) -> Dict[str, Any]:
        return {"noise": self.noise, "elapsed_ms": self.elapsed_ms, "current_go": self.current_go,
                "objective_loads": self.objective_loads, "previous_mean": self.previous_mean,
                "pending_rating": self.pending_rating, "rng": self.rng.bit_generator.state}

    def load_state(self, s: Dict[str, Any]) -> None:
        self.noise, self.elapsed_ms, self.current_go = float(s["noise"]), float(s["elapsed_ms"]), s["current_go"]
        self.objective_loads, self.previous_mean = list(s["objective_loads"]), s["previous_mean"]
        self.pending_rating = s["pending_rating"]
        self.rng.bit_generator.state = s["rng"]

    def start_session(self) -> None:
        self.elapsed_ms = 0.0

    # -- the hidden load
    def true_load(self, demand: float, task: float) -> float:
        """0 to 10. ``demand``: 0 (easy for this learner now) to 1 (hard); ``task``: 1 open-ended, else 0."""
        fatigue = 1.0 - math.exp(-(self.elapsed_ms / 60000.0) / self.p["tau"])
        self.noise = self.cfg["noise_ar"] * self.noise + float(self.rng.normal(0, self.cfg["noise_sd"]))
        raw = (self.p["c0"] + self.p["c1"] * demand + self.p["c2"] * task + self.p["c3"] * fatigue
               + self.p["c4"] * demand * fatigue + self.noise)
        return 10.0 * min(1.0, max(0.0, raw))

    def _close_objective(self) -> None:
        if not self.objective_loads:
            return
        mean = float(np.mean(self.objective_loads))
        if self.previous_mean is not None:
            delta = (mean - self.previous_mean) / 10.0
            rating = self.p["gain"] * delta * 8.0 + float(self.rng.normal(0, self.cfg["rating_noise_sd"]))
            self.pending_rating = int(round(min(2.0, max(-2.0, rating))))
        self.previous_mean = mean
        self.objective_loads = []

    def observe(self, go_id: str, *, demand: float, task: float, prompt_chars: int, chars: int, kind: str,
                engagement: str, answer_attempt: bool) -> Dict[str, Any]:
        """The hidden load for this turn and the timing block a client would send with the answer."""
        if self.current_go is not None and go_id != self.current_go:
            self._close_objective()
        self.current_go = go_id
        load = self.true_load(demand, task)
        self.objective_loads.append(load)
        l01, c = load / 10.0, self.cfg
        think_ln = (self.p["think0"] + 0.35 * (math.log(max(prompt_chars, 20)) - math.log(200)) + 0.4 * task
                    + self.p["slope"] * l01 + float(self.rng.normal(0, c["think_noise_sd"])))
        think_ms = math.exp(think_ln)
        rapid = engagement == "disengaging" and answer_attempt and self.rng.random() < c["rapid_guess_when_disengaging"]
        if rapid:
            think_ms = float(self.rng.uniform(600, 2200))
        elif kind == "minimal":
            think_ms *= 0.4
        think_ms = min(max(think_ms, 400.0), 20 * 60 * 1000.0)
        pace = math.exp(self.p["pace0"] - c["pace_load_slope"] * l01 + float(self.rng.normal(0, 0.15)))
        typing_ms = 0.0 if chars < 3 else chars / pace * 1000.0
        response_ms = think_ms + typing_ms
        hint = bool(answer_attempt and self.rng.random() < sigmoid(self.p["hint0"] + c["hint_load_slope"] * l01))
        self.elapsed_ms += response_ms + c["reading_ms_between_turns"]
        timing: Dict[str, Any] = {"response_ms": round(response_ms), "typing_ms": round(typing_ms), "chars": chars,
                                  "prompt_chars": prompt_chars, "elapsed_ms": round(self.elapsed_ms),
                                  "hint_requested": hint}
        if self.pending_rating is not None:
            timing["effort_rating"] = self.pending_rating
            self.pending_rating = None
        return {"true_load": round(load, 3), "timing": timing, "rapid_guess": bool(rapid)}
