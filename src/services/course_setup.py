"""Teacher course setup: create a course, set its weekly objectives, manage its uploads.

A course created here is not visible to students until a KC model is published for it
(B4): ``/courses`` lists only courses with an installed model. Uploads live under
``data/course_uploads/<CODE>/`` (gitignored; private course content is never committed),
with their details in the Redis hash ``course:{code}:uploads``.
"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Dict, List, Optional

from src.core.validation import course_code as valid_course_code
from src.onboarding import files as F
from src.onboarding.materials_source import FolderMaterialsSource, FolderSourceError
from src.services.errors import Busy, InvalidInput, NotFound
from src.services.events import EventRecorder, disabled

DISCIPLINES = ("computing", "mathematics", "science", "engineering", "social_science", "humanities",
               "business", "health", "education", "arts", "other")
MAX_WEEKS = 20
MAX_OBJECTIVES_PER_WEEK = 12


def meta_key(code: str) -> str:
    return f"course:{code}:meta"


def uploads_key(code: str) -> str:
    return f"course:{code}:uploads"


def plan_key(code: str) -> str:
    return f"course:{code}:plan"


class CourseSetupService:
    def __init__(self, redis_client, registry, staff, events: Optional[EventRecorder] = None):
        self.redis_client = redis_client
        self.registry = registry
        self.staff = staff
        self.events = events or disabled()
        self.busy_check = lambda code: False  # set by the job service: a job is using the files

    @property
    def conn(self):
        return self.redis_client.get_redis()

    def uploads_dir(self, code: str) -> Path:
        return Path(self.registry.data_dir) / "course_uploads" / code

    # ------------------------------------------------------------------ courses

    def meta(self, code: str) -> Optional[Dict[str, Any]]:
        raw = self.conn.get(meta_key(code))
        return json.loads(raw) if raw else None

    def managed_courses(self) -> List[str]:
        return sorted(k.split(":")[1] for k in self.conn.scan_iter(match="course:*:meta", count=500))

    def create(self, actor: str, code: str, name: str, discipline: str, allows_code: bool,
               code_language: Optional[str], weeks: int) -> Dict[str, Any]:
        try:
            code = valid_course_code(code)
        except ValueError:
            raise InvalidInput("Course codes are 2-4 letters and 3 digits, like AIML101.") from None
        name = (name or "").strip()
        if not name:
            raise InvalidInput("Give the course a name.")
        if discipline not in DISCIPLINES:
            raise InvalidInput(f"Discipline must be one of: {', '.join(DISCIPLINES)}.")
        if not 1 <= weeks <= MAX_WEEKS:
            raise InvalidInput(f"A course has 1 to {MAX_WEEKS} weeks.")
        language = (code_language or "").strip().lower() or None
        if allows_code and not language:
            raise InvalidInput("Say which programming language code questions use.")
        exists = (self.meta(code) or code in self.registry.available_courses()
                  or (Path(self.registry.data_dir) / "course_profiles" / f"{code}.json").exists())
        meta = {"code": code, "name": name, "discipline": discipline, "allows_code": bool(allows_code),
                "code_language": language if allows_code else None, "weeks": weeks, "created_by": actor,
                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        if exists or not self.conn.set(meta_key(code), json.dumps(meta), nx=True):
            raise InvalidInput(f"{code} already exists. Choose another code.")
        profile = Path(self.registry.data_dir) / "course_profiles" / f"{code}.json"
        profile.parent.mkdir(parents=True, exist_ok=True)
        profile.write_text(json.dumps({k: meta[k] for k in ("code", "name", "discipline", "allows_code",
                                                            "code_language")}, indent=2) + "\n", encoding="utf-8")
        self.registry.forget(code)
        if self.staff.role(actor) == "teacher":
            self.conn.sadd(f"course:{code}:owners", actor)
        self.events.staff(actor, "course_create", course=code, payload={k: meta[k] for k in meta if k != "created_by"})
        return meta

    def require_managed(self, code: str) -> Dict[str, Any]:
        meta = self.meta(code)
        if meta is None:
            raise InvalidInput(f"{code} was set up outside the Teacher area; its files are managed by hand.")
        return meta

    # ------------------------------------------------------------------ weekly objectives

    def plan(self, code: str) -> Optional[Dict[str, Any]]:
        raw = self.conn.get(plan_key(code))
        return json.loads(raw) if raw else None

    def set_plan(self, actor: str, code: str, weeks: List[Dict[str, Any]]) -> Dict[str, Any]:
        meta = self.require_managed(code)
        numbers = sorted(w.get("week") for w in weeks)
        if numbers != list(range(1, meta["weeks"] + 1)):
            raise InvalidInput(f"Give objectives for each of weeks 1 to {meta['weeks']}, once each.")
        clean = []
        for w in sorted(weeks, key=lambda w: w["week"]):
            title = (w.get("title") or "").strip()
            objectives = [" ".join(o.split()) for o in w.get("objectives", []) if o and o.strip()]
            if not title:
                raise InvalidInput(f"Week {w['week']} needs a title.")
            if not 1 <= len(objectives) <= MAX_OBJECTIVES_PER_WEEK:
                raise InvalidInput(f"Week {w['week']} needs 1 to {MAX_OBJECTIVES_PER_WEEK} learning objectives.")
            short = [o for o in objectives if len(o) < 15]
            if short:
                raise InvalidInput(f"Week {w['week']}: write each objective as a full sentence, like "
                                   f"\"Explain how ...\" (\"{short[0]}\" is too short).")
            clean.append({"week": w["week"], "title": title, "objectives": objectives})
        plan = {"weeks": clean, "updated_by": actor, "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        self.conn.set(plan_key(code), json.dumps(plan))
        self.events.staff(actor, "course_set_objectives", course=code,
                          payload={"weeks": len(clean), "objectives": sum(len(w["objectives"]) for w in clean)})
        return plan

    # ------------------------------------------------------------------ uploads

    def uploads(self, code: str) -> Dict[str, Dict[str, Any]]:
        return {name: json.loads(raw) for name, raw in self.conn.hgetall(uploads_key(code)).items()}

    def add_upload(self, actor: str, code: str, filename: str, stream: BinaryIO, week: Optional[int] = None,
                   kind: Optional[str] = None) -> Dict[str, Any]:
        meta = self.require_managed(code)
        if self.busy_check(code):
            raise Busy("A job is using this course's files. Wait for it to finish, or cancel it.")
        try:
            name = F.safe_name(filename)
        except F.UploadRejected as e:
            raise InvalidInput(str(e)) from None
        if week is not None and not 1 <= week <= meta["weeks"]:
            raise InvalidInput(f"{code} has weeks 1 to {meta['weeks']}.")
        if kind is not None and kind not in F.KINDS:
            raise InvalidInput(f"Kind must be one of: {', '.join(F.KINDS)}.")
        existing = self.uploads(code)
        used = sum(u["size"] for n, u in existing.items() if n != name)

        folder = self.uploads_dir(code)
        folder.mkdir(parents=True, exist_ok=True)
        digest, size, head = hashlib.sha256(), 0, b""
        with tempfile.NamedTemporaryFile(dir=folder, prefix=".upload-", delete=False) as tmp:
            try:
                while chunk := stream.read(1024 * 1024):
                    if not head:
                        head = chunk[:4096]
                    size += len(chunk)
                    if size > F.MAX_FILE_BYTES:
                        raise InvalidInput(f"{name} is over {F.MAX_FILE_BYTES // (1024 * 1024)} MB.")
                    if used + size > F.MAX_COURSE_BYTES:
                        raise InvalidInput(f"This would take {code} over its {F.MAX_COURSE_BYTES // (1024 ** 3)} GB "
                                           "of uploads. Delete files it no longer needs.")
                    digest.update(chunk)
                    tmp.write(chunk)
                if size == 0:
                    raise InvalidInput(f"{name} is empty.")
                F.check_content(name, head)
            except (InvalidInput, F.UploadRejected) as e:
                tmp.close()
                Path(tmp.name).unlink(missing_ok=True)
                raise InvalidInput(str(e)) from None
        shutil.move(tmp.name, folder / name)
        record = {"name": name, "size": size, "sha256": digest.hexdigest(), "week": week, "kind": kind,
                  "uploaded_by": actor, "uploaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        self.conn.hset(uploads_key(code), name, json.dumps(record))
        self.events.staff(actor, "upload_add", course=code,
                          payload={"name": name, "size": size, "week": week, "kind": kind, "replaced": name in existing})
        return record

    def delete_upload(self, actor: str, code: str, name: str) -> None:
        self.require_managed(code)
        if self.busy_check(code):
            raise Busy("A job is using this course's files. Wait for it to finish, or cancel it.")
        if not self.conn.hdel(uploads_key(code), name):
            raise NotFound(f"No upload called {name}.")
        (self.uploads_dir(code) / Path(name).name).unlink(missing_ok=True)
        self.events.staff(actor, "upload_delete", course=code, payload={"name": name})

    # ------------------------------------------------------------------ linked materials source

    def _profile_path(self, code: str) -> Path:
        return Path(self.registry.data_dir) / "course_profiles" / f"{code}.json"

    def _source_for(self, code: str) -> Optional[FolderMaterialsSource]:
        link = self.registry.profile(code).materials_source
        if not link or link.get("type") != "folder":
            return None
        try:
            return FolderMaterialsSource(link.get("path", ""))
        except FolderSourceError:
            return None

    def materials_source(self, code: str) -> Optional[Dict[str, Any]]:
        return self.registry.profile(code).materials_source

    def link_materials_source(self, actor: str, code: str, source_type: str, path: str) -> Dict[str, Any]:
        """Record a materials source on the course's profile (owners/admins only, same
        require_managed gate as uploads). Only ``"folder"`` exists today; other types can be
        added later without changing this method's signature or the API shape."""
        self.require_managed(code)
        if source_type != "folder":
            raise InvalidInput("Only a local folder can be linked right now.")
        try:
            FolderMaterialsSource(path)
        except FolderSourceError as e:
            raise InvalidInput(str(e)) from None
        profile_path = self._profile_path(code)
        data = json.loads(profile_path.read_text(encoding="utf-8")) if profile_path.exists() else {"code": code}
        link = {"type": "folder", "path": path}
        data["materials_source"] = link
        profile_path.parent.mkdir(parents=True, exist_ok=True)
        profile_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        self.registry.forget(code)
        self.events.staff(actor, "materials_source_link", course=code, payload=link)
        return link

    def unlink_materials_source(self, actor: str, code: str) -> None:
        """Stop tracking the link. Files already synced into uploads are left as ordinary
        uploads -- unlinking doesn't delete course content, only the connection to its source."""
        self.require_managed(code)
        profile_path = self._profile_path(code)
        if not profile_path.exists():
            return
        data = json.loads(profile_path.read_text(encoding="utf-8"))
        if "materials_source" not in data:
            return
        del data["materials_source"]
        profile_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        self.registry.forget(code)
        self.events.staff(actor, "materials_source_unlink", course=code)

    def _linked_uploads(self, code: str) -> Dict[str, Dict[str, Any]]:
        return {name: u for name, u in self.uploads(code).items() if u.get("linked_relpath")}

    def materials_source_status(self, code: str) -> List[Dict[str, Any]]:
        """One entry per candidate file (new/changed/unchanged/removed) or rejected file, for
        the sync preview -- read-only, changes nothing on disk or in Redis."""
        source = self._source_for(code)
        if source is None:
            return []
        by_relpath = {u["linked_relpath"]: (name, u) for name, u in self._linked_uploads(code).items()}
        seen_relpaths = set()
        entries: List[Dict[str, Any]] = []
        for f in source.list_files():
            seen_relpaths.add(f.relpath)
            try:
                name = F.safe_name(Path(f.relpath).name)
            except F.UploadRejected as e:
                entries.append({"relpath": f.relpath, "name": Path(f.relpath).name, "size": f.size,
                                "status": "rejected", "reason": str(e)})
                continue
            existing = by_relpath.get(f.relpath)
            if existing is None:
                status = "new"
            elif existing[1]["sha256"] != f.sha256:
                status = "changed"
            else:
                status = "unchanged"
            entries.append({"relpath": f.relpath, "name": name, "size": f.size, "status": status, "reason": None})
        for relpath, (name, u) in by_relpath.items():
            if relpath not in seen_relpaths:
                entries.append({"relpath": relpath, "name": name, "size": u.get("size", 0),
                                "status": "removed", "reason": None})
        for r in source.rejected_files():
            entries.append({"relpath": r.relpath, "name": Path(r.relpath).name, "size": 0,
                            "status": "rejected", "reason": r.reason})
        entries.sort(key=lambda e: e["relpath"])
        return entries

    def sync_materials_source(self, actor: str, code: str) -> Dict[str, int]:
        """Reconcile a linked folder's current files into the course's normal uploads: new
        and changed files are copied in and registered as uploads (source="linked"),
        unchanged ones are left alone, and uploads whose linked file is gone are removed. A
        no-op (all zero) when the course has no linked source. Called automatically before a
        Build job is priced (JobService.create) so the existing upload pipeline -- pricing,
        confirmation, embedding -- does the actual ingesting with no changes of its own."""
        counts = {"new": 0, "changed": 0, "unchanged": 0, "removed": 0, "rejected": 0}
        source = self._source_for(code)
        if source is None:
            return counts
        weeks = self.require_managed(code)["weeks"]
        for entry in self.materials_source_status(code):
            status = entry["status"]
            if status in ("new", "changed"):
                try:
                    data = source.read_bytes(entry["relpath"])
                    week, kind = F.infer_week_kind(entry["name"])  # "Week02-Lab-Notes.md" says its own week and kind
                    record = self.add_upload(actor, code, entry["name"], io.BytesIO(data),
                                             week=week if week and week <= weeks else None,
                                             kind=kind or F.DEFAULT_KIND.get(Path(entry["name"]).suffix.lower()))
                except (InvalidInput, FolderSourceError):
                    counts["rejected"] += 1
                    continue
                record["linked_relpath"] = entry["relpath"]
                self.conn.hset(uploads_key(code), record["name"], json.dumps(record))
                counts[status] += 1
            elif status == "unchanged":
                counts["unchanged"] += 1
            elif status == "removed":
                self.conn.hdel(uploads_key(code), entry["name"])
                (self.uploads_dir(code) / Path(entry["name"]).name).unlink(missing_ok=True)
                counts["removed"] += 1
            elif status == "rejected":
                counts["rejected"] += 1
        self.events.staff(actor, "materials_source_sync", course=code, payload=counts)
        return counts
