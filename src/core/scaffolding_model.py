"""How ZPD and support level are decided: the current rules, or one of two alternatives.

Selected per process by ``LEA_SCAFFOLDING_MODEL``:

``current`` (default)
    Nothing changes: ZPD is the accuracy over the last four graded responses and the CL x ZPD
    matrix sets the support level.

``zpd_shrunk``
    ZPD becomes a shrunk estimate of the learner's success: recent graded responses (up to eight,
    newer ones counting more) pulled toward the learner's mastery of the current objective, so a few noisy
    grades can't swing it. The matrix and fading are unchanged.

``load_led``
    The same shrunk ZPD, plus:

    * support level comes mainly from cognitive load (high load: high support, medium: medium, low: low),
      raised one level when ZPD is low and load is not low, so a struggling learner is still helped;
    * ZPD steers difficulty (aim for success of about 0.6 to 0.85) instead of support: ``increase`` when
      ZPD is at least 0.85, ``decrease`` when it is 0.45 or below;
    * fading counts a run of correct graded answers of 3, ignoring replies the grader marked as not
      checkable, and a support level must be held for two turns before it changes (no flip-flopping);
    * the grader's checkable/confidence fields (below) additionally weight evidence for ZPD and fading: an
      unchecked reply counts for nothing there, others in proportion to the grader's confidence.

**The grader itself (``src/core/grading.py``, all scaffolding models, not just ``load_led``):** since 2026-09-27
the tutor's and quiz's free-text grader ("V3" in the offline replay against pilot-1 through pilot-4's saved
answers, ``simulation/grader_replay.py``) also judges only the specific question actually asked, and asks whether
the tutor's message was checkable at all; a reply to something with no checkable question (e.g. "are you ready to
continue?") is left ungraded rather than marked right or wrong. The replay found this raised kappa against the
simulator's intent on fill-in and open-ended quiz answers (0.58 to 0.63 and 0.22 to 0.32) without raising tutor
false positives, at the cost of leaving about 4% of tutor turns ungraded. Pass ``with_confidence=False`` to
``grade_with_llm`` for the previous, ungated behaviour. This is independent of ``LEA_SCAFFOLDING_MODEL``; it
changes what counts as "graded" for every model, which is why it affects mastery and advancement, not only ZPD.

Two further switches concern the motivation state (they are independent of the model above):

``LEA_MOTIVATION_SUPPORT`` (**off by default since 2026-09-27**): with ``on``, the motivation state moves the load
level that picks the support level (drop: one level up, maintained high: one level down). The state is still
classified, logged and used for feedback tone and messages either way. Rationale (research, Amendment A3 in
``simulation/PREREGISTRATION.md``): in simulation about 89-91% of tutor turns were classified ``motivation_drop``
(driven mainly by the classifier's `performance_score < 0.5` rule against a noisy grader), and that shift accounted
for most "very high" support decisions, swamping every earlier comparison of the ZPD and scaffolding rules
themselves. Turning it off cut support mismatch against the simulator's hidden true load by 15 to 17 percentage
points, significant (Holm-corrected paired Wilcoxon, p <= 0.01) against every alternative tested.

``LEA_MOTIVATION_CLASSIFIER`` (``current`` by default): with ``no_performance``, recent accuracy is not used to
call a drop (accuracy below 0.5) or high motivation (accuracy above 0.8). Accuracy is already what ZPD measures,
and counting it as motivation as well double-counts a noisy signal: with the tutor's grader marking about half of
right answers wrong, accuracy is below 0.5 for most students most of the time.

Nothing here has been validated on real students.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

MODEL_ENV = "LEA_SCAFFOLDING_MODEL"
MODELS = ("current", "zpd_shrunk", "load_led")

ZPD_WINDOW = 8
ZPD_DECAY = 0.85          # each older response counts this much of the one after it
ZPD_PRIOR_WEIGHT = 3.0    # worth this many responses
ZPD_DEFAULT_PRIOR = 0.65
CHALLENGE_UP, CHALLENGE_DOWN = 0.85, 0.45
LOAD_LED_FADE_AFTER = 3
MIN_DWELL_TURNS = 2
MIN_CONFIDENCE_WEIGHT = 0.2


def selected_model() -> str:
    value = os.getenv(MODEL_ENV, "current").strip().lower()
    return value if value in MODELS else "current"


def motivation_shifts_support() -> bool:
    return os.getenv("LEA_MOTIVATION_SUPPORT", "off").strip().lower() == "on"


def motivation_uses_performance() -> bool:
    return os.getenv("LEA_MOTIVATION_CLASSIFIER", "current").strip().lower() != "no_performance"


def tutor_records_one_question() -> bool:
    """On by default since 2026-09-27 (research, not yet measured live): the tutor is instructed to end its
    message with exactly one checkable question about the current GO, state only facts the course content
    supports, and keep replies to about 200 words. When the student's reply arrives, a cheap extraction
    call (at grading time, not generation time -- no added latency on the tutor's turn, and no call at all
    if the student never replies) records the one required question from the tutor's last message and
    confirms it is about the current GO. Grading then uses that recorded question, scoped to that GO,
    instead of the raw last tutor message; a turn with no valid recorded question (extraction failed, or
    the tutor's question wasn't about this GO) is never graded. See
    src/tutor/simple_tutor_system.py's _extract_recorded_question and _evaluate_response_enhanced.

    Pass ``LEA_TUTOR_RECORDED_QUESTION=off`` to go back to the original, unrecorded tutor question."""
    return os.getenv("LEA_TUTOR_RECORDED_QUESTION", "on").strip().lower() != "off"


def tutor_question_scope() -> str:
    """``strict``: only a question genuinely about the current GO counts as "about this objective".
    ``broad`` (the default; research, 2026-09-27, unit-tested only, not yet run live): a question that connects or compares the current GO with another concept also counts,
    so long as answering it would still mainly show understanding of the current GO. Only takes effect when
    ``tutor_records_one_question()`` is also on. Two related, not-yet-built ideas: crediting a question
    that's clearly about a *different* same-week GO to that GO instead of leaving it ungraded
    ("credit_other_go"), and a separate check that the tutor's own message doesn't contradict the lesson
    (both open items -- see docs/STATUS.md).

    Pass ``LEA_TUTOR_QUESTION_SCOPE=strict`` for the narrower, unit-tested-only original behaviour."""
    value = os.getenv("LEA_TUTOR_QUESTION_SCOPE", "broad").strip().lower()
    return value if value in ("strict", "broad") else "broad"


def tutor_temperature() -> float:
    """The tutor reply generation call's temperature (2026-09-27's default of 0.7, unchanged, unless
    LEA_TUTOR_TEMPERATURE overrides it -- e.g. to test whether a lower temperature reduces how often the
    tutor states something that contradicts the lesson passage)."""
    try:
        return float(os.getenv("LEA_TUTOR_TEMPERATURE", "0.7"))
    except ValueError:
        return 0.7


def evidence_weight(checkable: Optional[bool], confidence: Optional[float]) -> Optional[float]:
    """The weight the grader's verdict earns as evidence. None when it gave no opinion (weight 1 is assumed)."""
    if checkable is None and confidence is None:
        return None
    if checkable is False:
        return 0.0
    c = 1.0 if confidence is None else max(0.0, min(1.0, float(confidence)))
    return max(MIN_CONFIDENCE_WEIGHT, c)


def shrunk_zpd(entries: List[Dict[str, Any]], prior: Optional[float], use_weights: bool) -> Tuple[float, Dict[str, Any]]:
    """(zpd, details). ``entries`` are graded evidence, oldest first."""
    prior = ZPD_DEFAULT_PRIOR if prior is None else max(0.0, min(1.0, float(prior)))
    last = entries[-ZPD_WINDOW:]
    weight_sum = correct_sum = 0.0
    for age, e in enumerate(reversed(last)):
        w = ZPD_DECAY ** age
        if use_weights and e.get("weight") is not None:
            w *= float(e["weight"])
        weight_sum += w
        correct_sum += w * (1.0 if e.get("correct") else 0.0)
    zpd = (correct_sum + ZPD_PRIOR_WEIGHT * prior) / (weight_sum + ZPD_PRIOR_WEIGHT)
    return zpd, {"model": "shrunk", "prior": round(prior, 3), "effective_n": round(weight_sum, 2), "used": len(last)}


def counted_correctness(entries: List[Dict[str, Any]]) -> List[bool]:
    """Correctness of the entries that count as evidence (weight above zero), oldest first."""
    return [bool(e.get("correct")) for e in entries if e.get("weight") is None or float(e["weight"]) > 0]


def support_from_load(cl_level: str, zpd_level: str) -> str:
    """Base support level: from load, raised one level when ZPD is low and load isn't."""
    base = {"high": "high", "medium": "medium", "low": "low"}[cl_level]
    if zpd_level == "low" and cl_level != "low":
        return {"medium": "high", "high": "very_high"}[cl_level]
    return base


def difficulty_from_zpd(zpd: float) -> str:
    if zpd >= CHALLENGE_UP:
        return "increase"
    if zpd <= CHALLENGE_DOWN:
        return "decrease"
    return "maintain"
