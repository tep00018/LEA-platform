"""B9: the whole teacher journey through the API, as in BUILD_PLAN.md's milestone 10.

An admin creates a teacher; the teacher creates a course, uploads materials, runs the
onboarding job, reviews and publishes the objectives, runs the content audit, tries the
course as a student, and sees analytics from simulated students. Along the way: nothing a
teacher does reaches real analytics or research exports, and every teacher action is in
the event log for a later study (with the teacher pseudonymised on export).
"""

import csv
import json

from src.onboarding.simulate import seed
from tests.test_api import register_and_login
from tests.test_onboarding import MD, fake_pipeline, new_code, plan_for, pptx, upload  # noqa: F401


def login(client, username, password):
    r = client.post("/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_admin_to_analytics(client, services, fake_pipeline, tmp_path):  # noqa: F811
    # 1. An admin creates a teacher (no self-service teacher sign-up).
    admin, admin_headers = register_and_login(client)
    services.redis_client.get_redis().hset(f"user:{admin}", "role", "admin")
    teacher = f"t_{new_code().lower()}"
    r = client.post("/admin/users", json={"username": teacher, "full_name": "Dr Rivera", "password": "teach-pass-1",
                                          "role": "teacher"}, headers=admin_headers)
    assert r.status_code == 201, r.text
    headers = login(client, teacher, "teach-pass-1")
    assert client.get("/teach/courses", headers=headers).json() == []

    # 2. The teacher creates a course, sets weekly objectives and uploads materials.
    code = new_code()
    r = client.post("/teach/courses", json={"code": code, "name": "Intro to AI", "discipline": "computing",
                                            "weeks": 3}, headers=headers)
    assert r.status_code == 201, r.text
    assert client.put(f"/teach/courses/{code}/objectives", json=plan_for(3), headers=headers).status_code == 200
    assert upload(client, headers, code, [("notes.md", MD, "text/markdown"),
                                          ("slides.pptx", pptx(2), "application/zip")], week=1).status_code == 201

    # 3. The onboarding job is priced, confirmed and run.
    job = client.post(f"/teach/courses/{code}/jobs", json={}, headers=headers).json()
    assert job["estimate"]["usd"] > 0
    client.post(f"/teach/jobs/{job['id']}/confirm", headers=headers)
    assert services.jobs.run_next() is True
    assert client.get(f"/teach/jobs/{job['id']}", headers=headers).json()["status"] == "succeeded"
    assert code not in [c["code"] for c in client.get("/courses").json()]  # not open until published

    # 4. Review the drafted objectives: edit one, then publish version 1.
    r = client.post(f"/teach/courses/{code}/kc/draft", json={"source": f"job:{job['id']}"}, headers=headers)
    assert r.status_code == 201, r.text
    rows = r.json()["rows"]
    edited = rows[0]["go_id"]
    rows[0] = {**rows[0], "skill_name": "Explain what an intelligent agent is"}
    r = client.put(f"/teach/courses/{code}/kc/draft", json={"rows": rows}, headers=headers)
    assert r.status_code == 200, r.text
    out = client.post(f"/teach/courses/{code}/kc/publish", json={"note": "first"}, headers=headers).json()
    assert out["version"] == 1
    assert code in [c["code"] for c in client.get("/courses").json()]

    # 5. The content audit runs on the live version; one finding is accepted.
    services.audit._embed = lambda texts: [[float(i), 1.0] for i in range(len(texts))]
    services.audit._search = lambda c, text: (0.7, "Week01-ReadingA-Notes.md")
    run = client.post(f"/teach/courses/{code}/audit/runs", headers=headers)
    assert run.status_code in (200, 201), run.text
    findings = run.json()["findings"]
    assert findings
    key = findings[0]["key"]
    assert client.put(f"/teach/courses/{code}/audit/findings/{key}", json={"status": "accepted"},
                      headers=headers).status_code == 200

    # 6. Try as a student: a sandbox tagged test, enrolled in the new course.
    r = client.post(f"/teach/courses/{code}/preview", headers=headers)
    assert r.status_code == 200, r.text
    preview = {"Authorization": f"Bearer {r.json()['token']}"}
    me = client.get("/me", headers=preview).json()
    assert code in me["enrolled_courses"] and services.events.session_kind(me["username"]) == "test"
    client.post("/tutor", json={"course": code, "week": 1}, headers=preview)

    # 7. Analytics: no real students yet; simulated students fill the screens.
    real = client.get(f"/teach/courses/{code}/analytics", headers=headers).json()
    assert real["suppressed"] is True and real["students"] is None
    model = json.loads((services.registry.data_dir / "kc_models" / code / f"kc_model_{code}.json").read_text())
    seed(services.events, model, code, students=12)
    sim = client.get(f"/teach/courses/{code}/analytics", params={"kind": "simulated"}, headers=headers).json()
    assert sim["students"] == 12 and sim["kc_version"] == 1
    assert client.get(f"/teach/courses/{code}/analytics", headers=headers).json()["suppressed"] is True
    detail = client.get(f"/teach/courses/{code}/analytics/objectives/{edited}", params={"kind": "simulated"},
                        headers=headers).json()
    assert detail["skill_name"] == "Explain what an intelligent agent is" and detail["curve"]

    # The sandbox never reaches real analytics or a research export.
    sandbox = services.events.pseudonym(me["username"])
    assert all(r["username_hash"] != sandbox for r in services.analytics.rows(code, "real"))
    research = tmp_path / "research.csv"
    services.events.log.export_csv(research, kinds=["real", "simulated"], course=code)
    exported = list(csv.DictReader(research.open(encoding="utf-8")))
    assert exported and all(r["session_kind"] == "simulated" for r in exported)

    # Every teacher action is logged for a later study; the export pseudonymises teachers.
    staff = tmp_path / "teaching.csv"
    services.events.log.export_staff_csv(staff, services.events.pseudonym, course=code)
    actions = list(csv.DictReader(staff.open(encoding="utf-8")))
    kinds = [a["type"] for a in actions]
    for expected in ("course_create", "upload_add", "job_create", "job_confirm", "kc_draft_create",
                     "kc_draft_save", "kc_publish", "audit_run", "audit_accepted", "preview_start", "analytics_view"):
        assert expected in kinds, expected
    assert teacher not in staff.read_text(encoding="utf-8")
    payload = {a["type"]: json.loads(a["payload_json"]) for a in actions}
    assert payload["kc_draft_save"]["gos_changed"] == [edited]
    assert "review_seconds" in payload["kc_publish"] and payload["audit_accepted"]["target"]
    overviews = [json.loads(a["payload_json"]) for a in actions if a["type"] == "analytics_view"]
    assert any(v.get("view") == "overview" and v["kind"] == "simulated" and v["flagged"] for v in overviews)
    sandbox_name = f"{teacher}.preview"
    assert sandbox_name not in staff.read_text(encoding="utf-8")  # names inside payloads too
