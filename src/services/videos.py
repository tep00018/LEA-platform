"""Videos an instructor has chosen for an objective, shown by the tutor instead of an
automatic YouTube search.

When a student is stuck (three wrong answers in a row on an objective) the tutor adds a
short list of videos to its reply. If the instructor has curated videos for that objective
they are used, in the instructor's order and with their notes ("watch from 3:20"); with none,
the tutor falls back to a cached automatic search (``src/mcp/youtube_cache.py``), and then to
plain search links.

Storage is one file per course, ``data/course_videos/<CODE>.json`` (gitignored: private
courses stay private), keyed by granular-objective ID. GO IDs never change once published,
so a list stays attached to its objective through later KC versions; an objective that has
been retired keeps its list but is no longer shown.

Adding a video checks it with YouTube's public oEmbed endpoint (no API key, no quota): the
video must exist and be public. That also fills in the title and channel. Only teachers who
own the course (and admins) can change a list; every change goes to the event log as a
teacher action.
"""

from __future__ import annotations

import json
import os
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from src.mcp.youtube_cache import YouTubeSearchCache
from src.onboarding.analytics_compute import MIN_STUDENTS
from src.onboarding import kc_model as K
from src.services.errors import InvalidInput, NotFound, Unavailable
from src.services.events import EventRecorder, disabled

MAX_PER_OBJECTIVE = 5
MAX_NOTE = 200
HELP_WINDOW_DAYS = 30
VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be", "www.youtu.be"}


def parse_video_id(url: str) -> str:
    """The 11-character video ID in a YouTube link (watch, youtu.be, embed, shorts or live)."""
    text = (url or "").strip()
    if not text:
        raise InvalidInput("Paste a YouTube video link.")
    if "://" not in text:
        text = "https://" + text
    parsed = urllib.parse.urlparse(text)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or host not in HOSTS:
        raise InvalidInput("That isn't a YouTube link. Paste the address of a video on youtube.com or youtu.be.")
    candidate = None
    if host.endswith("youtu.be"):
        candidate = parsed.path.strip("/").split("/")[0]
    elif parsed.path == "/watch":
        candidate = (urllib.parse.parse_qs(parsed.query).get("v") or [None])[0]
    else:
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) >= 2 and parts[0] in ("embed", "shorts", "live", "v"):
            candidate = parts[1]
    if not candidate or not VIDEO_ID.match(candidate):
        raise InvalidInput("That link doesn't point to a single video. Paste the address of the video itself.")
    return candidate


def watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def oembed(video_id: str) -> Dict[str, str]:
    """Title and channel from YouTube's public oEmbed endpoint. Raises InvalidInput for a video
    that is private, removed or embedding-disabled, and Unavailable if YouTube can't be reached."""
    endpoint = "https://www.youtube.com/oembed?format=json&url=" + urllib.parse.quote(watch_url(video_id), safe="")
    request = urllib.request.Request(endpoint, headers={"User-Agent": "LEA-video-check/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=8) as response:  # noqa: S310 (fixed https host)
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (400, 401, 403, 404):
            raise InvalidInput("YouTube can't show that video: it may be private, removed, age-restricted or "
                               "not allowed to be embedded. Check the link, or choose another video.") from e
        raise Unavailable("YouTube couldn't check that video just now. Try again in a moment.") from e
    except Exception as e:
        raise Unavailable("Couldn't reach YouTube to check that video. Try again in a moment.") from e
    return {"title": str(data.get("title") or "").strip(), "channel": str(data.get("author_name") or "").strip()}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class VideoService:
    def __init__(self, registry, events: Optional[EventRecorder] = None, redis_client=None,
                 fetch: Callable[[str], Dict[str, str]] = oembed):
        self.registry = registry
        self.events = events or disabled()
        self.redis_client = redis_client
        self.fetch = fetch
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ storage
    def path(self, code: str) -> Path:
        return Path(self.registry.data_dir) / "course_videos" / f"{code}.json"

    def _read(self, code: str) -> Dict[str, List[Dict[str, Any]]]:
        path = self.path(code)
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8")).get("objectives", {})
        except (OSError, ValueError):
            return {}

    def _write(self, code: str, objectives: Dict[str, List[Dict[str, Any]]]) -> None:
        path = self.path(code)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"version": 1, "objectives": objectives}, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(path)

    def _model(self, code: str) -> Dict[str, Any]:
        model = self.registry.kc_model(code)
        if not model:
            raise NotFound("This course has no published objectives yet.")
        return model

    # ------------------------------------------------------------------ for the tutor
    def curated(self, course: str, go_id: Optional[str]) -> List[Dict[str, Any]]:
        """The instructor's videos for an objective (empty if none or unknown). No events."""
        if not go_id:
            return []
        return list(self._read(course).get(go_id, []))

    # ------------------------------------------------------------------ for the Teacher area
    def search_status(self) -> Dict[str, Any]:
        cache = YouTubeSearchCache(self.redis_client).status()
        return {"enabled": bool(os.getenv("YOUTUBE_API_KEY")), **cache}

    def help_shown(self, code: str) -> Dict[str, Any]:
        """How often video help was shown to real students in the last ``HELP_WINDOW_DAYS`` days:
        students per objective and the number of times overall, from the event log. Any figure
        based on fewer than ``MIN_STUDENTS`` students is None (withheld), as in Analytics; test
        accounts, previews and simulated learners are never counted."""
        log = getattr(self.events, "log", None)
        empty: Dict[str, Any] = {"by_go": {}, "times": None}
        if log is None:
            return empty
        since = (datetime.now(timezone.utc) - timedelta(days=HELP_WINDOW_DAYS)).isoformat(timespec="seconds")
        try:
            rows = log.query("type = 'answer' AND mode = 'tutor' AND course = ? AND session_kind = 'real' "
                             "AND actor IS NULL AND ts >= ?", [code, since])
        except Exception:
            return empty
        per_go: Dict[str, set] = {}
        everyone, times = set(), 0
        for row in rows:
            try:
                shown = json.loads(row.get("payload_json") or "{}").get("youtube_shown")
            except ValueError:
                continue
            if shown and row.get("go_id"):
                per_go.setdefault(row["go_id"], set()).add(row["username_hash"])
                everyone.add(row["username_hash"])
                times += 1
        return {"by_go": {go: (len(s) if len(s) >= MIN_STUDENTS else None) for go, s in per_go.items()},
                "times": times if len(everyone) >= MIN_STUDENTS else (0 if not everyone else None)}

    def overview(self, code: str) -> Dict[str, Any]:
        """Every objective of the live version with its curated videos, what a stuck student
        gets for it, and how many students were shown help; plus the state of automatic search."""
        curated = self._read(code)
        search = self.search_status()
        help_shown = self.help_shown(code)
        automatic = "search" if search["enabled"] and not search["quota_paused_until"] else "links"
        objectives = []
        for r in K.rows_from_model(self._model(code)):
            videos = curated.get(r["go_id"], [])
            objectives.append({
                "go_id": r["go_id"], "week": int(r["week"]), "lo_id": r["lo_id"], "skill_name": r["skill_name"],
                "videos": videos, "student_gets": "curated" if videos else automatic,
                # 0 when nobody was shown help, None when 1-4 students (withheld), else the count
                "help_shown_students": help_shown["by_go"].get(r["go_id"], 0)})
        return {"course": code, "max_per_objective": MAX_PER_OBJECTIVE, "search": search,
                "help_window_days": HELP_WINDOW_DAYS, "help_shown_times": help_shown["times"],
                "curated_objectives": sum(1 for o in objectives if o["videos"]), "objectives": objectives}

    def add(self, actor: str, code: str, go_id: str, url: str, note: str = "") -> Dict[str, Any]:
        model = self._model(code)
        if go_id not in K.gos_of(model):
            raise NotFound("That objective isn't in the live version of this course.")
        note = " ".join((note or "").split())
        if len(note) > MAX_NOTE:
            raise InvalidInput(f"Keep the note under {MAX_NOTE} characters.")
        video_id = parse_video_id(url)
        with self._lock:
            objectives = self._read(code)
            current = objectives.get(go_id, [])
            if any(v["id"] == video_id for v in current):
                raise InvalidInput("That video is already in this objective's list.")
            if len(current) >= MAX_PER_OBJECTIVE:
                raise InvalidInput(f"An objective can have up to {MAX_PER_OBJECTIVE} videos. Remove one first.")
            details = self.fetch(video_id)
            video = {"id": video_id, "url": watch_url(video_id), "title": details.get("title") or "YouTube video",
                     "channel": details.get("channel", ""), "note": note, "added_by": actor, "added_at": _now()}
            objectives[go_id] = current + [video]
            self._write(code, objectives)
        self.events.staff(actor, "video_add", course=code,
                          payload={"go_id": go_id, "video_id": video_id, "has_note": bool(note),
                                   "videos_now": len(objectives[go_id])})
        return video

    def remove(self, actor: str, code: str, go_id: str, video_id: str) -> None:
        with self._lock:
            objectives = self._read(code)
            current = objectives.get(go_id, [])
            kept = [v for v in current if v["id"] != video_id]
            if len(kept) == len(current):
                raise NotFound("That video isn't in this objective's list.")
            if kept:
                objectives[go_id] = kept
            else:
                objectives.pop(go_id, None)
            self._write(code, objectives)
        self.events.staff(actor, "video_remove", course=code,
                          payload={"go_id": go_id, "video_id": video_id, "videos_now": len(kept)})

    def move(self, actor: str, code: str, go_id: str, video_id: str, direction: int) -> List[Dict[str, Any]]:
        """Move a video up (-1) or down (+1) in an objective's list; the order is the order students see."""
        with self._lock:
            objectives = self._read(code)
            current = objectives.get(go_id, [])
            index = next((i for i, v in enumerate(current) if v["id"] == video_id), None)
            if index is None:
                raise NotFound("That video isn't in this objective's list.")
            target = index + (-1 if direction < 0 else 1)
            if 0 <= target < len(current):
                current[index], current[target] = current[target], current[index]
                objectives[go_id] = current
                self._write(code, objectives)
        self.events.staff(actor, "video_reorder", course=code, payload={"go_id": go_id, "video_id": video_id,
                                                                        "direction": -1 if direction < 0 else 1})
        return current
