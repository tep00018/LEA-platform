"""Prompt variants for trying LEA differently, applied inside the simulator process only.

Nothing in ``src/`` changes and a variant never outlives its ``with`` block: the method it
wraps is put back on exit. Variants are for looking at what a change would do (with
``compare-models``); they are not LEA's behaviour and never reach a study run's metrics.

``quiz_questions_without_coaching``: LEA's question-generation prompt carries a
"motivation-informed adaptations" block whose lines ask for an encouraging, welcoming or
celebratory *tone*. The model writes the question and its feedback ("explanation") in one
call and puts that tone into the question itself (Sonnet does so eagerly: "No worries if
this feels tricky, let's take it step by step!"). The default variant keeps the tone
guidance but scopes it (``SCOPE_RULE``): supportive language goes only in the
``explanation``, the feedback shown after the student answers; the question text and
options stay neutral. Difficulty, structure, hints and scaffolding adaptations are left as
they are.

A first version deleted the tone lines (``strip_lines=True``; ``AFFECT_LINES`` are checked
against the live prompt by a test). That removed the coaching from the question but also
from the feedback, which is not what was wanted, so the scoped rule is the default.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator, List

# Lines of the motivation block in SimpleQuizSystem._create_orchestrator_guided_prompt that
# ask for a tone or emotional register (compared after stripping "- " and whitespace).
AFFECT_LINES: List[str] = [
    "Use encouraging, non-controlling language",
    "Add emotional support elements",
    "Focus on effort and process rather than just correctness",
    "Use challenging, engaging language",
    "Use especially welcoming, encouraging tone",
    "Provide positive reinforcement without performance pressure",
    "Include clear, friendly explanations",
    "Set up supportive learning environment",
    "Use collaborative language",
    "Celebrate effort and strategic thinking",
    "Provide mastery-oriented feedback",
    "Emphasize growth mindset principles",
]

# Added at the end of the prompt by default: the tone guidance stays, but only for feedback.
SCOPE_RULE = """

        **WHERE TONE GOES (overrides anything above about where to put it):** All the tone and
        emotional-support guidance above applies ONLY to the "explanation" field, the feedback the
        student sees AFTER answering: put any encouragement, reassurance, praise or supportive language
        there. The "question" text and the answer "options" must be neutral and self-contained: no
        encouragement, reassurance, praise, greetings or comments on the student's progress, effort or
        feelings (no "no worries", "nice work", "let's take it step by step"). Difficulty, structure,
        hints and scaffolding still adapt as described above.
"""

# Used with strip_lines=True (the first version): tone lines deleted, everything neutral.
NEUTRAL_RULE = """

        **QUESTION TEXT RULE (overrides anything above about tone):** The question text and the answer
        options must be neutral and self-contained. Do NOT put encouragement, reassurance, praise,
        greetings or any comment on the student's progress, effort or feelings anywhere in the question
        or its options (no "no worries", "nice work", "let's take it step by step"). Apply the
        adaptations above to content, difficulty, structure and hints only. Supportive language is given
        separately, in the feedback shown after the student answers.
"""


def strip_affect(prompt: str) -> str:
    """The prompt without the tone lines."""
    wanted = {x.lower() for x in AFFECT_LINES}
    kept = [line for line in prompt.split("\n") if line.strip().lstrip("-").strip().lower() not in wanted]
    return "\n".join(kept)


def describe(strip_lines: bool = False) -> str:
    """The change, in words, for the report."""
    head = "**Prompt change (test only; LEA's real prompt is unchanged).** "
    if strip_lines:
        lines = "\n".join(f"- {x}" for x in AFFECT_LINES)
        return (head + "In the quiz question-generation prompt, these tone lines were removed:\n\n" + lines +
                "\n\nand this rule was added at the end:\n\n> " + " ".join(NEUTRAL_RULE.split()))
    return (head + "The quiz question-generation prompt is unchanged except that this rule is added at the "
            "end, so the tone guidance applies to the feedback only:\n\n> " + " ".join(SCOPE_RULE.split()))


@contextmanager
def quiz_questions_without_coaching(strip_lines: bool = False) -> Iterator[None]:
    from src.quiz.simple_quiz_system import SimpleQuizSystem

    original = SimpleQuizSystem._create_orchestrator_guided_prompt

    def patched(self, *args, **kwargs):
        prompt = original(self, *args, **kwargs)
        return strip_affect(prompt) + NEUTRAL_RULE if strip_lines else prompt + SCOPE_RULE

    SimpleQuizSystem._create_orchestrator_guided_prompt = patched
    try:
        yield
    finally:
        SimpleQuizSystem._create_orchestrator_guided_prompt = original
