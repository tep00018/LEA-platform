"""Drive the real Streamlit app through Quiz and Tutor with a scripted model.

Checks the wiring added in Phase 1 (now through the service layer): graded answers reach the evidence store and mastery
(with LO ids from the KC model), progress is written, the mode-switch confirmation works
during a quiz, and a graded correct tutor answer advances the session.
"""

import json
import uuid

import redis
import streamlit as st
from streamlit.testing.v1 import AppTest

from tests.test_acceptance_phase1 import question_writer

APP = "src/ui/streamlit_app.py"


def _button(pool, label):
    return next(b for b in pool if label in b.label)


def _stored(r, kind, user):
    raw = r.get(f"lea:session:{kind}:{user}")
    return json.loads(raw) if raw else None


def _form_inputs(at, form_key):
    return [ti for ti in at.text_input if form_key in str(ti.proto.form_id)]


def test_quiz_and_tutor_flow(fake_llm, redis_url):
    fake_llm._responder = lambda m: (
        question_writer(m)
        if ("Return JSON" in m[-1]["content"] or "<answer>" in m[-1]["content"]
            or "JSON" in m[0]["content"])
        else "Let's start. What is AI?"
    )
    st.cache_resource.clear()  # earlier tests may have cached clients built without the fake
    user = f"ui_{uuid.uuid4().hex[:6]}"

    at = AppTest.from_file(APP, default_timeout=300).run()
    reg = _form_inputs(at, "register_form")
    for widget, value in zip(reg, [user, "UI Test", "secret123", "secret123"]):
        widget.input(value)
    at.multiselect[0].set_value(["DEMO101"])  # these flows are written against the test course
    at.button[1].click().run()
    assert "Account created" in at.success[0].value
    login = _form_inputs(at, "login_form")
    login[0].input(user)
    login[1].input("secret123")
    at.button[0].click().run()
    at.run()
    assert not at.exception

    # Quiz: three wrong answers
    _button(at.sidebar.button, "Quiz Mode").click().run()
    _button(at.button, "Start Quiz").click().run()
    assert not at.exception
    r = redis.from_url(redis_url)
    for _ in range(3):
        question = _stored(r, "quiz", user)["current_question"]
        if question["type"] == "multiple_choice":
            at.radio[0].set_value(at.radio[0].options[3]).run()
            _button(at.button, "Submit Answer").click().run()
        elif question["type"] == "true_false":
            _button(at.button, "False").click().run()
        elif question["type"] == "fill_in_blank":
            at.text_input[0].input("WRONG answer").run()
            _button(at.button, "Submit Answer").click().run()
        else:
            at.text_area[0].input("WRONG answer given here").run()
            _button(at.button, "Submit Answer").click().run()
        assert not at.exception
        assert at.error and at.error[0].value.startswith("❌ Incorrect")
        _button(at.button, "Continue").click().run()

    evidence = [json.loads(x) for x in r.lrange(f"evidence:{user}:DEMO101", 0, -1)]
    assert [e["correct"] for e in evidence] == [False, False, False]
    mastery = json.loads(r.get(f"mastery:{user}:DEMO101"))
    assert len(mastery["go_masteries"]) == 3
    assert list(mastery["lo_masteries"]) == ["LO_01_01"]
    progress = json.loads(r.hget(f"progress:{user}", "DEMO101"))
    assert progress["completion"] == 0.0 and progress["completed_gos"] == []

    # Switching mode during a quiz asks first, then switches
    _button(at.sidebar.button, "Tutor Mode").click().run()
    assert "Quiz in progress" in at.sidebar.warning[0].value
    _button(at.sidebar.button, "Yes, switch").click().run()
    assert not at.exception
    assert at.session_state["current_mode"] == "tutor"
    assert _stored(r, "quiz", user) is None

    # Tutor: the opening reply is diagnostic (can advance, not counted as evidence);
    # after that, a graded correct answer is recorded and advances the objective.
    _button(at.main.button, "Start Tutoring Session").click().run()
    assert not at.exception
    at.chat_input[0].set_value("RIGHT answer: AI is machines doing tasks that need intelligence").run()
    assert not at.exception
    assert _stored(r, "tutor", user)["session"]["current_go_index"] == 1
    evidence = [json.loads(x) for x in r.lrange(f"evidence:{user}:DEMO101", 0, -1)]
    assert evidence[-1]["mode"] == "tutor" and evidence[-1]["correct"] is None
    at.chat_input[0].set_value("RIGHT answer: types of AI are narrow and general").run()
    assert not at.exception
    assert _stored(r, "tutor", user)["session"]["current_go_index"] == 2
    evidence = [json.loads(x) for x in r.lrange(f"evidence:{user}:DEMO101", 0, -1)]
    assert evidence[-1]["mode"] == "tutor" and evidence[-1]["correct"] is True

    # Chat: a question gets an answer and no mastery update (chat is ungraded)
    before = r.llen(f"evidence:{user}:DEMO101")
    _button(at.sidebar.button, "Chat Mode").click().run()
    at.chat_input[0].set_value("What is machine learning?").run()
    assert not at.exception
    assert any("What is AI?" in m.markdown[0].value for m in at.chat_message if m.markdown)
    new = [json.loads(x) for x in r.lrange(f"evidence:{user}:DEMO101", before, -1)]
    assert new == [], (at.session_state["current_mode"], new)


def test_week_selector_follows_stored_progress(fake_llm, redis_url):
    st.cache_resource.clear()
    user = f"ui_{uuid.uuid4().hex[:6]}"
    at = AppTest.from_file(APP, default_timeout=300).run()
    reg = _form_inputs(at, "register_form")
    for widget, value in zip(reg, [user, "UI Test", "secret123", "secret123"]):
        widget.input(value)
    at.multiselect[0].set_value(["DEMO101"])  # these flows are written against the test course
    at.button[1].click().run()
    redis.from_url(redis_url).hset(f"progress:{user}", "DEMO101", json.dumps({"week": 2, "completion": 0.0}))

    login = _form_inputs(at, "login_form")
    login[0].input(user)
    login[1].input("secret123")
    at.button[0].click().run()
    at.run()
    assert not at.exception
    assert at.session_state["selected_week"] == 2
    assert "Week 2" in at.sidebar.selectbox[1].value


def _logged_in_app(user):
    at = AppTest.from_file(APP, default_timeout=300).run()
    reg = _form_inputs(at, "register_form")
    for widget, value in zip(reg, [user, "UI Test", "secret123", "secret123"]):
        widget.input(value)
    at.multiselect[0].set_value(["DEMO101"])  # these flows are written against the test course
    at.button[1].click().run()
    login = _form_inputs(at, "login_form")
    login[0].input(user)
    login[1].input("secret123")
    at.button[0].click().run()
    at.run()
    assert not at.exception
    return at


def test_chat_failure_is_shown_and_week_change_leaves_quiz_resumable(fake_llm, redis_url):
    st.cache_resource.clear()
    user = f"ui_{uuid.uuid4().hex[:6]}"
    at = _logged_in_app(user)

    def boom(messages):
        raise RuntimeError("API down")

    fake_llm._responder = boom
    at.chat_input[0].set_value("What is AI?").run()
    assert not at.exception
    assert any("couldn't answer" in e.value for e in at.error)

    # Start a week-1 quiz, move to week 2 (fresh start offered), come back (quiz resumes)
    fake_llm._responder = question_writer
    _button(at.sidebar.button, "Quiz Mode").click().run()
    _button(at.button, "Start Quiz").click().run()
    r = redis.from_url(redis_url)
    quiz_id = _stored(r, "quiz", user)["quiz_id"]
    weeks = at.sidebar.selectbox[1]
    weeks.set_value(weeks.options[1]).run()
    assert not at.exception and any("Start Quiz" in b.label for b in at.button)
    at.sidebar.selectbox[1].set_value(at.sidebar.selectbox[1].options[0]).run()
    assert not at.exception and any("End Quiz" in b.label for b in at.button)
    assert _stored(r, "quiz", user)["quiz_id"] == quiz_id
