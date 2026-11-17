"""Instructor-curated videos: link parsing, the service's rules, and the Teacher API."""

import json

import pytest

from src.services.errors import InvalidInput, NotFound, Unavailable
from src.services.videos import MAX_NOTE, MAX_PER_OBJECTIVE, VideoService, oembed, parse_video_id
from tests.test_api import register_and_login

COURSE = "DEMO101"
GO = "GO_01_01_001"
IDS = [f"vid{i:08d}" for i in range(8)]  # YouTube IDs are 11 characters


def fake_fetch(video_id):
    return {"title": f"Title of {video_id}", "channel": "A Channel"}


@pytest.fixture(autouse=True)
def clean_files(services):
    """The test data folder is shared by the whole session: start and finish with no lists."""
    services.videos.fetch = fake_fetch
    services.videos.path(COURSE).unlink(missing_ok=True)
    yield
    services.videos.path(COURSE).unlink(missing_ok=True)


@pytest.fixture
def teacher(client, services):
    username, headers = register_and_login(client)
    services.redis_client.get_redis().hset(f"user:{username}", "role", "teacher")
    services.staff.add_owner("admin", COURSE, username)
    return username, headers


# ---------------------------------------------------------------------------- links


@pytest.mark.parametrize("url,expected", [
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://youtube.com/watch?v=dQw4w9WgXcQ&t=90s&list=PL123", "dQw4w9WgXcQ"),
    ("http://m.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://youtu.be/dQw4w9WgXcQ?t=42", "dQw4w9WgXcQ"),
    ("youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://www.youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("  https://www.youtube.com/live/dQw4w9WgXcQ  ", "dQw4w9WgXcQ"),
])
def test_every_kind_of_video_link_gives_the_video_id(url, expected):
    assert parse_video_id(url) == expected


@pytest.mark.parametrize("url", [
    "", "   ", "not a link", "https://vimeo.com/12345678901", "https://example.com/watch?v=dQw4w9WgXcQ",
    "https://evil.com/?u=https://www.youtube.com/watch?v=dQw4w9WgXcQ", "https://www.youtube.com/watch",
    "https://www.youtube.com/watch?v=short", "https://www.youtube.com/playlist?list=PL12345678901",
    "https://www.youtube.com/@channel", "javascript:alert(1)", "ftp://youtube.com/watch?v=dQw4w9WgXcQ",
    "https://www.youtube.com.evil.com/watch?v=dQw4w9WgXcQ",
])
def test_anything_else_is_refused_with_a_plain_message(url):
    with pytest.raises(InvalidInput) as e:
        parse_video_id(url)
    assert "YouTube" in str(e.value) or "video" in str(e.value)


def test_oembed_maps_youtube_answers_to_plain_errors(monkeypatch):
    import io
    import urllib.request

    def fail(code):
        def opener(request, timeout):
            raise urllib.error.HTTPError(request.full_url, code, "x", {}, io.BytesIO(b""))
        return opener

    monkeypatch.setattr(urllib.request, "urlopen", fail(404))
    with pytest.raises(InvalidInput, match="private, removed"):
        oembed("dQw4w9WgXcQ")
    monkeypatch.setattr(urllib.request, "urlopen", fail(500))
    with pytest.raises(Unavailable):
        oembed("dQw4w9WgXcQ")
    monkeypatch.setattr(urllib.request, "urlopen", lambda r, timeout: (_ for _ in ()).throw(OSError("offline")))
    with pytest.raises(Unavailable, match="reach YouTube"):
        oembed("dQw4w9WgXcQ")


# ---------------------------------------------------------------------------- the service


def test_adding_checks_the_video_and_keeps_the_title_note_and_who_added_it(services):
    video = services.videos.add("teacher1", COURSE, GO, f"https://youtu.be/{IDS[0]}", "  Watch   from 3:20 ")
    assert video["id"] == IDS[0] and video["url"] == f"https://www.youtube.com/watch?v={IDS[0]}"
    assert video["title"] == f"Title of {IDS[0]}" and video["channel"] == "A Channel"
    assert video["note"] == "Watch from 3:20" and video["added_by"] == "teacher1" and video["added_at"]
    assert services.videos.curated(COURSE, GO) == [video]
    assert services.videos.curated(COURSE, "GO_99_99_999") == [] and services.videos.curated(COURSE, None) == []


def test_the_rules(services):
    add = lambda i, **kw: services.videos.add("t", COURSE, kw.pop("go", GO), f"https://youtu.be/{IDS[i]}", **kw)  # noqa: E731
    add(0)
    with pytest.raises(InvalidInput, match="already"):
        add(0)
    with pytest.raises(NotFound, match="objective"):
        add(1, go="GO_99_99_999")
    with pytest.raises(InvalidInput, match="characters"):
        add(1, note="x" * (MAX_NOTE + 1))
    for i in range(1, MAX_PER_OBJECTIVE):
        add(i)
    with pytest.raises(InvalidInput, match=f"up to {MAX_PER_OBJECTIVE}"):
        add(MAX_PER_OBJECTIVE)
    assert len(services.videos.curated(COURSE, GO)) == MAX_PER_OBJECTIVE


def test_a_video_youtube_will_not_show_is_refused_and_nothing_is_saved(services):
    def refuse(video_id):
        raise InvalidInput("YouTube can't show that video")

    services.videos.fetch = refuse
    with pytest.raises(InvalidInput):
        services.videos.add("t", COURSE, GO, f"https://youtu.be/{IDS[0]}")
    assert services.videos.curated(COURSE, GO) == [] and not services.videos.path(COURSE).exists()


def test_remove_and_reorder_and_the_list_survives_a_new_service(services):
    for i in range(3):
        services.videos.add("t", COURSE, GO, f"https://youtu.be/{IDS[i]}")
    order = lambda: [v["id"] for v in services.videos.curated(COURSE, GO)]  # noqa: E731
    services.videos.move("t", COURSE, GO, IDS[2], -1)
    assert order() == [IDS[0], IDS[2], IDS[1]]
    services.videos.move("t", COURSE, GO, IDS[0], -1)  # already first: unchanged
    services.videos.move("t", COURSE, GO, IDS[1], 1)  # already last: unchanged
    assert order() == [IDS[0], IDS[2], IDS[1]]
    again = VideoService(services.registry, services.events, services.redis_client, fetch=fake_fetch)
    assert [v["id"] for v in again.curated(COURSE, GO)] == order()  # read from the file
    services.videos.remove("t", COURSE, GO, IDS[2])
    assert order() == [IDS[0], IDS[1]]
    with pytest.raises(NotFound):
        services.videos.remove("t", COURSE, GO, IDS[2])
    services.videos.remove("t", COURSE, GO, IDS[0])
    services.videos.remove("t", COURSE, GO, IDS[1])
    assert GO not in json.loads(services.videos.path(COURSE).read_text())["objectives"]  # an empty list is dropped


def test_every_change_is_a_logged_teacher_action(services):
    services.videos.add("teacher1", COURSE, GO, f"https://youtu.be/{IDS[0]}", "a note")
    services.videos.add("teacher1", COURSE, GO, f"https://youtu.be/{IDS[1]}")
    services.videos.move("teacher1", COURSE, GO, IDS[1], -1)
    services.videos.remove("teacher1", COURSE, GO, IDS[0])
    rows = services.events.log.query("actor = 'teacher1' AND type LIKE 'video_%'")
    assert [r["type"] for r in rows] == ["video_add", "video_add", "video_reorder", "video_remove"]
    first = json.loads(rows[0]["payload_json"])
    assert first == {"go_id": GO, "video_id": IDS[0], "has_note": True, "videos_now": 1}
    assert all(r["course"] == COURSE for r in rows)


# ---------------------------------------------------------------------------- the Teacher API


def test_a_teacher_curates_videos_through_the_api(client, teacher, services):
    _, headers = teacher
    base = f"/teach/courses/{COURSE}/videos"
    overview = client.get(base, headers=headers).json()
    assert overview["course"] == COURSE and overview["curated_objectives"] == 0
    assert overview["max_per_objective"] == MAX_PER_OBJECTIVE and overview["objectives"]
    assert overview["search"]["enabled"] is False and overview["search"]["quota_paused_until"] is None
    weeks = {o["week"] for o in overview["objectives"]}
    assert weeks == {1, 2, 3} or min(weeks) == 1  # grouped for the screen by week

    r = client.post(base, json={"go_id": GO, "url": f"https://youtu.be/{IDS[0]}", "note": "Watch from 3:20"},
                    headers=headers)
    assert r.status_code == 201, r.text
    assert r.json()["title"] == f"Title of {IDS[0]}" and r.json()["note"] == "Watch from 3:20"
    client.post(base, json={"go_id": GO, "url": f"https://youtu.be/{IDS[1]}"}, headers=headers)
    listed = client.get(base, headers=headers).json()
    entry = next(o for o in listed["objectives"] if o["go_id"] == GO)
    assert [v["id"] for v in entry["videos"]] == IDS[:2] and listed["curated_objectives"] == 1

    moved = client.post(f"{base}/{GO}/{IDS[1]}/move", json={"direction": "up"}, headers=headers)
    assert moved.status_code == 200 and [v["id"] for v in moved.json()] == [IDS[1], IDS[0]]
    assert client.delete(f"{base}/{GO}/{IDS[1]}", headers=headers).status_code == 204
    assert client.delete(f"{base}/{GO}/{IDS[1]}", headers=headers).status_code == 404
    assert [v["id"] for v in services.videos.curated(COURSE, GO)] == [IDS[0]]


def test_the_api_says_plainly_what_is_wrong(client, teacher):
    _, headers = teacher
    base = f"/teach/courses/{COURSE}/videos"
    for body, status, word in [
            ({"go_id": GO, "url": "https://vimeo.com/123"}, 400, "YouTube"),
            ({"go_id": "GO_99_99_999", "url": f"https://youtu.be/{IDS[0]}"}, 404, "objective"),
            ({"go_id": GO, "url": f"https://youtu.be/{IDS[0]}", "note": "x" * 300}, 400, "characters")]:
        r = client.post(base, json=body, headers=headers)
        assert r.status_code == status and word in r.text, (body, r.text)
    assert client.post(base, json={"go_id": GO}, headers=headers).status_code == 422


def test_students_and_other_teachers_cannot_see_or_change_the_lists(client, teacher, services):
    student, student_headers = register_and_login(client)
    other, other_headers = register_and_login(client)
    services.redis_client.get_redis().hset(f"user:{other}", "role", "teacher")  # a teacher, but not of this course
    base = f"/teach/courses/{COURSE}/videos"
    body = {"go_id": GO, "url": f"https://youtu.be/{IDS[0]}"}
    for headers in (student_headers, other_headers):
        assert client.get(base, headers=headers).status_code == 403
        assert client.post(base, json=body, headers=headers).status_code == 403
        assert client.delete(f"{base}/{GO}/{IDS[0]}", headers=headers).status_code == 403
        assert client.post(f"{base}/{GO}/{IDS[0]}/move", json={"direction": "up"}, headers=headers).status_code == 403
    assert client.get(base).status_code in (401, 403)
    assert services.videos.curated(COURSE, GO) == []


# ---------------------------------------------------------------------------- help shown, and what a student gets


def shown(services, go, students, *, kind="real", mode="tutor", flag=True, days_ago=1, actor=None):
    """One tutor answer that showed (or didn't show) video help, for each of ``students``."""
    from datetime import datetime, timedelta, timezone

    ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat(timespec="milliseconds")
    for name in students:
        services.events.log.append(type="answer", session_kind=kind, course=COURSE, mode=mode, go_id=go,
                                   username_hash=f"h-{name}", ts=ts, actor=actor, payload={"youtube_shown": flag})


def by_go(services):
    return {o["go_id"]: o for o in services.videos.overview(COURSE)["objectives"]}


def test_help_shown_counts_real_students_and_withholds_small_numbers(services):
    ids = [o["go_id"] for o in services.videos.overview(COURSE)["objectives"]]
    many, few, one, nobody = ids[0], ids[1], ids[2], ids[3]
    shown(services, many, [f"s{i}" for i in range(6)])
    shown(services, many, ["s0", "s1"])  # the same students again: counted once per student
    shown(services, few, ["a", "b", "c"])
    shown(services, one, ["a"])
    overview = services.videos.overview(COURSE)
    goes = {o["go_id"]: o["help_shown_students"] for o in overview["objectives"]}
    assert goes[many] == 6 and goes[few] is None and goes[one] is None and goes[nobody] == 0  # 1-4 students: withheld
    assert overview["help_window_days"] == 30 and overview["help_shown_times"] == 6 + 2 + 3 + 1


def test_help_shown_leaves_out_everything_that_is_not_a_real_student_in_the_window(services):
    go = services.videos.overview(COURSE)["objectives"][0]["go_id"]
    people = [f"s{i}" for i in range(6)]
    shown(services, go, people, kind="test")  # a teacher's preview or a test account
    shown(services, go, people, kind="simulated")
    shown(services, go, people, days_ago=40)  # too long ago
    shown(services, go, people, mode="quiz")
    shown(services, go, people, flag=False)  # help was not shown
    shown(services, go, people, actor="teacher1")  # a staff action
    overview = services.videos.overview(COURSE)
    assert by_go(services)[go]["help_shown_students"] == 0 and overview["help_shown_times"] == 0
    shown(services, go, people)  # now real students in the window
    assert by_go(services)[go]["help_shown_students"] == 6


def test_the_overall_count_is_withheld_when_fewer_than_five_students_are_behind_it(services):
    go = services.videos.overview(COURSE)["objectives"][0]["go_id"]
    assert services.videos.overview(COURSE)["help_shown_times"] == 0  # nobody: zero reveals no one
    shown(services, go, ["a", "b", "c"])
    assert services.videos.overview(COURSE)["help_shown_times"] is None
    shown(services, go, ["d", "e"])
    assert services.videos.overview(COURSE)["help_shown_times"] == 5


def test_what_a_stuck_student_gets_for_each_objective(services, monkeypatch):
    from src.mcp.youtube_cache import YouTubeSearchCache

    first, second = [o["go_id"] for o in services.videos.overview(COURSE)["objectives"][:2]]
    services.videos.add("t", COURSE, first, f"https://youtu.be/{IDS[0]}")
    monkeypatch.setenv("YOUTUBE_API_KEY", "")
    assert by_go(services)[first]["student_gets"] == "curated" and by_go(services)[second]["student_gets"] == "links"
    monkeypatch.setenv("YOUTUBE_API_KEY", "a-key-is-set")
    assert by_go(services)[second]["student_gets"] == "search" and by_go(services)[first]["student_gets"] == "curated"
    YouTubeSearchCache(services.redis_client).pause_for_quota()
    try:
        overview = services.videos.overview(COURSE)
        assert overview["search"]["quota_paused_until"] and by_go(services)[second]["student_gets"] == "links"
    finally:
        YouTubeSearchCache(services.redis_client).resume()


def test_the_api_returns_the_new_fields(client, teacher, services):
    _, headers = teacher
    go = services.videos.overview(COURSE)["objectives"][0]["go_id"]
    shown(services, go, [f"s{i}" for i in range(5)])
    body = client.get(f"/teach/courses/{COURSE}/videos", headers=headers).json()
    entry = next(o for o in body["objectives"] if o["go_id"] == go)
    assert entry["help_shown_students"] == 5 and entry["student_gets"] in ("curated", "search", "links")
    assert body["help_shown_times"] == 5 and body["help_window_days"] == 30
