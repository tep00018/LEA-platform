"""The startup check names the setting that is wrong."""

from src.config_check import check_configuration


def test_ok_configuration(redis_url):
    assert check_configuration(redis_url=redis_url, openai_key="sk-proj-abc") == []


def test_missing_openai_key_is_named(redis_url):
    problems = check_configuration(redis_url=redis_url, openai_key="")
    assert len(problems) == 1 and "OPENAI_API_KEY" in problems[0]


def test_template_openai_key_counts_as_missing(redis_url):
    assert "OPENAI_API_KEY" in check_configuration(redis_url=redis_url, openai_key="sk-your-key-here")[0]


def test_missing_redis_url_is_named():
    problems = check_configuration(redis_url="", openai_key="sk-proj-abc")
    assert len(problems) == 1 and "REDIS_URL" in problems[0]


def test_unreachable_redis_is_explained_without_leaking_the_password():
    problems = check_configuration(redis_url="redis://default:hunter2@127.0.0.1:1", openai_key="sk-proj-abc")
    assert len(problems) == 1 and "Cannot connect to Redis" in problems[0]
    assert "hunter2" not in problems[0]
