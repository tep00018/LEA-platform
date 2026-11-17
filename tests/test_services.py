"""The service layer: quiz, tutor and chat flows, stored sessions, locks and accounts.

Everything runs on fakeredis with the scripted LLM; answers containing RIGHT are graded
correct (see ``question_writer``).
"""

import json
import threading
import time

import pytest

from src.services.chat import CHAT_SITTING_GAP, FAILURE_REPLY
from src.services.courses import lo_display_title
from src.services.errors import Busy, InvalidInput, NoActiveSession, WrongState
from src.services.models import ChatState, QuizState
from tests.test_acceptance_phase1 import given_answer, question_writer

COURSE = "DEMO101"
WEEK1_GOS = ["GO_01_01_001", "GO_01_01_002", "GO_01_01_003", "GO_01_01_004", "GO_01_02_001", "GO_01_02_002",
             "GO_01_02_003", "GO_01_03_001", "GO_01_03_002", "GO_01_03_003", "GO_01_03_004"]


@pytest.fixture
def svc(services, fake_llm):
    fake_llm._responder = lambda m: (
        question_writer(m) if ("Return JSON" in m[-1]["content"] or "<answer>" in m[-1]["content"]
                               or "JSON" in m[0]["content"])
        else "Tutor says: what is AI?"
    )
    return services


def evidence(services, username):
    conn = services.redis_client.get_redis()
    return [json.loads(x) for x in conn.lrange(f"evidence:{username}:{COURSE}", 0, -1)]


def answer_current(services, username, state, right):
    return services.quiz.answer(username, given_answer(state.current_question, right))


# ----------------------------------------------------------------------------- quiz


def test_quiz_flow_records_graded_answers_and_survives_a_restart(svc, username, redis_url, fake_llm, monkeypatch):
    state = svc.quiz.start(username, COURSE, 1)
    assert state.status == "question" and state.total == 11 and state.position == 1

    state = answer_current(svc, username, state, right=False)
    assert state.status == "feedback" and state.feedback.correct is False
    with pytest.raises(WrongState):
        svc.quiz.answer(username, "again")
    with pytest.raises(InvalidInput):
        svc.quiz.answer(username, "   ")

    state = svc.quiz.next(username)
    assert state.status == "question" and state.position == 2 and state.feedback is None

    # A new process (e.g. LEA restarted) sees the same quiz
    monkeypatch.setattr("src.mcp.tool_registry.RAGRetrievalTool", __import__("tests.fakes").fakes.StubRAGTool)
    from src.services.container import build_services
    fresh = build_services(redis_url, openai_client=fake_llm)
    resumed = fresh.quiz.current(username)
    assert resumed.quiz_id == state.quiz_id and resumed.position == 2
    resumed = answer_current(fresh, username, resumed, right=True)
    assert resumed.feedback.correct is True

    assert [e["correct"] for e in evidence(svc, username)] == [False, True]
    assert svc.quiz.start(username, COURSE, 1).quiz_id == state.quiz_id  # start resumes, doesn't restart

    ended = svc.quiz.end(username)
    assert ended.status == "completed" and ended.correct_count == 1 and ended.graded_count == 2
    svc.quiz.discard(username)
    assert svc.quiz.current(username) is None
    with pytest.raises(NoActiveSession):
        svc.quiz.next(username)


def test_quiz_questions_follow_the_latest_learner_state(svc, username):
    state = svc.quiz.start(username, COURSE, 1)
    state = answer_current(svc, username, state, right=False)
    ctx = state.orchestrator_context
    assert ctx["processing_successful"] is True
    assert isinstance(ctx["cognitive_state"]["cognitive_load"], float)
    json.dumps(ctx)  # stored as JSON


def test_quiz_completion_moves_a_ready_learner_to_the_next_week(svc, username):
    for go in WEEK1_GOS:  # master week 1 before the quiz
        for _ in range(4):
            svc.orchestrator.record_graded_response(username, COURSE, mode="quiz", go_id=go, correct=True, score=1.0)
    svc.accounts.auth.redis_client.update_user_progress(username=username, course=COURSE, week=1, completion=0.0)

    state = svc.quiz.start(username, COURSE, 1)
    state = answer_current(svc, username, state, right=True)
    assert state.week_ready
    while state.status != "completed":
        state = svc.quiz.next(username) if state.status == "feedback" else answer_current(svc, username, state, True)
    assert state.advanced_to_week == 2
    assert svc.progress.current_week(username, COURSE) == 2


def test_double_submit_is_rejected_not_double_counted(svc, username, fake_llm):
    state = svc.quiz.start(username, COURSE, 1)
    answer = given_answer(state.current_question, right=True)
    slow = fake_llm._responder

    def slow_responder(messages):
        time.sleep(0.3)
        return slow(messages)

    fake_llm._responder = slow_responder
    outcomes = []

    def submit():
        try:
            svc.quiz.answer(username, answer)
            outcomes.append("ok")
        except (Busy, WrongState) as e:
            outcomes.append(type(e).__name__)

    threads = [threading.Thread(target=submit) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(outcomes)[-1] == "ok" and outcomes.count("ok") == 1
    assert len(evidence(svc, username)) == 1


def test_parallel_mastery_updates_are_not_lost(svc, username):
    """Without the mastery lock, concurrent read-modify-writes overwrite each other."""
    tracker = svc.orchestrator.mcp_client.mcp_server.tool_registry.mastery_tracker
    original_load = tracker.load_learner_mastery

    def slow_load(*args, **kwargs):
        result = original_load(*args, **kwargs)
        time.sleep(0.05)  # widen the window between read and write
        return result

    tracker.load_learner_mastery = slow_load
    threads = [
        threading.Thread(target=svc.orchestrator.record_graded_response,
                         args=(username, COURSE), kwargs=dict(mode="quiz", go_id=go, correct=True, score=1.0))
        for go in WEEK1_GOS[:6]
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    summary = tracker.get_mastery_summary(username, COURSE)
    assert summary["total_interactions"] == 6
    assert set(summary["go_masteries"]) == set(WEEK1_GOS[:6])


# ----------------------------------------------------------------------------- tutor


def test_tutor_flow(svc, username):
    state = svc.tutor.start(username, COURSE, 1)
    assert state.session.current_go_index == 0 and state.session.conversation_history[0]["role"] == "tutor"
    assert svc.tutor.start(username, COURSE, 1).session.session_id == state.session.session_id

    reply = svc.tutor.respond(username, "RIGHT answer: AI is machines doing tasks that need intelligence")
    assert reply.graded is False  # the opening reply is diagnostic
    assert reply.state.session.current_go_index == 1
    reply = svc.tutor.respond(username, "RIGHT answer: narrow and general AI")
    assert reply.graded and reply.correct is True and reply.state.session.current_go_index == 2
    assert [e["correct"] for e in evidence(svc, username)] == [None, True]

    assert svc.tutor.current(username).session.current_go_index == 2  # stored
    summary = svc.tutor.end(username)
    assert summary["gos_completed"] == 2 and svc.tutor.current(username) is None
    with pytest.raises(NoActiveSession):
        svc.tutor.respond(username, "hello")


def test_tutor_reviews_a_finished_quiz_without_regrading_it(svc, username, fake_llm):
    state = svc.quiz.start(username, COURSE, 1)
    missed_question = state.current_question["text"]
    answer_current(svc, username, state, right=False)
    state = svc.quiz.next(username)
    answer_current(svc, username, state, right=True)
    unfinished = svc.quiz.current(username)

    plain = svc.tutor.start(username, COURSE, 1, quiz=unfinished)  # not finished: an ordinary start
    assert plain.session.quiz_review is None
    quiz = svc.quiz.end(username)
    assert svc.tutor.start(username, COURSE, 2, quiz=quiz).session.quiz_review is None  # other week

    before = evidence(svc, username)
    review = svc.tutor.start(username, COURSE, 1, quiz=quiz)
    notes = review.session.quiz_review
    assert notes.startswith("Week 1 quiz: 1 of 2 graded answers correct.")
    assert "Missed:" in notes and missed_question[:40] in notes and "Answered correctly:" in notes
    opening = review.session.conversation_history[0]["content"]
    assert opening.startswith("Let's go over your Week 1 quiz. You got 1 of 2 right.")
    assert evidence(svc, username) == before  # starting the review records nothing

    svc.tutor.respond(username, "RIGHT answer: AI is machines doing tasks that need intelligence")
    assert "QUIZ REVIEW" in fake_llm.last_prompt and missed_question[:40] in fake_llm.last_prompt
    assert svc.quiz.current(username).correct_count == 1  # the quiz itself is untouched


def master(svc, username, go_ids):
    for go in go_ids:
        for _ in range(4):
            svc.orchestrator.record_graded_response(username, COURSE, mode="quiz", go_id=go, correct=True, score=1.0)


def last_tutor_start(svc, username):
    rows = [r for r in svc.events.log.query("type = 'tutor_start'") if r["username_hash"] == svc.events.pseudonym(username)]
    return json.loads(rows[-1]["payload_json"])


def test_select_objectives_orders_and_explains_the_choice():
    from src.services.tutor import select_objectives

    gos = [{"go_id": "A", "mastery_threshold": 0.8}, {"go_id": "B", "mastery_threshold": 0.7},
           {"go_id": "C", "mastery_threshold": None}, {"go_id": "D"}]
    mastery = {"A": 0.9, "B": 0.69, "C": 0.79}
    assert select_objectives(gos, mastery) == ([gos[1], gos[2], gos[3]], "unmastered")  # C: default 0.8
    assert select_objectives(gos, mastery, ["D", "A", None]) == ([gos[0], gos[3]], "quiz_missed")  # week order
    assert select_objectives(gos, {"A": 1, "B": 1, "C": 1, "D": 1}) == ([], "all_mastered")
    assert select_objectives(gos, {"A": 1, "B": 1, "C": 1, "D": 1}, ["Z"]) == ([], "all_mastered")  # unknown id


def test_review_teaches_only_the_objectives_the_quiz_got_wrong(svc, username):
    state = svc.quiz.start(username, COURSE, 1)
    for right in (False, True, False, True):
        state = answer_current(svc, username, state, right=right)
        state = svc.quiz.next(username)
    quiz = svc.quiz.end(username)
    missed = [r.go_id for r in quiz.results if r.graded and not r.correct]
    assert len(missed) == 2

    review = svc.tutor.start(username, COURSE, 1, quiz=quiz)
    assert [g["go_id"] for g in review.session.go_list] == [g for g in WEEK1_GOS if g in missed]
    assert review.session.current_go_index == 0 and not review.completed
    assert "just those" in review.session.conversation_history[0]["content"]
    payload = last_tutor_start(svc, username)
    assert payload["selection"] == "quiz_missed" and payload["objectives"] == 2
    assert payload["week_objectives"] == len(WEEK1_GOS) and payload["skipped_objectives"] == len(WEEK1_GOS) - 2


def test_tutor_does_not_reteach_mastered_objectives(svc, username):
    master(svc, username, WEEK1_GOS[:3] + WEEK1_GOS[5:6])  # one mastered objective sits mid-week
    state = svc.tutor.start(username, COURSE, 1)
    taught = [g["go_id"] for g in state.session.go_list]
    assert taught == WEEK1_GOS[3:5] + WEEK1_GOS[6:]
    assert state.session.current_go_index == 0 and not state.completed
    payload = last_tutor_start(svc, username)
    assert payload["selection"] == "unmastered" and payload["skipped_objectives"] == 4


def test_a_fully_mastered_week_is_not_taught_again(svc, username):
    master(svc, username, WEEK1_GOS)
    svc.accounts.auth.redis_client.update_user_progress(username=username, course=COURSE, week=1, completion=0.0)
    before = evidence(svc, username)

    state = svc.tutor.start(username, COURSE, 1)
    assert state.completed and state.current_objective is None and state.progress_percent == 100.0
    message = state.session.conversation_history[0]["content"]
    assert "already mastered every concept in Week 1" in message
    assert "refresher" in message and "safe to move on" in message and "Week 2 is now open" in message
    assert state.advanced_to_week == 2 and svc.progress.current_week(username, COURSE) == 2
    assert last_tutor_start(svc, username)["selection"] == "all_mastered"
    assert evidence(svc, username) == before  # nothing recorded

    reply = svc.tutor.respond(username, "can we go over it again?")
    assert reply.graded is False and "every objective" in reply.message
    assert svc.tutor.end(username)["advanced_to_week"] == 2
    assert svc.tutor.current(username) is None


# ----------------------------------------------------------------------------- chat


def test_chat_answers_and_keeps_history_without_touching_mastery(svc, username, fake_llm):
    fake_llm._responder = lambda m: "Machine learning is learning from data."
    reply = svc.chat.send(username, COURSE, 1, "What is machine learning?")
    assert reply.ok and reply.message == "Machine learning is learning from data."
    assert [m.role for m in svc.chat.history(username, COURSE)] == ["user", "assistant"]
    assert evidence(svc, username) == []
    with pytest.raises(InvalidInput):
        svc.chat.send(username, COURSE, 1, "  ")


def test_chat_failure_is_reported_not_disguised(svc, username, fake_llm):
    def boom(messages):
        raise RuntimeError("API down")

    fake_llm._responder = boom
    reply = svc.chat.send(username, COURSE, 1, "What is AI?")
    assert reply.ok is False and reply.message == FAILURE_REPLY
    # The unanswered question is dropped, so retrying doesn't duplicate it or add a turn
    assert svc.chat.history(username, COURSE) == []
    fake_llm._responder = lambda m: "AI is..."
    assert svc.chat.send(username, COURSE, 1, "What is AI?").ok
    assert [m.role for m in svc.chat.history(username, COURSE)] == ["user", "assistant"]
    assert svc.chat.store.load(ChatState, "chat", username, COURSE).turns == 1


def test_chat_sitting_resets_after_a_gap(svc, username, fake_llm):
    fake_llm._responder = lambda m: "ok"
    svc.chat.send(username, COURSE, 1, "one")
    svc.chat.send(username, COURSE, 1, "two")
    state = svc.chat.store.load(ChatState, "chat", username, COURSE)
    assert state.turns == 2
    state.last_activity -= CHAT_SITTING_GAP + 1
    svc.chat.store.save(state, "chat", username, COURSE)
    svc.chat.send(username, COURSE, 1, "three")
    assert svc.chat.store.load(ChatState, "chat", username, COURSE).turns == 1


# ----------------------------------------------------------------------------- store, accounts, courses


def test_unreadable_stored_session_is_discarded(svc, username):
    svc.redis_client.get_redis().set(svc.quiz.store.key("quiz", username), '{"quiz_id": 5}')
    assert svc.quiz.current(username) is None
    assert svc.redis_client.get_redis().get(svc.quiz.store.key("quiz", username)) is None


def test_quiz_state_round_trips_through_json(svc, username):
    state = svc.quiz.start(username, COURSE, 1)
    assert QuizState.model_validate_json(state.model_dump_json()) == state


def test_accounts(svc, username):
    with pytest.raises(InvalidInput, match="at least 6"):
        svc.accounts.register(username, "Ada", "short", "short", [COURSE])
    with pytest.raises(InvalidInput, match="at least one course"):
        svc.accounts.register(username, "Ada", "secret123", "secret123", [])
    with pytest.raises(InvalidInput, match="Unknown course"):
        svc.accounts.register(username, "Ada", "secret123", "secret123", ["XYZ999"])
    assert "Account created" in svc.accounts.register(username, "Ada Lovelace", "secret123", "secret123", [COURSE])
    with pytest.raises(InvalidInput):
        svc.accounts.login(username, "wrong-password")
    profile, session_id = svc.accounts.login(username, "secret123")
    assert profile.full_name == "Ada Lovelace" and profile.enrolled_courses == [COURSE] and session_id


def test_course_outline(svc):
    outline = svc.courses.outline(COURSE)
    assert [w.number for w in outline.weeks] == [1, 2, 3]
    assert outline.week(1).concept_count == 11
    assert len(svc.courses.week_objectives(COURSE, 2)) == 9
    with pytest.raises(InvalidInput):
        svc.courses.week_objectives(COURSE, 9)
    with pytest.raises(InvalidInput):
        svc.courses.outline("../etc")


def test_learning_objective_display_titles():
    full = "Describe the scope and structure of human psychology as a scientific discipline"
    # A real short title is shown; the full title stays in the model for prompts.
    assert lo_display_title({"title": full, "short_title": "Psychology as a Science"}) == "Psychology as a Science"
    # The generator's 50-character cut isn't a name: show the full title instead.
    assert lo_display_title({"title": full, "short_title": full[:50] + "..."}) == full
    assert lo_display_title({"title": full}) == full
    assert lo_display_title({"objective_name": "Old style"}) == "Old style"


def test_outline_and_mastery_show_demo_titles_unchanged(svc):
    # DEMO101's short titles equal its titles, so nothing it shows changes.
    titles = [lo.title for w in svc.courses.outline(COURSE).weeks for lo in w.learning_objectives]
    assert titles[:3] == ["AI Basics", "AI Types Overview", "AI vs ML Distinction"]


def test_consolidation_queue_holds_each_session_once(svc, username):
    client = svc.redis_client
    for i in range(8):
        client.store_short_term_memory(username=username, interaction_type="chat", content={"message": str(i)})
    queue = [json.loads(t) for t in client.get_redis().lrange("memory:consolidation:queue", 0, -1)]
    assert sum(1 for t in queue if t["username"] == username) == 1
