"""LEA's Streamlit front end.

A thin client over the service layer (``src.services``): this file draws the pages and
keeps only UI state (who is logged in, the selected course, week and mode). Quiz, tutor
and chat sessions live in Redis through the services, so a refresh resumes them.
"""

import logging
import sys
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

import streamlit as st

# Make ``src`` importable when Streamlit runs this file directly
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from src.logging_config import setup_logging  # noqa: E402

setup_logging()
logger = logging.getLogger("src.ui.streamlit_app")

from src.config_check import check_configuration  # noqa: E402
from src.services.errors import ServiceError  # noqa: E402
from src.ui.avatars import (  # noqa: E402
    create_student_avatar, get_lea_avatar, load_page_icon, pil_image_to_base64,
)


class AppMode(Enum):
    CHAT = "chat"
    TUTOR = "tutor"
    QUIZ = "quiz"


st.set_page_config(
    page_title="LEA - Learning Assistant",
    page_icon=load_page_icon(),
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .main {
        padding: 0;
        max-width: 1400px;
        margin: 0 auto;
    }
    
    .quiz-progress {
        background-color: #e9ecef;
        padding: 1rem;
        border-radius: 8px;
        margin-bottom: 1rem;
        text-align: center;
        font-weight: 600;
    }
    
    .feedback-correct {
        background-color: #d4edda;
        border: 1px solid #c3e6cb;
        color: #155724;
        padding: 1rem;
        border-radius: 8px;
        margin: 1rem 0;
    }
    
    .feedback-incorrect {
        background-color: #f8d7da;
        border: 1px solid #f5c6cb;
        color: #721c24;
        padding: 1rem;
        border-radius: 8px;
        margin: 1rem 0;
    }
    
    .quiz-summary {
        background-color: #e7f3ff;
        border: 1px solid #b8daff;
        color: #004085;
        padding: 1.5rem;
        border-radius: 8px;
        margin: 1rem 0;
        text-align: center;
    }
    
    .stButton > button {
        font-size: 0.85rem !important;
        padding: 0.4rem 0.8rem !important;
    }
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def get_services():
    """Every LEA service, built once per Streamlit process."""
    from src.services.container import build_services

    services = build_services()
    services.start_background_work()
    return services


@st.cache_data(ttl=300)
def _course_outline(course: str):
    return get_services().courses.outline(course)


def course_outline(course: Optional[str]):
    """The course's weeks, or None (with a message) if its KC model can't be read."""
    if not course:
        return None
    try:
        return _course_outline(course)
    except ServiceError as e:
        st.error(str(e))
    except Exception:
        logger.exception("Could not load the outline of %s", course)
        st.error(f"Couldn't load the weeks for {course}.")
    return None


# ============================================================================ helpers


def run(action: Callable, *args, **kwargs):
    """Call a service; show its error message instead of a traceback. Returns None on error."""
    try:
        return action(*args, **kwargs)
    except ServiceError as e:
        st.error(str(e))
    except Exception:
        logger.exception("Unexpected error in %s", getattr(action, "__qualname__", action))
        st.error("Something went wrong. Please try again.")
    return None


def flash(kind: str, text: str) -> None:
    """Show a message on the next run (messages shown before st.rerun() are lost)."""
    st.session_state.setdefault("flash", []).append((kind, text))


def show_flash() -> None:
    for kind, text in st.session_state.pop("flash", []):
        if kind == "toast":
            st.toast(text)
        else:
            getattr(st, kind)(text)


def initialize_session_state() -> None:
    defaults = {
        "authenticated": False,
        "username": "",
        "enrolled_courses": [],
        "selected_course": None,
        "selected_week": 1,
        "current_mode": AppMode.CHAT.value,  # a string: Enum classes are redefined on every rerun
        "pending_mode_switch": None,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def current_mode() -> str:
    return st.session_state.current_mode


def selection():
    return st.session_state.username, st.session_state.selected_course, st.session_state.selected_week


def quiz_for_selection():
    """The learner's quiz, if it belongs to the selected course and week."""
    username, course, week = selection()
    state = get_services().quiz.current(username)
    return state if state and (state.course, state.week) == (course, week) else None


def tutor_for_selection():
    username, course, week = selection()
    state = get_services().tutor.current(username)
    return state if state and (state.session.course, state.session.week) == (course, week) else None


def select_course(course: str) -> None:
    st.session_state.selected_course = course
    st.session_state.selected_week = get_services().progress.current_week(st.session_state.username, course)


# ============================================================================ login


def render_login_page() -> None:
    services = get_services()
    _, col2, _ = st.columns([1, 2, 1])
    with col2:
        avatar_b64 = pil_image_to_base64(get_lea_avatar())
        st.markdown(f"""
        <div style="text-align: center; margin-bottom: 2rem;">
            <div style="display: flex; align-items: center; justify-content: center; gap: 20px;">
                <div style="display: flex; flex-direction: column; align-items: center;">
                    <img src="{avatar_b64}" style="width: 80px; height: 80px; border-radius: 50%; margin-bottom: 5px;">
                    <span style="font-size: 1.2rem; font-weight: bold; color: #262730;">LEA</span>
                </div>
                <div style="text-align: left;">
                    <span style="font-size: 2.5rem; font-weight: bold; color: #262730; line-height: 1.2;">
                        Learning Engagement<br>Assistant
                    </span>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown("<p style='text-align: center; color: #6c757d; font-size: 1.1rem; margin-bottom: 2rem;'>"
                    "Slide In. Study Up. Show Off.</p>", unsafe_allow_html=True)

        tab1, tab2 = st.tabs(["Login", "Register"])
        with tab1:
            with st.form("login_form"):
                username = st.text_input("Username")
                password = st.text_input("Password", type="password")
                if st.form_submit_button("Log In", use_container_width=True, type="primary"):
                    result = run(services.accounts.login, username, password)
                    if result:
                        profile, token = result
                        st.session_state.auth_token = token
                        st.session_state.authenticated = True
                        st.session_state.username = profile.username
                        st.session_state.enrolled_courses = profile.enrolled_courses
                        if profile.enrolled_courses:
                            select_course(profile.enrolled_courses[0])
                        st.rerun()

        with tab2:
            with st.form("register_form"):
                new_username = st.text_input("Username")
                full_name = st.text_input("Full Name")
                new_password = st.text_input("Password", type="password")
                confirm_password = st.text_input("Confirm Password", type="password")
                courses = services.courses.available()
                selected_courses = st.multiselect("Select Courses:", courses,
                                                  default=["AIML101"] if "AIML101" in courses else [])
                if st.form_submit_button("Create Account", use_container_width=True, type="primary"):
                    message = run(services.accounts.register, new_username, full_name, new_password,
                                  confirm_password, selected_courses)
                    if message:
                        # No rerun: it would wipe this message and the student would think nothing happened.
                        st.success(message)


# ============================================================================ sidebar


def mode_status(mode: AppMode) -> dict:
    services = get_services()
    username, course, _ = selection()
    if not course:
        return {"emoji": "", "text": ""}
    if mode is AppMode.CHAT:
        count = sum(1 for m in services.chat.history(username, course) if m.role == "user")
        return {"emoji": "💭", "text": f"({count} msgs)"} if count else {"emoji": "💬", "text": ""}
    if mode is AppMode.TUTOR:
        state = tutor_for_selection()
        if state and state.completed:
            return {"emoji": "✅", "text": "(Complete)"}
        if state:
            return {"emoji": "📖", "text": f"({state.progress_percent:.0f}%)"}
        return {"emoji": "🎓", "text": ""}
    state = quiz_for_selection()
    if state and state.status == "completed":
        accuracy = state.correct_count / state.graded_count * 100 if state.graded_count else 0
        return {"emoji": "✅", "text": f"({accuracy:.0f}%)"}
    if state:
        return {"emoji": "⏳", "text": f"({state.position}/{state.total})"}
    return {"emoji": "⭐", "text": ""}


def switch_mode(new_mode: AppMode, confirmed: bool = False) -> None:
    services = get_services()
    username = st.session_state.username
    quiz = quiz_for_selection()
    quiz_running = quiz is not None and quiz.status != "completed"
    if quiz_running and not confirmed:
        st.session_state.pending_mode_switch = new_mode.value  # the sidebar asks on the next run
        st.rerun()
    st.session_state.pending_mode_switch = None
    if quiz_running:
        # The student chose to leave the quiz: it ends here, and the answers so far stand.
        quiz = run(services.quiz.end, username)
        run(services.quiz.discard, username)
    if quiz is not None and quiz.status == "completed" and quiz.advanced_to_week:
        follow_week_advancement(quiz.week, quiz.advanced_to_week)
        run(services.quiz.discard, username)
    st.session_state.current_mode = new_mode.value
    st.rerun()


def follow_week_advancement(week: int, next_week: int) -> None:
    """The learner finished ``week``: select the next one and say so."""
    st.session_state.selected_week = next_week
    flash("toast", f"🎉 Week {week} complete. Week {next_week} is now unlocked.")


def render_sidebar() -> None:
    with st.sidebar:
        st.markdown("### 🧭 Command Center")

        courses = st.session_state.enrolled_courses
        if courses:
            course = st.selectbox("Course:", courses, index=courses.index(st.session_state.selected_course)
                                  if st.session_state.selected_course in courses else 0)
            if course != st.session_state.selected_course:
                select_course(course)
                st.rerun()

        outline = course_outline(st.session_state.selected_course)
        weeks = outline.weeks if outline else []
        if weeks:
            numbers = [w.number for w in weeks]
            index = numbers.index(st.session_state.selected_week) if st.session_state.selected_week in numbers else 0
            title = st.selectbox("Week:", [w.title for w in weeks], index=index)
            new_week = weeks[[w.title for w in weeks].index(title)].number
            if new_week != st.session_state.selected_week:
                st.session_state.selected_week = new_week
                st.rerun()

        st.markdown("---")
        st.markdown("### ✨ Learning Modes")
        modes = {
            AppMode.CHAT: ("💬 Chat Mode", "Ask questions"),
            AppMode.TUTOR: ("🎓 Tutor Mode", "Guided learning"),
            AppMode.QUIZ: ("⭐ Quiz Mode", "Test knowledge"),
        }
        for mode, (label, description) in modes.items():
            is_current = current_mode() == mode.value
            status = mode_status(mode)
            col1, col2 = st.columns([3, 1])
            with col1:
                if st.button(label, use_container_width=True, type="primary" if is_current else "secondary",
                             disabled=is_current, key=f"mode_btn_{mode.value}"):
                    switch_mode(mode)
            with col2:
                st.markdown(status["emoji"])
            st.caption(f"✨ {description}" if is_current else f"{description} {status['text']}")

        pending = st.session_state.get("pending_mode_switch")
        if pending:
            st.warning("⚠️ Quiz in progress. Leave the quiz and switch modes?")
            confirm_col, cancel_col = st.columns(2)
            if confirm_col.button("✅ Yes, switch", type="primary", key="confirm_mode_switch"):
                switch_mode(AppMode(pending), confirmed=True)
            if cancel_col.button("❌ Stay in quiz", key="cancel_mode_switch"):
                st.session_state.pending_mode_switch = None
                st.rerun()

        st.markdown("---")
        if st.button("Logout", use_container_width=True, key="logout_btn"):
            if st.session_state.get("auth_token"):
                run(get_services().accounts.logout, st.session_state.auth_token)
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()


# ============================================================================ main area


def render_main_content() -> None:
    titles = {"chat": "💬 Chat with LEA", "tutor": "📝 Flex Your Smarts", "quiz": "⭐ Quiz It Like You Mean It"}
    st.markdown(f"# {titles.get(current_mode(), '🌀 Learning Mode')}")
    st.markdown(f"**{st.session_state.selected_course} - Week {st.session_state.selected_week}**")
    show_flash()
    if not st.session_state.selected_course:
        st.info("You aren't enrolled in any course yet.")
        return
    {"chat": render_chat_interface, "tutor": render_tutor_interface, "quiz": render_quiz_interface}[current_mode()]()


def render_week_overview(heading_prefix: str):
    outline = course_outline(st.session_state.selected_course)
    week = outline.week(st.session_state.selected_week) if outline else None
    if not week:
        return None
    st.markdown(f"### {heading_prefix}{week.title}", unsafe_allow_html=True)
    st.markdown(f"**Learning Objectives:** {len(week.learning_objectives)}")
    return week


def render_what_we_cover(week) -> None:
    with st.expander("📚 What We'll Cover"):
        for lo in week.learning_objectives:
            st.markdown(f"- **{lo.title}** ({lo.concept_count} concepts)")


# ---------------------------------------------------------------------------- chat


def render_chat_interface() -> None:
    services = get_services()
    username, course, week = selection()
    student_avatar = create_student_avatar(username[0] if username else "U")
    lea_avatar = get_lea_avatar()

    history = services.chat.history(username, course)
    if not history:
        st.chat_message("assistant", avatar=lea_avatar).write(
            f"Hey, I'm LEA 👋 Got questions on {course} Week {week}? I'm here to help!")
    for msg in history:
        if msg.role == "user":
            st.chat_message("user", avatar=student_avatar).write(msg.message)
        else:
            st.chat_message("assistant", avatar=lea_avatar).write(msg.message)

    user_input = st.chat_input("Ask me anything about your course!")
    if user_input and user_input.strip():
        with st.spinner("🧠 Analyzing your question..."):
            reply = run(services.chat.send, username, course, week, user_input)
        if reply is not None:
            if not reply.ok:
                flash("error", reply.message)
            st.rerun()


# ---------------------------------------------------------------------------- tutor


def render_tutor_interface() -> None:
    services = get_services()
    username, course, week = selection()
    st.markdown("---")
    state = tutor_for_selection()

    if state is None or state.completed:
        if state is not None:
            st.success("🎉 Tutoring session completed!")
        _, col2, _ = st.columns([1, 2, 1])
        with col2:
            if st.button("🎓 Start Tutoring Session", use_container_width=True, type="primary", key="main_start_tutor"):
                with st.spinner("Preparing your tutoring session..."):
                    started = run(services.tutor.start, username, course, week)
                if started:
                    st.rerun()
        avatar_b64 = pil_image_to_base64(get_lea_avatar())
        overview = render_week_overview(
            f'<img src="{avatar_b64}" style="width: 30px; height: 30px; vertical-align: middle; '
            f'margin-right: 8px;">Ready to Learn: ')
        if overview:
            st.markdown(f"**Concepts to Master:** {overview.concept_count}")
            render_what_we_cover(overview)
        return

    _, col2, _ = st.columns([1, 2, 1])
    with col2:
        if st.button("❌ End Tutoring Session", use_container_width=True, key="main_end_tutor"):
            summary = run(services.tutor.end, username)
            if summary and summary.get("advanced_to_week"):
                follow_week_advancement(week, summary["advanced_to_week"])
            st.rerun()

    session = state.session
    objective = state.current_objective or {}
    st.markdown(f"""
    <div class="quiz-progress">
        Learning: {objective.get('skill_name', '')} | Progress: {state.progress_percent:.0f}% |
        Scaffolding: {session.scaffolding_level.title()} Support
    </div>
    """, unsafe_allow_html=True)

    student_avatar = create_student_avatar(username[0] if username else "U")
    lea_avatar = get_lea_avatar()
    for msg in session.conversation_history:
        if msg["role"] == "student":
            st.chat_message("user", avatar=student_avatar).write(msg["content"])
        else:
            st.chat_message("assistant", avatar=lea_avatar).write(msg["content"])

    user_input = st.chat_input("Share your thoughts, ask questions, or work through the problem...")
    if user_input and user_input.strip():
        with st.spinner("LEA is thinking..."):
            reply = run(services.tutor.respond, username, user_input)
        if reply is not None:
            for achievement in reply.achievements:
                flash("toast", f"🎉 {achievement}")
            if reply.state.advanced_to_week:
                follow_week_advancement(week, reply.state.advanced_to_week)
            st.rerun()


# ---------------------------------------------------------------------------- quiz


def render_quiz_interface() -> None:
    services = get_services()
    username, course, week = selection()
    state = quiz_for_selection()

    if state is None:
        _, col2, _ = st.columns([1, 2, 1])
        with col2:
            if st.button("⭐ Start Quiz", use_container_width=True, type="primary", key="start_quiz_btn"):
                with st.spinner("🧠 Preparing adaptive quiz..."):
                    started = run(services.quiz.start, username, course, week)
                if started:
                    st.rerun()
        week_info = render_week_overview("📊 ")
        if week_info:
            st.markdown(f"**Total Questions:** {week_info.concept_count}")
            render_what_we_cover(week_info)
        return

    if state.status == "completed":
        if state.advanced_to_week:
            st.info(f"🎉 Week {state.week} complete. Week {state.advanced_to_week} is now unlocked.")
        _, col2, _ = st.columns([1, 2, 1])
        with col2:
            if st.button("🔄 Start New Quiz", use_container_width=True, type="primary", key="new_quiz_btn"):
                if state.advanced_to_week:
                    follow_week_advancement(state.week, state.advanced_to_week)
                run(services.quiz.discard, username)
                st.rerun()
        render_quiz_results(state)
        return

    st.progress(min(1.0, state.position / state.total))
    col1, col2 = st.columns([3, 1])
    with col1:
        st.write(f"Question {state.position} of {state.total} | Correct: {state.correct_count}")
    with col2:
        st.caption("🧠 Adaptive Mode")

    if st.button("❌ End Quiz", key="end_quiz_btn"):
        run(services.quiz.end, username)
        st.rerun()

    if state.status == "feedback" and state.feedback:
        render_quiz_feedback(state)
        return

    question = state.current_question or {}
    text = question.get("text", "Question not available")
    if "```" in text:
        st.markdown("### Question:")
        st.markdown(text, unsafe_allow_html=False)
    else:
        st.markdown(f"### {text}")

    key = f"{state.quiz_id}_{state.position}"
    qtype = question.get("type", "multiple_choice")
    answer: Optional[str] = None
    if qtype == "multiple_choice":
        options = question.get("options", [])
        if not options:
            st.error("No options available for this question.")
            return
        selected = st.radio("Select your answer:", options, key=f"quiz_mc_{key}")
        if st.button("Submit Answer", type="primary", disabled=not selected, key=f"submit_mc_{key}"):
            answer = selected
    elif qtype == "true_false":
        st.write("Choose True or False:")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("✅ True", use_container_width=True, type="primary", key=f"true_btn_{key}"):
                answer = "True"
        with col2:
            if st.button("❌ False", use_container_width=True, key=f"false_btn_{key}"):
                answer = "False"
    elif qtype == "fill_in_blank":
        typed = st.text_input("Your answer:", key=f"quiz_fill_{key}")
        if st.button("Submit Answer", type="primary", disabled=not typed.strip(), key=f"submit_fill_{key}"):
            answer = typed
    else:  # open_ended
        st.write("Type your answer below:")
        typed = st.text_area("Your answer:", height=120, key=f"quiz_open_{key}")
        chars = len(typed.strip())
        st.caption(f"Character count: {chars}")
        min_chars = 10
        if st.button("Submit Answer", type="primary", disabled=chars < min_chars, key=f"submit_open_{key}"):
            answer = typed
        if chars < min_chars:
            st.warning(f"Please write at least {min_chars} characters. You have {chars}.")

    if answer is not None:
        with st.spinner("Checking your answer..."):
            result = run(services.quiz.answer, username, answer)
        if result is not None:
            for achievement in result.feedback.achievements if result.feedback else []:
                flash("toast", f"🎉 {achievement}")
            st.rerun()


def render_quiz_feedback(state) -> None:
    feedback = state.feedback
    if feedback.correct is None:
        st.warning(f"⚠️ {feedback.explanation}")
    elif feedback.correct:
        st.success(f"✅ Correct! {feedback.explanation}")
    else:
        st.error(f"❌ Incorrect. {feedback.explanation}")
    if st.button("Continue", type="primary", key="continue_btn"):
        with st.spinner("Preparing the next question..."):
            run(get_services().quiz.next, st.session_state.username)
        st.rerun()


def render_quiz_results(state) -> None:
    """Quiz results (answers that couldn't be graded are left out of the score)."""
    total, correct = state.graded_count, state.correct_count
    accuracy = correct / total * 100 if total else 0
    ungraded = len(state.results) - total
    st.balloons()
    st.success(f"🎉 Quiz Complete! Score: {correct}/{total} ({accuracy:.1f}%)")
    if ungraded:
        st.caption(f"{ungraded} answer(s) couldn't be graded and aren't included.")
    col1, col2, col3 = st.columns(3)
    col1.metric("Questions", total)
    col2.metric("Correct", correct)
    col3.metric("Accuracy", f"{accuracy:.1f}%")
    if accuracy >= 90:
        st.success("🌟 Excellent work!")
    elif accuracy >= 75:
        st.info("👍 Good job!")
    elif accuracy >= 60:
        st.warning("📚 Room for improvement.")
    else:
        st.error("🤔 More study needed.")


# ============================================================================ entry point


def main() -> None:
    # Check configuration once per browser session and say exactly what is missing.
    if not st.session_state.get("config_ok"):
        problems = check_configuration()
        if problems:
            st.error("LEA can't start until these settings are fixed (then restart LEA):")
            for problem in problems:
                st.error(problem)
            st.stop()
        st.session_state["config_ok"] = True

    initialize_session_state()
    try:
        get_services()
    except Exception:
        logger.exception("LEA services failed to start")
        st.error("⚠️ LEA couldn't start. The console log names the cause.")
        st.stop()

    if not st.session_state.authenticated:
        render_login_page()
    else:
        render_sidebar()
        render_main_content()


if __name__ == "__main__":
    main()
