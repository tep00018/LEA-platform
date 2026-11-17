"""YouTube help: cached searches, a pause when Google's quota runs out, video help once per
stuck streak, and an instructor's curated videos preferred over any search."""

import json
import logging
import threading
from datetime import datetime, timezone

import pytest

from src.mcp.tool_registry import MCPToolRegistry
from src.mcp.youtube_cache import (FAILURE_TTL_SECONDS, QUOTA_KEY, YouTubeSearchCache, is_quota_error,
                                   seconds_until_quota_reset)
from tests.test_acceptance_phase1 import question_writer

COURSE = "DEMO101"
QUOTA_ERROR = ('<HttpError 403 when requesting https://youtube.googleapis.com/youtube/v3/search?q=x&key=K returned '
               '"The request cannot be completed because you have exceeded your quota.". Details: '
               '"[{\'reason\': \'quotaExceeded\'}]">')


class FakeYouTube:
    """A stand-in for the Google client that counts the calls it costs."""

    def __init__(self, error=None):
        self.error, self.searches, self.stats = error, 0, 0

    def search(self):
        outer = self

        class _S:
            def list(self, **kw):
                outer.searches += 1
                return self

            def execute(self):
                if outer.error:
                    raise RuntimeError(outer.error)
                return {"items": [{"id": {"videoId": f"vid{i:08d}"}, "snippet": {
                    "title": f"Video {i}", "channelTitle": "Channel", "description": "d", "publishedAt": "2024-01-01T00"}}
                    for i in range(3)]}
        return _S()

    def videos(self):
        outer = self

        class _V:
            def list(self, **kw):
                outer.stats += 1
                return self

            def execute(self):
                return {"items": [{"id": f"vid{i:08d}", "statistics": {"viewCount": str(100 - i)}} for i in range(3)]}
        return _V()


def tool(youtube, redis_client):
    t = object.__new__(MCPToolRegistry)
    t.youtube, t._youtube_lock, t.redis_client = youtube, threading.Lock(), redis_client
    return t


def search(t, topic):
    return t._handle_youtube_search({"topic": topic, "subject_area": "DEMO101"})


@pytest.fixture
def clean(lea_redis):
    conn = lea_redis.get_redis()
    for key in list(conn.scan_iter(match="youtube:*")):
        conn.delete(key)
    return lea_redis


# ---------------------------------------------------------------------------- the cache


def test_the_same_objective_is_searched_once_however_many_students_ask(clean):
    api = FakeYouTube()
    t = tool(api, clean)
    first, second, third = search(t, "Weak AI"), search(t, "Weak AI"), search(t, "Weak AI")
    assert (first["source"], second["source"], third["source"]) == ("api", "cache", "cache")
    assert api.searches == 1 and api.stats == 1  # 101 quota units, once
    assert [v["title"] for v in second["videos"]] == [v["title"] for v in first["videos"]]
    search(t, "Turing test")
    assert api.searches == 2  # another objective is a new search
    assert YouTubeSearchCache(clean).status()["cached_searches"] == 2


def test_a_quota_error_pauses_every_search_until_the_reset_but_cached_ones_still_work(clean):
    good, broken = FakeYouTube(), FakeYouTube(QUOTA_ERROR)
    search(tool(good, clean), "Weak AI")  # cached before the quota ran out
    t = tool(broken, clean)
    failed = search(t, "Turing test")
    assert failed["success"] is False and "quota" in failed["error"].lower()
    until = YouTubeSearchCache(clean).quota_paused_until()
    assert until and 0 < until - datetime.now(timezone.utc).timestamp() <= 25 * 3600
    assert broken.searches == 1
    paused = search(t, "Neural networks")  # a different objective: not sent to Google at all
    assert paused["success"] is False and paused["paused"] is True and broken.searches == 1
    assert "search_query=" in paused["fallback_url"]
    assert search(t, "Weak AI")["source"] == "cache"  # already cached: still served
    assert YouTubeSearchCache(clean).status()["quota_paused_until"]
    YouTubeSearchCache(clean).resume()
    search(t, "Neural networks")
    assert broken.searches == 2  # searching again after the pause is lifted


def test_other_failures_are_not_retried_on_every_reply(clean):
    api = FakeYouTube("HTTP 400: bad request for this query")
    t = tool(api, clean)
    assert search(t, "Odd topic")["success"] is False and api.searches == 1
    again = search(t, "Odd topic")
    assert again["success"] is False and again["paused"] is True and api.searches == 1
    search(t, "Another topic")
    assert api.searches == 2  # only that query is remembered as failed
    assert clean.get_redis().ttl(next(iter(clean.get_redis().scan_iter(match="youtube:failed:*")))) \
        <= FAILURE_TTL_SECONDS


def test_without_redis_every_search_goes_to_google_as_before():
    api = FakeYouTube()
    t = tool(api, None)
    assert search(t, "Weak AI")["source"] == "api" and search(t, "Weak AI")["source"] == "api" and api.searches == 2


def test_no_key_still_gives_a_search_link_and_never_touches_the_cache(clean):
    result = search(tool(None, clean), "Weak AI")
    assert result["source"] == "search-link" and "results?search_query=" in result["videos"][0]["url"]
    assert not list(clean.get_redis().scan_iter(match="youtube:*"))


def test_quota_errors_are_told_from_other_errors_and_the_reset_is_pacific_midnight():
    assert is_quota_error(QUOTA_ERROR) and is_quota_error("HttpError 429 when requesting") and \
        is_quota_error("Quota exceeded for quota metric 'Search Queries'")
    assert not is_quota_error("HTTP 400: invalid videoDuration") and not is_quota_error("Connection reset")
    just_before = datetime(2026, 9, 26, 6, 59, tzinfo=timezone.utc)  # 23:59 Pacific (daylight time)
    assert seconds_until_quota_reset(just_before) == 60  # the minimum
    assert 22 * 3600 < seconds_until_quota_reset(datetime(2026, 9, 26, 8, 0, tzinfo=timezone.utc)) < 24 * 3600
    assert QUOTA_KEY.startswith("youtube:")


# ---------------------------------------------------------------------------- the tutor


def drive(services, username, replies):
    """Send replies to the tutor; returns [(streak after the reply, video block shown, help source)]."""
    services.tutor.start(username, COURSE, 1)
    seen = []
    for text in replies:
        reply = services.tutor.respond(username, text)
        payload = json.loads(services.events.log.query("type = 'answer' AND mode = 'tutor'")[-1]["payload_json"])
        seen.append((reply.state.session.consecutive_incorrect, "Video Resources" in reply.message,
                     payload.get("youtube_source"), reply.message))
    return seen


@pytest.fixture
def svc(services, fake_llm, monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "")  # never a real search from a test
    fake_llm._responder = lambda m: (
        question_writer(m) if ("Return JSON" in m[-1]["content"] or "<answer>" in m[-1]["content"]
                               or "JSON" in m[0]["content"]) else "Tutor says: what is AI?")
    services.videos.path(COURSE).unlink(missing_ok=True)  # the test data folder is shared by the whole session
    yield services
    services.videos.path(COURSE).unlink(missing_ok=True)


def test_video_help_appears_once_per_stuck_streak_not_on_every_wrong_reply(svc, username):
    wrong, right = "WRONG answer, I have no idea", "RIGHT answer: it is about machines that learn"
    seen = drive(svc, username, ["diagnostic answer", wrong, wrong, wrong, wrong, wrong, right, wrong, wrong, wrong])
    by_streak = [(streak, shown) for streak, shown, _, _ in seen]
    assert (3, True) in by_streak
    assert all(not shown for streak, shown in by_streak if streak != 3)  # 1, 2, 4, 5 and after a correct one: none
    first_stuck = next(i for i, (s, shown) in enumerate(by_streak) if s == 3)
    assert [s for s, _ in by_streak[first_stuck:first_stuck + 3]] == [3, 4, 5]
    assert sum(1 for _, shown in by_streak[first_stuck:first_stuck + 3] if shown) == 1
    later = [shown for streak, shown in by_streak[first_stuck + 3:] if streak == 3]
    assert later == [True]  # after a correct answer, a new streak of three gets help again


def test_curated_videos_are_preferred_in_the_instructors_order_with_their_notes(svc, username):
    svc.videos.fetch = lambda vid: {"title": f"Lesson {vid}", "channel": "Prof"}
    for go in (g["go_id"] for g in svc.courses.week_objectives(COURSE, 1)):
        for i, note in enumerate(["Watch from 3:20", "", "The proof", "Extra"]):
            svc.videos.add("teacher1", COURSE, go, f"https://youtu.be/cur{i:08d}", note)
    calls = []
    server = svc.tutor.tutor_system.mcp_client.mcp_server
    original = server.handle_tool_request
    server.handle_tool_request = lambda req: (calls.append(req.get("tool")), original(req))[1]
    wrong = "WRONG answer, I have no idea"
    seen = drive(svc, username, ["diagnostic answer", wrong, wrong])
    streak, shown, source, message = seen[-1]
    assert streak == 3 and shown and source == "curated"
    assert "youtube_worked_examples" not in calls  # no search, so no quota
    assert message.index("Lesson cur00000000") < message.index("Lesson cur00000001")
    assert "Watch from 3:20" in message and "The proof" in message
    assert "Lesson cur00000003" not in message  # three are shown; the fourth waits


def test_without_curated_videos_the_automatic_help_is_used_and_its_source_recorded(svc, username):
    wrong = "WRONG answer, I have no idea"
    seen = drive(svc, username, ["diagnostic answer", wrong, wrong])
    assert seen[-1][1] and seen[-1][2] == "search:search-link"  # no API key in tests: a search link


def test_a_failing_curated_lookup_falls_back_instead_of_breaking_the_reply(svc, username, caplog):
    svc.tutor.tutor_system.curated_videos = lambda course, go: (_ for _ in ()).throw(RuntimeError("disk error"))
    wrong = "WRONG answer, I have no idea"
    with caplog.at_level(logging.WARNING):
        seen = drive(svc, username, ["diagnostic answer", wrong, wrong])
    assert seen[-1][1] and seen[-1][2].startswith("search") and "Curated videos couldn't be read" in caplog.text
