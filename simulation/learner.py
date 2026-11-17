"""Simulated learners: hidden ground truth (docs/simulation/PLAN.md, section 1).

Bayesian Knowledge Tracing per granular objective (GO), no forgetting:

- A GO starts known with probability ``sigmoid(theta - b_g)``.
- After a counted tutor exchange on the GO (an answer attempt or a question; minimal
  replies and quitting don't count) an unknown GO becomes known with probability
  ``p_learn``; after quiz feedback, ``p_learn * quiz_learning_factor``.
- Answering: if known, correct with ``sigmoid(logit(1 - slip - d_type) + eps)``, where
  ``eps ~ N(0, sigma)`` is drawn per session; if unknown, correct by chance
  (``guess[type]``).

Two ground truths are kept per GO: ``known`` (the realised hidden state, used for
precision and recall of LEA's mastery decisions) and ``p_know`` (the probability of
knowing given the learner's parameters and the learning opportunities so far, not
conditioned on answers; used for correlations with LEA's mastery).

Each turn's intent comes from one categorical draw (quit, question, minimal reply, or an
answer attempt), with rates set by the profile and tilted by a hidden engagement state
(engaged, steady, disengaging) that follows a per-profile Markov chain. The rates are
rescaled so that, averaged over the profile's stationary engagement mix, they equal the
configured values.

Randomness uses separate seeded streams (knowledge, answers, engagement, options, text
style), so the same learner behaves the same way however the conversation goes.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np

from simulation.signals import HumanSignals

QUESTION_TYPES = ("multiple_choice", "true_false", "fill_in", "open_ended", "tutor_reply")
ENGAGEMENT = ("engaged", "steady", "disengaging")
RATES = ("ask", "minimal", "quit")
INTENTS = ("answer", "question", "minimal", "quit")


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def logit(p: float) -> float:
    p = min(max(p, 1e-9), 1 - 1e-9)
    return math.log(p / (1 - p))


def learner_seed(run_seed: int, profile: str, index: int) -> int:
    """A stable seed per learner from the run seed, profile and index."""
    digest = hashlib.sha256(f"{run_seed}:{profile}:{index}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


# ---------------------------------------------------------------------------- GO difficulty

def go_difficulties(gos: List[Dict[str, Any]], learner_cfg: Dict[str, Any], seed: int) -> Dict[str, float]:
    """``b_g`` from the Bloom level (unknown levels: 0) plus seeded jitter; recorded in the
    manifest. Deterministic for a seed, whatever the order of the GOs."""
    mapping = {k.lower(): float(v) for k, v in learner_cfg["bloom_difficulty"].items()}
    sd = float(learner_cfg["difficulty_jitter_sd"])
    out = {}
    for go in gos:
        base = mapping.get(str(go.get("cognitive_level") or "").strip().lower(), 0.0)
        rng = np.random.default_rng(learner_seed(seed, f"difficulty:{go['go_id']}", 0))
        out[go["go_id"]] = round(base + float(rng.normal(0.0, sd)), 4)
    return out


# ---------------------------------------------------------------------------- profiles

@dataclass(frozen=True)
class Profile:
    key: str
    name: str
    theta: float
    p_learn: float
    slip: float
    sigma: float
    ask: float
    minimal: float
    quit: float
    reply_length: str
    engagement: Dict[str, float]
    # derived: per engagement state, the per-turn probabilities of ask / minimal / quit
    state_rates: Dict[str, Dict[str, float]] = field(default_factory=dict)


def build_profiles(config: Dict[str, Any]) -> Dict[str, Profile]:
    learner = config["learner"]
    mult = learner["engagement_multipliers"]
    out = {}
    for key, p in config["profiles"].items():
        mix = {s: float(p["engagement"][s]) for s in ENGAGEMENT}
        if abs(sum(mix.values()) - 1) > 1e-6:
            raise ValueError(f"{key}: engagement shares must add up to 1")
        rates: Dict[str, Dict[str, float]] = {s: {} for s in ENGAGEMENT}
        for r in RATES:
            scale = sum(mix[s] * float(mult[s][r]) for s in ENGAGEMENT)
            for s in ENGAGEMENT:
                rates[s][r] = float(p[r]) * float(mult[s][r]) / scale if scale else 0.0
        for s in ENGAGEMENT:
            if sum(rates[s].values()) > 0.95:
                raise ValueError(f"{key}: ask + minimal + quit exceed 0.95 when {s}")
        if p["reply_length"] not in (*learner["reply_words"], "varies"):
            raise ValueError(f"{key}: unknown reply_length {p['reply_length']}")
        out[key] = Profile(key=key, name=p["name"], theta=float(p["theta"]), p_learn=float(p["p_learn"]),
                           slip=float(p["slip"]), sigma=float(p["sigma"]), ask=float(p["ask"]),
                           minimal=float(p["minimal"]), quit=float(p["quit"]), reply_length=p["reply_length"],
                           engagement=mix, state_rates=rates)
    return out


# ---------------------------------------------------------------------------- the learner

@dataclass
class Intent:
    kind: str                       # answer / question / minimal / quit / acknowledge (the tutor asked nothing answerable)
    go_id: Optional[str]
    qtype: Optional[str]
    correct: Optional[bool]         # for answers: meant to be correct
    p_correct: Optional[float]      # the learner's true success probability for this item
    known: Optional[bool]
    engagement: str
    target_words: Optional[int]


class Learner:
    def __init__(self, username: str, profile: Profile, difficulties: Dict[str, float],
                 learner_cfg: Dict[str, Any], seed: int):
        self.username = username
        self.profile = profile
        self.cfg = learner_cfg
        self.difficulty = dict(difficulties)
        streams = np.random.SeedSequence(seed).spawn(5)
        self.rng_knowledge, self.rng_answer, self.rng_engagement, self.rng_option, self.rng_style = (
            np.random.default_rng(s) for s in streams)
        self.signals = HumanSignals(seed, learner_cfg.get("signals"))  # hidden load and the timing it produces
        self.p0 = {g: sigmoid(profile.theta - b) for g, b in self.difficulty.items()}
        # Draw every GO's starting state up front, in a fixed order, so it doesn't depend
        # on the order LEA happens to visit objectives.
        self.known = {g: bool(self.rng_knowledge.random() < self.p0[g]) for g in sorted(self.difficulty)}
        self.opportunities = {g: {"tutor": 0, "quiz": 0} for g in self.difficulty}
        self.eps = 0.0
        self.engagement_state = "steady"
        self.sessions = 0

    # -- ground truth
    def p_know(self, go_id: str) -> float:
        """Probability of knowing, given parameters and learning opportunities (not answers)."""
        o = self.opportunities[go_id]
        pl = self.profile.p_learn
        stay_unknown = (1 - self.p0[go_id]) * (1 - pl) ** o["tutor"] * (1 - pl * self.quiz_factor) ** o["quiz"]
        return 1 - stay_unknown

    @property
    def quiz_factor(self) -> float:
        return float(self.cfg["quiz_learning_factor"])

    def p_correct_if_known(self, qtype: str) -> float:
        base = 1 - self.profile.slip - float(self.cfg["d_type"][qtype])
        return sigmoid(logit(base) + self.eps)

    def success_probability(self, go_id: str, qtype: str) -> float:
        """The true chance of a correct answer now, from the realised state."""
        return self.p_correct_if_known(qtype) if self.known[go_id] else float(self.cfg["guess"][qtype])

    def expected_success(self, go_id: str, qtype: str) -> float:
        """The same, averaged over ``p_know`` (the model-level success probability)."""
        pk = self.p_know(go_id)
        return pk * self.p_correct_if_known(qtype) + (1 - pk) * float(self.cfg["guess"][qtype])

    def snapshot(self) -> Dict[str, Any]:
        return {"known": dict(self.known), "p_know": {g: round(self.p_know(g), 4) for g in self.known},
                "engagement": self.engagement_state, "eps": round(self.eps, 4)}

    # -- checkpoints
    STREAMS = ("rng_knowledge", "rng_answer", "rng_engagement", "rng_option", "rng_style")

    def state(self) -> Dict[str, Any]:
        """Everything needed to continue this learner exactly (JSON-serialisable)."""
        return {"known": self.known, "opportunities": self.opportunities, "eps": self.eps,
                "engagement_state": self.engagement_state, "sessions": self.sessions,
                "rngs": {name: getattr(self, name).bit_generator.state for name in self.STREAMS},
                "signals": self.signals.state()}

    def load_state(self, state: Dict[str, Any]) -> None:
        self.known = {g: bool(v) for g, v in state["known"].items()}
        self.opportunities = {g: dict(v) for g, v in state["opportunities"].items()}
        self.eps = float(state["eps"])
        self.engagement_state = state["engagement_state"]
        self.sessions = int(state["sessions"])
        for name in self.STREAMS:
            getattr(self, name).bit_generator.state = state["rngs"][name]
        if state.get("signals"):
            self.signals.load_state(state["signals"])

    # -- sessions and turns
    def start_session(self) -> None:
        self.sessions += 1
        self.signals.start_session()
        self.eps = float(self.rng_answer.normal(0.0, self.profile.sigma)) if self.profile.sigma > 0 else 0.0
        self.engagement_state = self._draw_state()

    def _draw_state(self) -> str:
        mix = self.profile.engagement
        return str(self.rng_engagement.choice(ENGAGEMENT, p=[mix[s] for s in ENGAGEMENT]))

    def _step_engagement(self) -> None:
        if self.rng_engagement.random() >= float(self.cfg["engagement_persistence"]):
            self.engagement_state = self._draw_state()

    def target_words(self) -> int:
        words = self.cfg["reply_words"]
        length = self.profile.reply_length
        if length == "varies":
            length = str(self.rng_style.choice(sorted(words)))
        return int(words[length])

    def turn(self, go_id: str, qtype: str = "tutor_reply", *, may_digress: bool = True) -> Intent:
        """What the learner does next. ``may_digress`` False (quiz items) means always attempt."""
        self._step_engagement()
        state = self.engagement_state
        kind = "answer"
        if may_digress:
            r = self.profile.state_rates[state]
            u = self.rng_engagement.random()
            if u < r["quit"]:
                kind = "quit"
            elif u < r["quit"] + r["ask"]:
                kind = "question"
            elif u < r["quit"] + r["ask"] + r["minimal"]:
                kind = "minimal"
        if kind != "answer":
            return Intent(kind, go_id, qtype, None, None, None, state,
                          self.target_words() if kind == "question" else None)
        p = self.success_probability(go_id, qtype)
        correct = bool(self.rng_answer.random() < p)
        return Intent("answer", go_id, qtype, correct, round(p, 4), self.known[go_id], state,
                      self.target_words() if qtype not in ("multiple_choice", "true_false") else None)

    def pick_option(self, options: List[str], correct_index: int, correct: bool) -> int:
        """Multiple choice / true-false: the right option, or a random wrong one."""
        if correct or len(options) < 2:
            return correct_index
        wrong = [i for i in range(len(options)) if i != correct_index]
        return int(self.rng_option.choice(wrong))

    # -- learning
    def after_tutor_exchange(self, go_id: str, intent: Intent) -> None:
        if intent.kind not in ("answer", "question", "acknowledge"):
            return
        self.opportunities[go_id]["tutor"] += 1
        self._maybe_learn(go_id, self.profile.p_learn)

    def after_quiz_feedback(self, go_id: str) -> None:
        self.opportunities[go_id]["quiz"] += 1
        self._maybe_learn(go_id, self.profile.p_learn * self.quiz_factor)

    def _maybe_learn(self, go_id: str, p: float) -> None:
        draw = self.rng_knowledge.random()  # always drawn, so streams don't depend on state
        if not self.known[go_id] and draw < p:
            self.known[go_id] = True


def make_learner(config: Dict[str, Any], profile_key: str, index: int, difficulties: Dict[str, float]) -> Learner:
    profiles = build_profiles(config)
    return Learner(f"sim_{profile_key}_{index}", profiles[profile_key], difficulties, config["learner"],
                   learner_seed(int(config["seed"]), profile_key, index))
