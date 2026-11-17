"""The adaptive loop: graded evidence and stored mastery must reach the orchestrator.

These tests describe the behaviour in the papers: ZPD is the mean accuracy of the
learner's last four graded responses, mastery updates persist, and scaffolding responds
to both.
"""

import pytest

from src.core.agent_orchestrator_mcp import InteractionType

COURSE = "DEMO101"
GOS = ["GO_01_01_001", "GO_01_01_002", "GO_01_01_003", "GO_01_01_004"]


def _tutor_turn(orchestrator, username, text="I think it is about learning from data"):
    return orchestrator.process_interaction(
        username=username,
        course=COURSE,
        interaction_type=InteractionType.TUTOR_RESPONSE,
        student_input=text,
        current_mode="tutor",
        session_context={"selected_week": 1, "interaction_count": 1},
    )


def test_stored_mastery_reaches_the_orchestrator(orchestrator, mcp_server, username):
    tracker = mcp_server.tool_registry.mastery_tracker
    for go_id in GOS:
        tracker.update_learner_mastery(
            username, COURSE, "answer", go_id, "LO_01_01", 1,
            {"is_quiz": True, "correct": True, "score": 0.95, "question_type": "multiple_choice"},
        )

    result = _tutor_turn(orchestrator, username)
    state = result["cognitive_state"]

    assert state.mastery_data.get("go_masteries"), "orchestrator should see the saved GO masteries"
    assert state.zpd_score > 0.8
    assert state.motivation_score > 0.0


def test_mastery_update_tool_persists_mastery(orchestrator, username):
    result = orchestrator.mcp_client.update_mastery(username, COURSE, {
        "go_id": "GO_01_01_002", "correct": True, "score": 0.9,
        "question_type": "multiple_choice", "mode": "quiz", "student_response": "B",
    })
    assert result["success"]

    summary = orchestrator.mcp_client.get_mastery_summary(username, COURSE)
    data = summary["data"]
    assert "GO_01_01_002" in data["go_masteries"]
    assert "LO_01_01" in data["lo_masteries"], "LO id should come from the KC model"


def test_zpd_is_mean_accuracy_of_last_four_graded_responses(orchestrator, username):
    for correct in (True, False, True, True, True):
        orchestrator.record_graded_response(
            username, COURSE, mode="quiz", go_id="GO_01_01_001", correct=correct,
            score=1.0 if correct else 0.0, question_type="multiple_choice",
        )

    state = (_tutor_turn(orchestrator, username))["cognitive_state"]
    assert state.zpd_score == pytest.approx(0.75)  # last four: F, T, T, T


def test_ungraded_responses_do_not_count_towards_zpd(orchestrator, username):
    for _ in range(3):
        orchestrator.record_graded_response(
            username, COURSE, mode="quiz", go_id="GO_01_01_001", correct=True, score=1.0,
        )
    orchestrator.record_graded_response(
        username, COURSE, mode="quiz", go_id="GO_01_01_001", correct=None, score=None,
    )

    state = (_tutor_turn(orchestrator, username))["cognitive_state"]
    assert state.zpd_score == pytest.approx(1.0)


def test_scaffolding_responds_to_performance(orchestrator, username):
    def record(correct, n=4):
        for _ in range(n):
            orchestrator.record_graded_response(
                username, COURSE, mode="quiz", go_id="GO_01_01_001", correct=correct,
                score=1.0 if correct else 0.0,
            )

    record(False)
    struggling = _tutor_turn(orchestrator, username)
    record(True)
    succeeding = _tutor_turn(orchestrator, username)

    s1, s2 = struggling["cognitive_state"], succeeding["cognitive_state"]
    assert s1.zpd_score == pytest.approx(0.0)
    assert s2.zpd_score == pytest.approx(1.0)
    assert s1.cognitive_load > s2.cognitive_load
    order = ["minimal", "low", "medium", "high", "very_high"]
    assert order.index(struggling["scaffolding_strategy"]["intensity_level"]) > \
        order.index(succeeding["scaffolding_strategy"]["intensity_level"])
