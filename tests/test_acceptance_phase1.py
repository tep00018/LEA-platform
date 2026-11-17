"""Phase 1 acceptance: a scripted DEMO101 session through the real quiz system and orchestrator.

1. As answers get worse and then better, ZPD, mastery and scaffolding follow.
2. A course whose profile disallows code never produces a code question, across a
   whole week's quiz.
"""

import json

import pytest

from src.core.agent_orchestrator_mcp import InteractionType
from src.core.course_registry import CourseProfile
from src.quiz.simple_quiz_system import SimpleQuizSystem
from tests.fakes import StubRAGTool

COURSE = "DEMO101"
INTENSITY = ["minimal", "low", "medium", "high", "very_high"]


def question_writer(messages):
    """Writes a valid question of whatever type the prompt asks for, and grades free text:
    answers containing RIGHT are correct."""
    system = messages[0]["content"]
    if "ONE required checkable question" in system:
        # the recorded-question extraction call (LEA_TUTOR_RECORDED_QUESTION): always report a question
        # that's about the current objective, in whichever contract (strict or broad scope) was asked for.
        return json.dumps({"question": "What is AI?", "about_this_objective": True, "category": "current"})
    prompt = messages[-1]["content"]
    if "<answer>" in prompt:
        right = "RIGHT" in prompt
        return json.dumps({"correct": right, "score": 0.9 if right else 0.1, "explanation": "e"})
    if "TRUE/FALSE" in prompt:
        return json.dumps({"question": "Statement?", "correct_answer": "True", "explanation": "e"})
    if "FILL IN THE BLANK" in prompt:
        return json.dumps({"question": "The ___ term", "correct_answer": "model", "explanation": "e"})
    if "OPEN-ENDED" in prompt:
        return json.dumps({"question": "Explain.", "sample_answer": "Because.", "key_points": ["a"], "explanation": "e"})
    return json.dumps({"question": "Pick one", "options": ["A) a", "B) b", "C) c", "D) d"],
                       "correct_answer": "A", "explanation": "e"})


@pytest.fixture
def quiz(fake_llm, monkeypatch, redis_url):
    fake_llm._responder = question_writer
    return SimpleQuizSystem("sk-test", rag_tool=StubRAGTool())


def given_answer(question, right):
    exact = {"multiple_choice": ("A) a", "D) d"), "true_false": ("True", "False")}
    if question["type"] in exact:
        return exact[question["type"]][0 if right else 1]
    return "RIGHT answer" if right else "WRONG answer"


def answer(orchestrator, quiz, quiz_data, username, right: bool):
    question = quiz_data["current_question"]
    context = {"quiz_data": quiz_data, "selected_week": 1, "interaction_count": len(quiz_data["answers"]) + 1,
               "question_number": quiz_data["current_question_index"] + 1,
               "total_questions": len(quiz_data["question_plan"]),
               "completed_questions": len(quiz_data["answers"])}
    state = orchestrator.process_interaction(username, COURSE, InteractionType.QUIZ_ANSWER, "answer",
                                                   "quiz", context)
    given = given_answer(question, right)
    result = quiz.submit_answer(quiz_data, given)
    orchestrator.record_graded_response(username, COURSE, mode="quiz", go_id=question["go_id"],
                                              correct=result["correct"], score=result["score"],
                                              question_type=question["type"], student_response=given)
    return state


def test_scripted_demo101_session_adapts(orchestrator, quiz, username):
    quiz_data = _start(quiz, username)
    states = []
    pattern = [False] * 4 + [True] * 4
    for right in pattern:
        states.append(answer(orchestrator, quiz, quiz_data, username, right))
        quiz_data = quiz.get_next_question(quiz_data)

    after_wrong = (orchestrator.process_interaction(
        username, COURSE, InteractionType.QUIZ_ANSWER, "x", "quiz", {"selected_week": 1}))
    # states[4] was computed after the four wrong answers; the final one after four right answers.
    struggling, recovered = states[4]["cognitive_state"], after_wrong["cognitive_state"]
    assert struggling.zpd_score == pytest.approx(0.0)
    assert recovered.zpd_score == pytest.approx(1.0)
    assert struggling.cognitive_load > recovered.cognitive_load
    assert INTENSITY.index(states[4]["scaffolding_strategy"]["intensity_level"]) > \
        INTENSITY.index(after_wrong["scaffolding_strategy"]["intensity_level"])

    mastery = (orchestrator.mcp_client.get_mastery_summary(username, COURSE))["data"]
    assert len(mastery["go_masteries"]) >= 4
    assert mastery["total_interactions"] == len(pattern)
    assert any(lo.startswith("LO_01_") for lo in mastery["lo_masteries"])


def test_whole_quiz_for_a_non_programming_course_has_no_code(quiz, fake_llm, monkeypatch, username):
    class NoCodeRegistry:
        def profile(self, code):
            return CourseProfile(code=code, name="Psychology-style course", allows_code=False)

    monkeypatch.setattr("src.quiz.simple_quiz_system.default_registry", lambda: NoCodeRegistry())
    quiz_data = _start(quiz, username)
    seen = 0
    while quiz_data:
        assert quiz_data["current_question"]["has_code"] is False
        seen += 1
        quiz_data = quiz.get_next_question(quiz_data)
    prompts = [c["messages"][-1]["content"] for c in fake_llm.calls]
    assert seen >= 10
    assert not any("CODING QUESTION" in p for p in prompts)
    assert all("does not involve programming" in p for p in prompts)


def _start(quiz, username):
    return quiz.start_quiz(COURSE, 1, username)


def test_quiz_skips_a_first_question_that_cannot_be_generated(quiz, fake_llm, username):
    calls = {"n": 0}

    def flaky(messages):
        calls["n"] += 1
        return "not json" if calls["n"] <= 2 else question_writer(messages)  # first item fails twice

    fake_llm._responder = flaky
    quiz_data = _start(quiz, username)
    assert quiz_data is not None
    assert quiz_data["current_question_index"] == 1
    assert quiz_data["current_question"]["go_id"] == quiz_data["question_plan"][1]["go_id"]
