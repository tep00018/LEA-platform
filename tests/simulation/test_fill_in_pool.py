"""Programmatic fill-in wrong answers (simulation/drivers.py's LearnerRunner._quiz_answer): a genuine
course term that is simply wrong for the current blank, not an LLM invention, once enough distinct terms
have been seen."""


from simulation.drivers import LearnerRunner
from simulation.learner import Intent


class FakeStyleRng:
    """Deterministic 'random' choice: always the first option, for a predictable assertion."""

    def choice(self, options):
        return options[0]


class Stub:
    """Just enough of LearnerRunner to call _quiz_answer unbound."""

    def __init__(self):
        self._fill_in_pool = []
        self.learner = type("L", (), {"rng_style": FakeStyleRng()})()
        self.student = None  # the LLM path must never be reached once the pool has a distractor

    def _misconception(self, entry):
        return "a wrong belief"


def intent(correct):
    return Intent(kind="answer", go_id="g1", qtype="fill_in", correct=correct, p_correct=0.5, known=True,
                 engagement="engaged", target_words=None)


def question(term):
    return {"type": "fill_in", "text": f"The ___ is {term}", "correct_answer": term}


def test_a_wrong_fill_in_answer_is_a_real_term_from_a_different_question_not_llm_text():
    stub = Stub()
    stub._fill_in_pool = ["gradient descent"]  # a term seen on an earlier question this learner answered
    answer, misconception = LearnerRunner._quiz_answer(stub, question("backpropagation"), "fill_in", intent(False), None)
    assert answer == "gradient descent" and misconception is None  # no LLM misconception needed: no LLM call made


def test_the_chosen_wrong_term_is_never_the_current_blank_s_own_answer(monkeypatch):
    stub = Stub()
    stub._fill_in_pool = ["neuron"]  # the only term seen so far happens to be this question's own answer
    stub.student = type("S", (), {"quiz_answer": lambda *a, **k: "fallback wrong term"})()
    answer, _ = LearnerRunner._quiz_answer(stub, question("neuron"), "fill_in", intent(False), {})
    assert answer == "fallback wrong term"  # nothing else in the pool to offer, so it falls through to the LLM


def test_first_ever_fill_in_wrong_answer_falls_back_to_the_llm_path(monkeypatch):
    stub = Stub()
    stub.student = type("S", (), {"quiz_answer": lambda self, learner, intent, q, entry, misconception: "wrong term"})()
    answer, misconception = LearnerRunner._quiz_answer(stub, question("neuron"), "fill_in", intent(False), {})
    assert answer == "wrong term" and misconception == "a wrong belief"  # the LLM path, used because the pool was empty


def test_correct_fill_in_answers_still_go_through_the_llm_for_paraphrasing():
    stub = Stub()
    stub.student = type("S", (), {"quiz_answer": lambda self, learner, intent, q, entry, misconception: "neurons"})()
    answer, misconception = LearnerRunner._quiz_answer(stub, question("neuron"), "fill_in", intent(True), {})
    assert answer == "neurons" and misconception is None
    assert stub._fill_in_pool == ["neuron"]  # the real term is still recorded into the pool


def test_the_pool_deduplicates_case_insensitively():
    stub = Stub()
    stub.student = type("S", (), {"quiz_answer": lambda *a, **k: "x"})()
    LearnerRunner._quiz_answer(stub, question("Neuron"), "fill_in", intent(True), {})
    LearnerRunner._quiz_answer(stub, question("neuron"), "fill_in", intent(True), {})
    assert stub._fill_in_pool == ["Neuron"]
