"""B4: KC model versions, drafts, spreadsheet round-trip, publishing with lineage."""

import io
import json
import os
import shutil

import pytest
from openpyxl import load_workbook

from src.onboarding import kc_model as K
from src.storage.event_log import EventLog
from tests.conftest import FIXTURE_DATA
from tests.test_api import register_and_login
from tests.test_onboarding import new_code

DEMO = json.loads((FIXTURE_DATA / "kc_models/DEMO101/kc_model_DEMO101.json").read_text())


@pytest.fixture
def teacher(client, services):
    username, headers = register_and_login(client)
    services.redis_client.get_redis().hset(f"user:{username}", "role", "teacher")
    return username, headers


def managed_course_with_job_draft(client, headers, services, weeks=3):
    """A Teacher-area course whose onboarding job produced a draft (DEMO101's model)."""
    code = new_code()
    client.post("/teach/courses", json={"code": code, "name": "Draft Course", "discipline": "computing",
                                        "weeks": weeks}, headers=headers)
    drafts = services.registry.data_dir / "kc_models" / code / "drafts"
    drafts.mkdir(parents=True)
    (drafts / "job1.json").write_text(json.dumps(DEMO))
    return code


def publish_first_version(client, headers, services):
    code = managed_course_with_job_draft(client, headers, services)
    r = client.post(f"/teach/courses/{code}/kc/draft", json={"source": "job:job1"}, headers=headers)
    assert r.status_code == 201, r.text
    r = client.post(f"/teach/courses/{code}/kc/publish", json={"note": "first"}, headers=headers)
    assert r.status_code == 200, r.text
    return code


def rows(client, headers, code):
    return client.get(f"/teach/courses/{code}/kc/draft", headers=headers).json()["rows"]


def save(client, headers, code, body_rows):
    return client.put(f"/teach/courses/{code}/kc/draft", json={"rows": body_rows}, headers=headers)


# ---------------------------------------------------------------------------- pure rules


def test_new_ids_are_never_reused_and_moves_keep_ids():
    base = K.rows_from_model(DEMO)
    lo = base[0]["lo_id"]
    week, lo_num = lo[3:5], lo[6:8]
    used = K.ids_in(DEMO) | {f"GO_{week}_{lo_num}_009"}  # a retired, higher number
    new = dict(base[0], go_id=None, skill_name="Brand new")
    fresh_lo = dict(base[0], go_id=None, lo_id=None, week=2, lo_title="A new learning objective")
    moved = dict(base[1], week=3)  # a move keeps the ID
    out = K.assign_ids([new, fresh_lo, moved], used)
    assert out[0]["go_id"] == f"GO_{week}_{lo_num}_010"
    top_lo = max(int(i[6:8]) for i in used if i.startswith(("LO_", "GO_")))
    assert out[1]["lo_id"] == f"LO_02_{top_lo + 1:02d}" and out[1]["go_id"] == f"GO_02_{top_lo + 1:02d}_001"
    assert out[2]["go_id"] == base[1]["go_id"]


def test_validation_catches_what_the_plan_lists():
    base = K.rows_from_model(DEMO)
    known, gos = K.ids_in(DEMO), set(K.gos_of(DEMO))

    def errors(rs, retired=frozenset(), weeks=3):
        return [i["message"] for i in K.validate(rs, known, set(retired), gos, weeks) if i["level"] == "error"]

    assert errors(base) == []
    bad = [dict(r) for r in base]
    bad[0]["go_id"] = "GO_09_99_999"
    bad[1]["go_id"] = bad[2]["go_id"]
    bad[3]["mastery_threshold"] = 0.99
    bad[4]["cognitive_level"] = "Memorise"
    bad[5]["prerequisites"] = ["GO_77_77_777"]
    found = " | ".join(errors(bad))
    for text in ("Unknown ID GO_09_99_999", "appears twice", "0.5 to 0.95", "Bloom level", "isn't an objective"):
        assert text in found, text

    cyc = [dict(r) for r in base]
    cyc[0]["prerequisites"], cyc[1]["prerequisites"] = [cyc[1]["go_id"]], [cyc[0]["go_id"]]
    assert any("circle" in e for e in errors(cyc))
    assert any("Week 3 has no objectives" in e for e in errors([r for r in base if r["week"] != 3]))
    assert any("retired" in e for e in errors(base, retired={base[0]["go_id"]}))
    moved = [dict(r) for r in base]
    moved[0]["week"] = 3  # half a learning objective in another week
    assert any("same week" in e for e in errors(moved))
    split = [dict(r) for r in base]
    split[0] = dict(split[0], go_id=None, split_from=base[1]["go_id"])  # its source is still there
    assert any("removes" in e for e in errors(split))
    later = [dict(r) for r in base]
    later[0]["prerequisites"] = [next(r["go_id"] for r in base if r["week"] == 3)]
    warnings = [i for i in K.validate(later, known, set(), gos, 3) if i["level"] == "warning"]
    assert any("after this objective" in w["message"] for w in warnings)


# ---------------------------------------------------------------------------- drafts and publishing


def test_a_job_draft_becomes_version_1_and_students_can_enrol(client, teacher, services):
    _, headers = teacher
    code = managed_course_with_job_draft(client, headers, services)
    assert code not in [c["code"] for c in client.get("/courses").json()]
    r = client.post(f"/teach/courses/{code}/kc/draft", json={"source": "job:job1"}, headers=headers)
    draft = r.json()
    assert r.status_code == 201 and len(draft["rows"]) == len(K.gos_of(DEMO)) and draft["based_on"] is None
    assert client.post(f"/teach/courses/{code}/kc/draft", json={"source": "job:job1"}, headers=headers).status_code == 409
    diff = client.get(f"/teach/courses/{code}/kc/diff", headers=headers).json()
    assert diff["counts"]["added"] == len(K.gos_of(DEMO)) and diff["impact"]["students_affected"] == 0

    out = client.post(f"/teach/courses/{code}/kc/publish", json={}, headers=headers).json()
    assert out["version"] == 1
    folder = services.registry.data_dir / "kc_models" / code
    assert (folder / "versions" / "v1.json").exists() and not (folder / "versions" / "draft.json").exists()
    live = json.loads((folder / f"kc_model_{code}.json").read_text())
    assert "id_ledger" not in live and live["version_info"]["version"] == 1
    assert code in [c["code"] for c in client.get("/courses").json()]  # now open for registration
    overview = client.get(f"/teach/courses/{code}/kc", headers=headers).json()
    assert overview["published_version"] == 1 and overview["draft"] is None and overview["versions"][0]["live"]


def test_editing_a_live_course_retires_splits_merges_and_carries_mastery(client, teacher, services):
    username, headers = teacher
    code = publish_first_version(client, headers, services)
    conn = services.redis_client.get_redis()
    base = K.rows_from_model(json.loads((services.registry.data_dir / "kc_models" / code / f"kc_model_{code}.json").read_text()))
    a, b, c, d, e = (base[i]["go_id"] for i in range(5))
    conn.set(f"mastery:learner1:{code}", json.dumps({"go_masteries": {
        a: {"level": 0.8, "confidence": 0.7, "last_updated": "", "interaction_count": 3, "evidence_summary": ""},
        c: {"level": 0.6, "confidence": 0.5, "last_updated": "", "interaction_count": 2, "evidence_summary": ""},
        d: {"level": 0.2, "confidence": 0.5, "last_updated": "", "interaction_count": 1, "evidence_summary": ""},
        e: 0.9}}))
    conn.set(f"mastery:learner2:{code}", json.dumps({"go_masteries": {}}))

    client.post(f"/teach/courses/{code}/kc/draft", json={"source": "published"}, headers=headers)
    current = rows(client, headers, code)
    by_id = {r["go_id"]: r for r in current}
    new_rows = [r for r in current if r["go_id"] not in (a, c, d, e)]
    by_id[b]["mastery_threshold"] = 0.7  # an edit
    new_rows += [dict(by_id[a], go_id=None, split_from=a, skill_name=f"{by_id[a]['skill_name']} (part {n})",
                      prerequisites=[]) for n in (1, 2)]
    new_rows.append(dict(by_id[c], go_id=None, merged_from=[c, d], skill_name="Merged objective", prerequisites=[]))
    new_rows.append(dict(by_id[b], go_id=None, skill_name="An added objective", prerequisites=[]))
    for r in new_rows:  # prerequisites on removed objectives would be errors
        r["prerequisites"] = [p for p in r["prerequisites"] if p not in (a, c, d, e)]
    r = save(client, headers, code, new_rows)
    assert r.status_code == 200, r.text
    saved = r.json()["rows"]
    assert all(row["go_id"] for row in saved)

    diff = client.get(f"/teach/courses/{code}/kc/diff", headers=headers).json()
    assert diff["counts"]["splits"] == 1 and diff["counts"]["merges"] == 1 and diff["counts"]["added"] == 4
    assert [x["go_id"] for x in diff["retired"]] == [e]
    assert any(ch["go_id"] == b for ch in diff["changed"])
    assert diff["impact"]["students_affected"] == 1

    out = client.post(f"/teach/courses/{code}/kc/publish", json={"note": "split, merge, retire"}, headers=headers).json()
    assert out["version"] == 2 and out["mastery_records_migrated"] == 1
    gos = json.loads(conn.get(f"mastery:learner1:{code}"))["go_masteries"]
    parts = [x["go_id"] for x in saved if x.get("split_from") == a]
    merged = next(x["go_id"] for x in saved if x.get("merged_from"))
    assert all(gos[p]["level"] == 0.8 and "split" in gos[p]["evidence_summary"] for p in parts)
    assert gos[merged]["level"] == pytest.approx(0.4) and gos[merged]["interaction_count"] == 3
    assert gos[a]["level"] == 0.8 and gos[e] == 0.9  # old entries stay (ignored)

    v2 = json.loads((services.registry.data_dir / "kc_models" / code / "versions" / "v2.json").read_text())
    assert {x["go_id"] for x in v2["retired"]} == {a, c, d, e}
    assert v2["lineage"]["splits"][0]["from"] == a and v2["lineage"]["merges"][0]["to"] == merged
    assert e in v2["lineage"]["retired"] and a in v2["id_ledger"]
    assert services.registry.kc_model(code)["version_info"]["version"] == 2  # reloaded without a restart

    client.post(f"/teach/courses/{code}/kc/draft", json={"source": "published"}, headers=headers)
    again = rows(client, headers, code)
    again.append(dict(again[0], go_id=e))  # a retired ID can't come back
    r = save(client, headers, code, again)
    assert r.status_code == 400 and "retired" in r.json()["detail"]

    audit = EventLog(os.environ["LEA_EVENTS_DB"]).query("type = 'kc_publish'")
    payload = json.loads(audit[-1]["payload_json"])
    assert payload["version"] == 2 and payload["splits"] == 1 and payload["mastery_records_migrated"] == 1
    assert "review_seconds" in payload and payload["draft_saves"] == 1


def test_a_stale_draft_cant_be_published(client, teacher, services):
    _, headers = teacher
    code = publish_first_version(client, headers, services)
    client.post(f"/teach/courses/{code}/kc/draft", json={"source": "published"}, headers=headers)
    draft_path = services.registry.data_dir / "kc_models" / code / "versions" / "draft.json"
    stale = draft_path.read_text()
    assert client.post(f"/teach/courses/{code}/kc/publish", json={}, headers=headers).status_code == 200
    draft_path.write_text(stale)  # a second draft started from version 1
    r = client.post(f"/teach/courses/{code}/kc/publish", json={}, headers=headers)
    assert r.status_code == 409 and "Start a new draft" in r.json()["detail"]


def test_a_pre_versioning_course_keeps_its_model_as_version_1(client, teacher, services):
    username, headers = teacher
    code = new_code()
    folder = services.registry.data_dir / "kc_models" / code
    folder.mkdir(parents=True)
    shutil.copy(FIXTURE_DATA / "kc_models/DEMO101/kc_model_DEMO101.json", folder / f"kc_model_{code}.json")
    services.staff.add_owner("admin", code, username)
    assert client.get(f"/teach/courses/{code}/kc", headers=headers).json()["published_version"] == 0
    client.post(f"/teach/courses/{code}/kc/draft", json={"source": "published"}, headers=headers)
    out = client.post(f"/teach/courses/{code}/kc/publish", json={}, headers=headers).json()
    assert out["version"] == 2 and out["changes"]["changed"] == 0
    v1 = json.loads((folder / "versions" / "v1.json").read_text())
    assert v1["version_info"]["note"] == "The model in use before versioning" and len(K.gos_of(v1)) == len(K.gos_of(DEMO))


def test_the_spreadsheet_round_trip(client, teacher, services):
    _, headers = teacher
    code = publish_first_version(client, headers, services)
    r = client.get(f"/teach/courses/{code}/kc/draft/export", headers=headers)  # no draft: the live model
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/vnd.openxmlformats")
    wb = load_workbook(io.BytesIO(r.content))
    ws = wb["Objectives"]
    assert ws.protection.sheet and ws["A2"].protection.locked and not ws["G2"].protection.locked
    assert "Read me" in wb.sheetnames
    headers_row = [c.value for c in ws[1]]
    col = {h: i + 1 for i, h in enumerate(headers_row)}
    first_id = ws.cell(2, col["GO ID"]).value
    ws.cell(2, col["Mastery threshold"]).value = 0.9
    last = ws.max_row + 1
    for h, v in [("Week", 1), ("Week title", ws.cell(2, col["Week title"]).value), ("LO ID", ws.cell(2, col["LO ID"]).value),
                 ("Learning objective", ws.cell(2, col["Learning objective"]).value), ("Objective name", "From Excel"),
                 ("Description", "Added in the spreadsheet"), ("Bloom level", "Apply"), ("Mastery threshold", 0.75)]:
        ws.cell(last, col[h]).value = v
    buf = io.BytesIO()
    wb.save(buf)
    r = client.post(f"/teach/courses/{code}/kc/draft/import", files={"file": ("kc.xlsx", buf.getvalue())}, headers=headers)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["diff"]["counts"]["added"] == 1 and out["diff"]["counts"]["changed"] == 1
    assert any(ch["go_id"] == first_id for ch in out["diff"]["changed"])
    assert out["draft"]["source"] == "import"

    ws.cell(3, col["GO ID"]).value = "GO_42_42_042"  # a typed-in ID
    buf = io.BytesIO()
    wb.save(buf)
    r = client.post(f"/teach/courses/{code}/kc/draft/import", files={"file": ("kc.xlsx", buf.getvalue())}, headers=headers)
    assert r.status_code == 400 and "Unknown ID GO_42_42_042" in r.json()["detail"]
    assert len(rows(client, headers, code)) == len(K.gos_of(DEMO)) + 1  # the draft is unchanged
    r = client.post(f"/teach/courses/{code}/kc/draft/import", files={"file": ("x.xlsx", b"not a workbook")}, headers=headers)
    assert r.status_code == 400


def test_validate_does_not_save_and_discard_removes_the_draft(client, teacher, services):
    _, headers = teacher
    code = publish_first_version(client, headers, services)
    client.post(f"/teach/courses/{code}/kc/draft", json={"source": "published"}, headers=headers)
    current = rows(client, headers, code)
    current[0]["mastery_threshold"] = 2
    r = client.post(f"/teach/courses/{code}/kc/draft/validate", json={"rows": current}, headers=headers)
    assert any(i["field"] == "mastery_threshold" for i in r.json()["issues"])
    assert rows(client, headers, code)[0]["mastery_threshold"] != 2
    assert client.delete(f"/teach/courses/{code}/kc/draft", headers=headers).status_code == 204
    assert client.get(f"/teach/courses/{code}/kc/draft", headers=headers).status_code == 404


def test_another_teacher_cant_touch_the_model(client, teacher, services):
    _, headers = teacher
    code = publish_first_version(client, headers, services)
    other, other_headers = register_and_login(client)
    services.redis_client.get_redis().hset(f"user:{other}", "role", "teacher")
    for method, path in [("get", "/kc"), ("post", "/kc/draft"), ("get", "/kc/draft/export"), ("post", "/kc/publish")]:
        assert client.request(method, f"/teach/courses/{code}{path}", json={}, headers=other_headers).status_code == 403
