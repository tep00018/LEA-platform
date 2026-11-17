"""Headless smoke test of the Streamlit app (no OpenAI calls are made).

Runs the real script with Streamlit's AppTest harness: the login page renders,
a student can register and log in, and the main Chat view renders afterwards.
"""

import uuid

import pytest
from streamlit.testing.v1 import AppTest

APP = "src/ui/streamlit_app.py"
TIMEOUT = 300  # first run loads the reranker model and KC model


@pytest.fixture
def app():
    return AppTest.from_file(APP, default_timeout=TIMEOUT)


def _form_inputs(at, form_key):
    return [ti for ti in at.text_input if form_key in str(ti.proto.form_id)]


def test_login_page_renders(app):
    at = app.run()
    assert not at.exception
    assert [b.label for b in at.button] == ["Log In", "Create Account"]


def test_register_then_login_shows_main_view(app):
    username = f"smoke_{uuid.uuid4().hex[:8]}"
    at = app.run()

    register = _form_inputs(at, "register_form")
    register[0].input(username)
    register[1].input("Smoke Test")
    register[2].input("secret123")
    register[3].input("secret123")
    at.button[1].click().run()
    assert not at.exception
    assert any("Account created" in s.value for s in at.success), [e.value for e in at.error]

    login = _form_inputs(at, "login_form")
    login[0].input(username)
    login[1].input("secret123")
    at.button[0].click().run()
    assert not at.exception

    at.run()  # the app reruns after login
    assert not at.exception
    assert at.session_state["authenticated"] is True
    assert at.session_state["username"] == username
    assert len(at.sidebar.selectbox) >= 1, "course/week selectors should render in the sidebar"
