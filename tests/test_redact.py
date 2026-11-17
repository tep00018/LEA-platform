"""Secrets never leave LEA in error messages or logs (the YouTube API key leak).

A failed Google API call raises an error whose text is the whole request URL, key included.
LEA returned that text and logged it. Every key below is made up.
"""

import logging
import threading

import pytest

from src.core.redact import REDACTED, install_log_redaction, redact, uninstall_log_redaction

FAKE_GOOGLE = "AIza" + "x" * 35
FAKE_OPENAI = "sk-" + "y" * 40
FAKE_TOKEN = "tok" + "1" * 6 + "z" * 8  # built at runtime so no scanner sees a secret-shaped literal
YOUTUBE_ERROR = (f'<HttpError 429 when requesting https://youtube.googleapis.com/youtube/v3/search?q=Weak+AI'
                 f'&part=id%2Csnippet&maxResults=6&type=video&key={FAKE_GOOGLE}&alt=json returned "Quota exceeded '
                 f'for quota metric \'Search Queries\'.". Details: "[]">')


def test_the_key_in_a_google_error_url_is_removed_and_the_rest_kept():
    out = redact(YOUTUBE_ERROR)
    assert FAKE_GOOGLE not in out and "key=" + REDACTED + "&alt=json" in out
    assert "HttpError 429" in out and "Quota exceeded" in out and "q=Weak+AI" in out  # still diagnosable


@pytest.mark.parametrize("text,secret", [
    (f"GET https://api.example.com/x?api_key={FAKE_OPENAI}&y=1", FAKE_OPENAI),
    (f"GET https://api.example.com/x?y=1&access_token={FAKE_TOKEN}", FAKE_TOKEN),
    (f"key was {FAKE_GOOGLE} in the message", FAKE_GOOGLE),
    (f"header Authorization: Bearer {'z' * 30}", "z" * 30),
    (f"OpenAI said your key {FAKE_OPENAI} is invalid", FAKE_OPENAI),
    ("connecting to redis://default:S3cretPassw0rd@redis-1.example.com:6379/0", "S3cretPassw0rd"),
    ("connecting to rediss://:S3cretPassw0rd@redis-1.example.com:6379", "S3cretPassw0rd"),
])
def test_each_kind_of_secret_is_removed(text, secret):
    out = redact(text)
    assert secret not in out and REDACTED in out


def test_ordinary_text_is_unchanged_and_redaction_is_idempotent():
    for text in ("The Turing Test proposed in 1950", "https://www.youtube.com/watch?v=abc123", "key concept: weak AI",
                 "redis://localhost:6379", "user token count is 12", ""):
        assert redact(text) == text
    once = redact(YOUTUBE_ERROR)
    assert redact(once) == once


@pytest.fixture
def redacting():
    install_log_redaction()
    install_log_redaction()  # idempotent
    yield
    uninstall_log_redaction()


def test_every_log_record_is_cleaned_message_arguments_and_traceback(redacting, caplog):
    logger = logging.getLogger("tests.redact")
    with caplog.at_level(logging.INFO, logger="tests.redact"):
        logger.warning(f"YouTube search returned no videos: {{'error': '{YOUTUBE_ERROR}'}}")
        logger.info("lazy argument: %s", YOUTUBE_ERROR)
        try:
            raise RuntimeError(YOUTUBE_ERROR)
        except RuntimeError as e:
            logger.error(f"YouTube help retrieval failed: {e}", exc_info=True)
        logger.info("no secret here: %s and %d", "value", 3)
    assert FAKE_GOOGLE not in caplog.text and REDACTED in caplog.text
    assert "Traceback" in caplog.text and "RuntimeError" in caplog.text  # the traceback is still there
    assert "no secret here: value and 3" in caplog.text  # ordinary records are untouched


def test_the_youtube_tool_never_returns_the_key(redacting, caplog):
    """The tool's error result is what LEA returned and logged; it now carries no key."""
    from src.mcp.tool_registry import MCPToolRegistry

    class Broken:
        def search(self):
            raise RuntimeError(YOUTUBE_ERROR)

    tool = object.__new__(MCPToolRegistry)
    tool.youtube, tool._youtube_lock = Broken(), threading.Lock()
    result = tool._handle_youtube_search({"topic": "Weak AI", "subject_area": "AIML101"})
    assert result["success"] is False and "YouTube search failed" in result["error"]
    assert FAKE_GOOGLE not in str(result) and "Quota exceeded" in result["error"]
    assert result["fallback_url"].startswith("https://www.youtube.com/results?search_query=")
    with caplog.at_level(logging.WARNING):
        logging.getLogger("src.tutor.simple_tutor_system").warning(f"YouTube search returned no videos: {result}")
    assert FAKE_GOOGLE not in caplog.text


def test_building_the_services_installs_the_redaction(services):
    """The API and the app get it through build_services, so it doesn't depend on who logs."""
    record = logging.getLogger("tests.redact.services").makeRecord(
        "tests.redact.services", logging.ERROR, __file__, 1, f"boom {FAKE_GOOGLE}", None, None)
    assert FAKE_GOOGLE not in record.getMessage()
