"""KC model versions, the teacher's draft, and publishing.

On disk, per course (``data/kc_models/<CODE>/``):

- ``versions/v<n>.json``: every published version, never changed afterwards; each carries
  ``version_info`` (who, when, based on, counts), the cumulative ``lineage`` (splits,
  merges, retirements), ``retired`` (the removed objectives, kept) and ``id_ledger`` (every
  GO and LO ID ever issued, so none is reused);
- ``versions/published.json``: which version is live;
- ``versions/draft.json``: the one draft being edited (rows, see ``src.onboarding.kc_model``);
- ``kc_model_<CODE>.json``: a copy of the live version, which is what LEA reads. Students
  keep using it while a draft is edited.

A course that predates versioning gets its current model recorded as v1 the first time
it is versioned. Publishing carries mastery over along the lineage **(research)**: each
part of a split gets the old objective's mastery, a merge the mean of its sources;
retired objectives keep their mastery but no longer count.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.onboarding import kc_model as K
from src.onboarding import kc_sheet
from src.services.errors import InvalidInput, NotFound, WrongState
from src.services.events import EventRecorder, disabled
from src.storage.locks import redis_lock


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write_json(path: Path, data: Any) -> None:
    """Write atomically (a reader never sees half a file)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


class KCVersionService:
    def __init__(self, registry, redis_client, setup, events: Optional[EventRecorder] = None):
        self.registry = registry
        self.redis_client = redis_client
        self.setup = setup
        self.events = events or disabled()

    # ------------------------------------------------------------------ paths and reads

    def folder(self, code: str) -> Path:
        return Path(self.registry.data_dir) / "kc_models" / code

    def _versions(self, code: str) -> Path:
        return self.folder(code) / "versions"

    def _read(self, path: Path) -> Optional[Dict[str, Any]]:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def published_version(self, code: str) -> Optional[int]:
        pointer = self._read(self._versions(code) / "published.json")
        if pointer:
            return pointer["version"]
        return 0 if (self.folder(code) / f"kc_model_{code}.json").exists() else None

    def published(self, code: str) -> Optional[Dict[str, Any]]:
        """The live model (a pre-versioning course's current file counts as version 0)."""
        version = self.published_version(code)
        if version is None:
            return None
        if version == 0:
            return self._read(self.folder(code) / f"kc_model_{code}.json")
        return self._read(self._versions(code) / f"v{version}.json")

    def versions(self, code: str) -> List[Dict[str, Any]]:
        live = self.published_version(code)
        out = []
        for path in sorted(self._versions(code).glob("v*.json"), key=lambda p: int(p.stem[1:])):
            info = (self._read(path) or {}).get("version_info", {})
            out.append({**info, "version": int(path.stem[1:]), "live": int(path.stem[1:]) == live})
        if live == 0:
            model = self.published(code) or {}
            out.append({"version": 0, "live": True, "published_at": "", "published_by": "",
                        "note": "In use before versioning", "objectives": len(K.gos_of(model))})
        return out

    def _ledger(self, code: str) -> set:
        used = set()
        for path in self._versions(code).glob("v*.json"):
            model = self._read(path) or {}
            used |= set(model.get("id_ledger", [])) | K.ids_in(model)
        return used | K.ids_in(self.published(code))

    def _retired(self, code: str) -> set:
        model = self.published(code) or {}
        return {go["go_id"] for go in model.get("retired", [])}

    def _weeks(self, code: str, rows: List[Dict[str, Any]]) -> int:
        meta = self.setup.meta(code) or {}
        live = self.published(code) or {}
        return max(meta.get("weeks", 0), len(live.get("week_navigation", {}))) or \
            max((int(r["week"]) for r in rows if str(r.get("week", "")).isdigit()), default=1)

    # ------------------------------------------------------------------ drafts

    def draft(self, code: str) -> Optional[Dict[str, Any]]:
        return self._read(self._versions(code) / "draft.json")

    def create_draft(self, actor: str, code: str, source: str = "published", replace: bool = False) -> Dict[str, Any]:
        """Start a draft from the live model (``published``) or a job's draft (``job:<id>``)."""
        if self.draft(code) and not replace:
            raise WrongState("This course already has a draft. Keep editing it, or replace it.")
        live = self.published(code)
        if source == "published":
            if live is None:
                raise InvalidInput("There's no published model yet. Start from an onboarding job's draft.")
            rows, base_note = K.rows_from_model(live), "published"
        elif source.startswith("job:"):
            path = self.folder(code) / "drafts" / f"{source[4:]}.json"
            job_model = self._read(path)
            if job_model is None:
                raise NotFound("That job didn't produce a KC draft.")
            rows = K.rows_from_model(job_model)
            if live is not None:  # its IDs were generated afresh and may clash with published ones
                for r in rows:
                    r["go_id"] = r["lo_id"] = None
                    r["prerequisites"] = []
                rows = K.assign_ids(rows, self._ledger(code))
            base_note = source
        else:
            raise InvalidInput("Start from 'published' or 'job:<id>'.")
        draft = {"course": code, "source": base_note, "based_on": self.published_version(code),
                 "created_by": actor, "created_at": _now(), "updated_by": actor, "updated_at": _now(),
                 "saves": 0, "rows": rows}
        _write_json(self._versions(code) / "draft.json", draft)
        self.events.staff(actor, "kc_draft_create", course=code, payload={"source": base_note, "objectives": len(rows)})
        return self.view(code)

    def check(self, code: str, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        draft = self.draft(code) or {}
        known = self._ledger(code) | {r.get("go_id") for r in draft.get("rows", [])} | \
            {r.get("lo_id") for r in draft.get("rows", [])}
        known.discard(None)
        return K.validate(rows, known, self._retired(code), set(K.gos_of(self.published(code))),
                          self._weeks(code, rows))

    def save_rows(self, actor: str, code: str, rows: List[Dict[str, Any]], source: Optional[str] = None) -> Dict[str, Any]:
        draft = self.draft(code)
        if draft is None:
            raise WrongState("Start a draft first.")
        rows = [self.clean(r) for r in rows]
        errors = [i for i in self.check(code, rows) if i["level"] == "error"]
        if errors:
            raise InvalidInput("The draft wasn't saved: " + "; ".join(
                (f"row {e['row']}: " if e["row"] else "") + e["message"] for e in errors[:8])
                + (f" (and {len(errors) - 8} more)" if len(errors) > 8 else ""))
        before = {r["go_id"]: r for r in draft["rows"]}
        rows = K.assign_ids(rows, self._ledger(code) | set(before) | {r["lo_id"] for r in draft["rows"]})
        for r in rows:  # the source excerpt travels with its objective
            if not r.get("provenance") and r["go_id"] in before:
                r["provenance"] = before[r["go_id"]].get("provenance")
        touched = K.diff(K.model_from_rows(draft["rows"], None, {}), rows)
        change = touched["counts"]
        draft.update({"rows": rows, "updated_by": actor, "updated_at": _now(), "saves": draft.get("saves", 0) + 1})
        if source:
            draft["source"] = source
        _write_json(self._versions(code) / "draft.json", draft)
        self.events.staff(actor, "kc_draft_save", course=code, payload={
            **change, "via": source or "table",
            "gos_changed": [c["go_id"] for c in touched["changed"]][:200],
            "gos_added": [g["go_id"] for g in touched["added"]][:200],
            "gos_removed": [g["go_id"] for g in touched["retired"]][:200]})
        return self.view(code)

    def discard(self, actor: str, code: str) -> None:
        path = self._versions(code) / "draft.json"
        if not path.exists():
            raise NotFound("There's no draft.")
        path.unlink()
        self.events.staff(actor, "kc_draft_discard", course=code)

    def view(self, code: str) -> Dict[str, Any]:
        draft = self.draft(code)
        if draft is None:
            raise NotFound("There's no draft.")
        return {**{k: v for k, v in draft.items() if k != "rows"}, "rows": draft["rows"],
                "issues": self.check(code, draft["rows"])}

    @staticmethod
    def clean(row: Dict[str, Any]) -> Dict[str, Any]:
        r = {k: row.get(k) for k in ("go_id", "week", "week_title", "lo_id", "lo_title", "lo_short_title",
                                     "skill_name", "description", "cognitive_level", "mastery_threshold",
                                     "keywords", "prerequisites", "prerequisite_notes", "split_from",
                                     "merged_from", "provenance")}
        r["go_id"], r["lo_id"], r["split_from"] = r["go_id"] or None, r["lo_id"] or None, r["split_from"] or None
        for f in ("keywords", "prerequisites", "prerequisite_notes", "merged_from"):
            r[f] = [str(v).strip() for v in (r[f] or []) if str(v).strip()]
        for f in ("week_title", "lo_title", "lo_short_title", "skill_name", "description"):
            r[f] = str(r[f] or "").strip()
        r["cognitive_level"] = K.bloom(r["cognitive_level"])
        return r

    # ------------------------------------------------------------------ spreadsheet

    def export(self, code: str) -> bytes:
        draft = self.draft(code)
        rows = draft["rows"] if draft else K.rows_from_model(self.published(code) or {})
        if not rows:
            raise NotFound("There's no model to export yet.")
        return kc_sheet.export_xlsx(rows, code)

    def import_sheet(self, actor: str, code: str, data: bytes) -> Dict[str, Any]:
        try:
            rows = kc_sheet.import_xlsx(data)
        except ValueError as e:
            raise InvalidInput(str(e)) from None
        if self.draft(code) is None:
            self.create_draft(actor, code, "published")
        self.save_rows(actor, code, rows, source="import")
        return {"draft": self.view(code), "diff": self.diff(code)}

    # ------------------------------------------------------------------ diff and publish

    def diff(self, code: str) -> Dict[str, Any]:
        draft = self.draft(code)
        if draft is None:
            raise NotFound("There's no draft.")
        change = K.diff(self.published(code), draft["rows"])
        change["impact"] = self._impact(code, change)
        return change

    def _mastery_keys(self, code: str):
        conn = self.redis_client.get_redis()
        return conn, [k for k in conn.scan_iter(match=f"mastery:*:{code}", count=500)]

    def _impact(self, code: str, change: Dict[str, Any]) -> Dict[str, Any]:
        """How many students have mastery on objectives this draft retires, splits or merges."""
        affected = {"retired": {r["go_id"] for r in change["retired"]},
                    "split": {s["from"] for s in change["splits"]},
                    "merged": {m for mg in change["merges"] for m in mg["from"]}}
        conn, keys = self._mastery_keys(code)
        counts = {k: 0 for k in affected}
        students = 0
        for key in keys:
            data = json.loads(conn.get(key) or "{}").get("go_masteries", {})
            hit = False
            for kind, ids in affected.items():
                if ids & set(data):
                    counts[kind] += 1
                    hit = True
            students += hit
        return {"students_affected": students, "with_mastery_on": counts, "students_with_mastery": len(keys)}

    def publish(self, actor: str, code: str, note: str = "") -> Dict[str, Any]:
        draft = self.draft(code)
        if draft is None:
            raise NotFound("There's no draft to publish.")
        if draft.get("based_on") != self.published_version(code):
            raise WrongState("Another version was published after this draft was started. Start a new draft.")
        rows = draft["rows"]
        errors = [i for i in self.check(code, rows) if i["level"] == "error"]
        if errors:
            raise InvalidInput(f"Fix the draft's {len(errors)} problem(s) first: {errors[0]['message']}")
        live = self.published(code)
        folder = self._versions(code)
        if live is not None and not (folder / "published.json").exists():  # record the pre-versioning model
            _write_json(folder / "v1.json", {**live, "version_info": {
                "version": 1, "published_at": "", "published_by": "", "based_on": None,
                "note": "The model in use before versioning", "objectives": len(K.gos_of(live))}})
            _write_json(folder / "published.json", {"version": 1})
            live = self.published(code)
        change = K.diff(live, rows)
        impact = self._impact(code, change)

        old_lineage = (live or {}).get("lineage", {"splits": [], "merges": [], "retired": []})
        lineage = {"splits": old_lineage["splits"] + change["splits"],
                   "merges": old_lineage["merges"] + change["merges"],
                   "retired": old_lineage["retired"] + [r["go_id"] for r in change["retired"]]}
        removed = set(K.gos_of(live)) - {r["go_id"] for r in rows}
        retired_gos = (live or {}).get("retired", []) + [
            {**g, "retired_in": None} for gid, g in K.gos_of(live).items() if gid in removed]
        course_info = {**(live or {}).get("course_info", {}), "course_code": code}
        if self.setup.meta(code):
            course_info["course_name"] = self.setup.meta(code)["name"]
        model = K.model_from_rows(rows, live or self._job_base(code, draft), course_info, lineage)
        version = (self.published_version(code) or 0) + 1
        for g in retired_gos:
            g["retired_in"] = g["retired_in"] or version
        review_seconds = int((datetime.fromisoformat(_now()) - datetime.fromisoformat(draft["created_at"])).total_seconds())
        model.update({
            "retired": retired_gos,
            "id_ledger": sorted(self._ledger(code) | K.ids_in(model)),
            "version_info": {"version": version, "published_at": _now(), "published_by": actor,
                             "based_on": draft.get("based_on"), "source": draft.get("source"), "note": note,
                             "objectives": len(K.gos_of(model)), "changes": change["counts"],
                             "review_seconds": review_seconds, "draft_saves": draft.get("saves", 0)},
        })
        _write_json(folder / f"v{version}.json", model)
        _write_json(folder / "published.json", {"version": version})
        live_copy = {k: v for k, v in model.items() if k not in ("id_ledger",)}
        _write_json(self.folder(code) / f"kc_model_{code}.json", live_copy)
        (folder / "draft.json").unlink(missing_ok=True)
        self.registry.forget(code)
        migrated = self._carry_mastery(code, change)
        self.events.staff(actor, "kc_publish", course=code, payload={
            "version": version, **change["counts"], "retired": len(change["retired"]),
            "review_seconds": review_seconds, "draft_saves": draft.get("saves", 0), "source": draft.get("source"),
            "students_affected": impact["students_affected"], "mastery_records_migrated": migrated,
            "gos_changed": {c["go_id"]: [f["field"] for f in c["changes"]] for c in change["changed"]},
            "gos_added": [g["go_id"] for g in change["added"]],
            "gos_retired": [g["go_id"] for g in change["retired"]]})
        return {"version": version, "changes": change["counts"], "impact": impact, "mastery_records_migrated": migrated}

    def _job_base(self, code: str, draft: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        source = draft.get("source", "")
        if source.startswith("job:"):
            return self._read(self.folder(code) / "drafts" / f"{source[4:]}.json")
        return None

    def _carry_mastery(self, code: str, change: Dict[str, Any]) -> int:
        """(research) Splits copy the old objective's mastery to each part; merges take the
        mean of the sources a student has. Old entries stay (retired, ignored)."""
        if not change["splits"] and not change["merges"]:
            return 0
        conn, keys = self._mastery_keys(code)
        migrated = 0
        for key in keys:
            with redis_lock(self.redis_client, key):
                data = json.loads(conn.get(key) or "{}")
                gos = data.get("go_masteries", {})
                touched = False
                for split in change["splits"]:
                    old = gos.get(split["from"])
                    if old is None:
                        continue
                    for new_id in split["to"]:
                        gos[new_id] = self._copy_mastery(old, f"Carried over from {split['from']} (split)")
                    touched = True
                for merge in change["merges"]:
                    sources = [gos[m] for m in merge["from"] if m in gos]
                    if not sources:
                        continue
                    levels = [s["level"] if isinstance(s, dict) else float(s) for s in sources]
                    merged = self._copy_mastery(sources[0], f"Mean of {', '.join(merge['from'])} (merge)")
                    if isinstance(merged, dict):
                        merged["level"] = sum(levels) / len(levels)
                        merged["interaction_count"] = sum(int(s.get("interaction_count", 0)) for s in sources
                                                          if isinstance(s, dict))
                    else:
                        merged = sum(levels) / len(levels)
                    gos[merge["to"]] = merged
                    touched = True
                if touched:
                    data["go_masteries"] = gos
                    conn.set(key, json.dumps(data))
                    migrated += 1
        return migrated

    @staticmethod
    def _copy_mastery(entry: Any, why: str) -> Any:
        if not isinstance(entry, dict):
            return float(entry)
        return {**entry, "evidence_summary": why, "last_updated": _now()}
