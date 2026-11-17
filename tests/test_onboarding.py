"""B3: course setup, uploads and onboarding jobs (fake pipeline steps: no OpenAI, no Whisper)."""

import io
import json
import random
import string
import uuid
import zipfile
from pathlib import Path

import pytest

from src.onboarding import files as F
from src.onboarding.pipeline import JobContext, Pipeline, apply_objective_titles, estimate
from tests.conftest import FIXTURE_DATA
from tests.test_api import register_and_login

PDF = b"%PDF-1.4\n" + b"x" * 100
MD = "# Week 1 notes\n\nPerceptrons learn a linear decision boundary.\n".encode()


def pptx(images=2) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        for i in range(images):
            z.writestr(f"ppt/media/image{i}.png", b"\x89PNG")
    return buf.getvalue()


def new_code() -> str:
    return "".join(random.choices(string.ascii_uppercase, k=3)) + f"{random.randint(100, 999)}"


def plan_for(weeks):
    return {"weeks": [{"week": w, "title": f"Week {w} topic",
                       "objectives": [f"Explain the main idea of week {w} in detail", f"Apply week {w} methods to a problem"]}
                      for w in range(1, weeks + 1)]}


@pytest.fixture
def teacher(client, services):
    username, headers = register_and_login(client)
    services.redis_client.get_redis().hset(f"user:{username}", "role", "teacher")
    return username, headers


@pytest.fixture
def course(client, teacher):
    _, headers = teacher
    code = new_code()
    r = client.post("/teach/courses", json={"code": code, "name": "Neural Networks", "discipline": "computing",
                                            "allows_code": True, "code_language": "Python", "weeks": 2}, headers=headers)
    assert r.status_code == 201, r.text
    return code


class FakeCollection:
    def __init__(self):
        self.deleted = []

    def query(self, query_texts, n_results, include):
        weak = "Weak" in query_texts[0]
        return {"ids": [["c1"]], "documents": [["Perceptrons learn a boundary."]],
                "metadatas": [[{"source_file": "Week01-ReadingA-Notes.md"}]], "distances": [[1.9 if weak else 0.5]]}

    def delete(self, where):
        self.deleted.append(where["source_file"])


class FakeProcessor:
    """Stands in for data_foundation's DocumentProcessor."""
    instances = []

    def __init__(self, course, data_dir):
        self.processed, self.metadata, self.errors = [], {}, {}
        self.collection = FakeCollection()
        self.on_file = None
        FakeProcessor.instances.append(self)

    def process_file(self, path):
        self.processed.append(Path(path).name)
        if self.on_file:
            self.on_file(Path(path).name)
        return True

    def _save_metadata(self):
        pass

    def _save_errors(self):
        pass


def fake_kc(ctx):
    model = json.loads((FIXTURE_DATA / "kc_models/DEMO101/kc_model_DEMO101.json").read_text())
    first = next(iter(model["week_navigation"].values()))["learning_objectives"][0]["granular_objectives"][0]
    first["skill_name"] = "Weak coverage objective"
    return model


@pytest.fixture
def fake_pipeline(services):
    FakeProcessor.instances.clear()
    services.jobs.pipeline = Pipeline(processor_factory=FakeProcessor, kc_builder=fake_kc)
    return services.jobs.pipeline


def upload(client, headers, code, files, **form):
    return client.post(f"/teach/courses/{code}/uploads", files=[("files", f) for f in files],
                       data={k: str(v) for k, v in form.items()}, headers=headers)


# ---------------------------------------------------------------------------- files


def test_upload_names_and_contents_are_checked():
    assert F.safe_name("../../Week 1: Intro?.PDF") == "Week 1- Intro.pdf"
    assert F.safe_name(r"C:\\slides\\lecture.pptx") == "lecture.pptx"
    for bad in ("run.exe", "notes", ".pdf", "archive.zip"):
        with pytest.raises(F.UploadRejected):
            F.safe_name(bad)
    F.check_content("a.pdf", PDF)
    F.check_content("a.pptx", pptx())
    F.check_content("a.md", "Café notes".encode())
    F.check_content("a.wav", b"RIFF\x00\x00\x00\x00WAVEfmt ")
    for name, head in [("a.pdf", b"PK\x03\x04"), ("a.docx", PDF), ("a.md", b"\x00\x01\x02binary"),
                       ("a.mp4", b"not a video at all")]:
        with pytest.raises(F.UploadRejected):
            F.check_content(name, head)
    assert F.staged_name(3, "Lecture", "B", "intro to_perceptrons.pptx") == "Week03-LectureB-Intro-To-Perceptrons.pptx"
    assert F.staged_name(None, "Reading", "A", "x.pdf") == "Week00-ReadingA-X.pdf"


# ---------------------------------------------------------------------------- courses


def test_a_teacher_creates_a_course_and_owns_it(client, teacher, course, services):
    username, headers = teacher
    assert username in services.staff.owners(course)
    mine = {c["code"]: c for c in client.get("/teach/courses", headers=headers).json()}
    assert mine[course]["managed"] is True and mine[course]["weeks"] == 2 and mine[course]["has_kc_model"] is False
    assert course not in [c["code"] for c in client.get("/courses").json()]  # students can't see it yet
    profile = json.loads((services.registry.data_dir / "course_profiles" / f"{course}.json").read_text())
    assert profile == {"code": course, "name": "Neural Networks", "discipline": "computing", "allows_code": True,
                       "code_language": "python"}
    again = client.post("/teach/courses", json={"code": course, "name": "X", "discipline": "computing", "weeks": 1},
                        headers=headers)
    assert again.status_code == 400
    taken = client.post("/teach/courses", json={"code": "AIML101", "name": "X", "discipline": "computing", "weeks": 1},
                        headers=headers)
    assert taken.status_code == 400 and "already exists" in taken.json()["detail"]
    bad = client.post("/teach/courses", json={"code": new_code(), "name": "X", "discipline": "astrology", "weeks": 1},
                      headers=headers)
    assert bad.status_code == 400


def test_weekly_objectives_are_validated(client, teacher, course):
    _, headers = teacher
    assert client.get(f"/teach/courses/{course}/objectives", headers=headers).status_code == 404
    one_week = {"weeks": plan_for(1)["weeks"]}
    assert client.put(f"/teach/courses/{course}/objectives", json=one_week, headers=headers).status_code == 400
    terse = plan_for(2)
    terse["weeks"][1]["objectives"] = ["Backprop"]
    r = client.put(f"/teach/courses/{course}/objectives", json=terse, headers=headers)
    assert r.status_code == 400 and "full sentence" in r.json()["detail"]
    r = client.put(f"/teach/courses/{course}/objectives", json=plan_for(2), headers=headers)
    assert r.status_code == 200 and len(r.json()["weeks"][0]["objectives"]) == 2
    assert client.get(f"/teach/courses/{course}/objectives", headers=headers).json()["weeks"][1]["week"] == 2


def test_uploads_are_checked_stored_listed_and_deleted(client, teacher, course, services):
    _, headers = teacher
    r = upload(client, headers, course, [("notes.md", MD, "text/markdown"), ("slides.pptx", pptx(), "application/zip")],
               week=1)
    assert r.status_code == 201, r.text
    assert [u["name"] for u in r.json()] == ["notes.md", "slides.pptx"] and r.json()[0]["week"] == 1
    folder = services.setup.uploads_dir(course)
    assert (folder / "notes.md").read_bytes() == MD

    assert upload(client, headers, course, [("virus.exe", b"MZ", "application/octet-stream")]).status_code == 400
    assert upload(client, headers, course, [("fake.pdf", b"PK\x03\x04zip", "application/pdf")]).status_code == 400
    assert upload(client, headers, course, [("empty.md", b"", "text/markdown")]).status_code == 400
    assert upload(client, headers, course, [("notes.md", MD, "text/markdown")], week=9).status_code == 400
    assert upload(client, headers, course, [("../../escape.md", MD, "text/markdown")]).json()[0]["name"] == "escape.md"
    assert not list(folder.glob(".upload-*"))  # rejected files leave nothing behind

    listed = client.get(f"/teach/courses/{course}/uploads", headers=headers).json()
    assert {u["name"] for u in listed} == {"notes.md", "slides.pptx", "escape.md"}
    assert client.delete(f"/teach/courses/{course}/uploads/escape.md", headers=headers).status_code == 204
    assert not (folder / "escape.md").exists()
    assert client.delete(f"/teach/courses/{course}/uploads/escape.md", headers=headers).status_code == 404


def test_upload_size_limits(client, teacher, course, monkeypatch):
    _, headers = teacher
    monkeypatch.setattr(F, "MAX_FILE_BYTES", 1000)
    r = upload(client, headers, course, [("big.md", b"a" * 1001, "text/markdown")])
    assert r.status_code == 400 and "over" in r.json()["detail"]
    monkeypatch.setattr(F, "MAX_FILE_BYTES", 10_000)
    monkeypatch.setattr(F, "MAX_COURSE_BYTES", 1500)
    assert upload(client, headers, course, [("a.md", b"a" * 1000, "text/markdown")]).status_code == 201
    r = upload(client, headers, course, [("b.md", b"b" * 1000, "text/markdown")])
    assert r.status_code == 400 and "GB of uploads" in r.json()["detail"]
    assert upload(client, headers, course, [("a.md", b"c" * 1200, "text/markdown")]).status_code == 201  # replacing


def test_other_teachers_and_hand_made_courses_are_off_limits(client, teacher, course, services):
    other, other_headers = register_and_login(client)
    services.redis_client.get_redis().hset(f"user:{other}", "role", "teacher")
    for method, path in [("get", f"/teach/courses/{course}/uploads"), ("get", f"/teach/courses/{course}/jobs"),
                         ("put", f"/teach/courses/{course}/objectives")]:
        assert client.request(method, path, json=plan_for(2), headers=other_headers).status_code == 403
    _, headers = teacher
    services.staff.add_owner("admin", "AIML101", teacher[0])
    r = upload(client, headers, "AIML101", [("notes.md", MD, "text/markdown")])
    assert r.status_code == 400 and "managed by hand" in r.json()["detail"]


# ---------------------------------------------------------------------------- jobs


def ready(client, headers, code):
    upload(client, headers, code, [("notes.md", MD, "text/markdown"), ("slides.pptx", pptx(3), "application/zip")], week=1)
    upload(client, headers, code, [("talk.mp3", b"ID3" + b"\x00" * 50, "audio/mpeg")], week=2)
    client.put(f"/teach/courses/{code}/objectives", json=plan_for(2), headers=headers)


def test_a_job_is_priced_confirmed_run_and_reported(client, teacher, course, services, fake_pipeline):
    _, headers = teacher
    ready(client, headers, course)
    r = client.post(f"/teach/courses/{course}/jobs", json={}, headers=headers)
    assert r.status_code == 201, r.text
    job = r.json()
    assert job["status"] == "awaiting_confirmation" and job["steps"][0] == "convert"
    est = job["estimate"]
    assert est["documents"] == 2 and est["media"] == 1 and est["images"] == 3 and est["model_calls"] == 6
    assert est["usd"] > 0 and any("Whisper" in n for n in est["notes"])
    assert services.jobs.run_next() is False  # nothing runs before confirmation
    assert client.post(f"/teach/courses/{course}/jobs", json={}, headers=headers).status_code == 409  # one per course

    assert client.post(f"/teach/jobs/{job['id']}/confirm", headers=headers).json()["status"] == "queued"
    assert upload(client, headers, course, [("late.md", MD, "text/markdown")]).status_code == 409  # files in use
    assert services.jobs.run_next() is True
    done = client.get(f"/teach/jobs/{job['id']}", headers=headers).json()
    assert done["status"] == "succeeded" and done["percent"] == 100, done
    processor = FakeProcessor.instances[-1]
    assert processor.processed == ["Week02-AudioA-Talk.mp3", "Week01-LectureA-Slides.pptx", "Week01-ReadingA-Notes.md"]
    staged = sorted(p.name for p in (services.registry.data_dir / "org_docs" / course).iterdir())
    assert staged == ["Week01-LectureA-Slides.pptx", "Week01-ReadingA-Notes.md", "Week02-AudioA-Talk.mp3"]

    draft_path = services.registry.data_dir / done["result"]["kc_draft"]
    assert draft_path.parent.name == "drafts" and draft_path.exists()
    assert not (services.registry.data_dir / "kc_models" / course / f"kc_model_{course}.json").exists()  # not live
    draft = json.loads(draft_path.read_text())
    go = next(iter(draft["week_navigation"].values()))["learning_objectives"][0]["granular_objectives"][1]
    assert go["provenance"]["source_file"] == "Week01-ReadingA-Notes.md" and go["provenance"]["similarity"] == 0.75
    assert len(done["result"]["verify"]["weak_support"]) == 1  # the fake "Weak coverage objective"
    assert any("Chunking and embedding" in line for line in done["log"])
    assert client.get("/teach/courses", headers=headers).json()[0]["active_job"] is None
    assert [j["id"] for j in client.get(f"/teach/courses/{course}/jobs", headers=headers).json()] == [job["id"]]


def test_a_rerun_removes_deleted_files_from_the_index(client, teacher, course, services, fake_pipeline):
    _, headers = teacher
    ready(client, headers, course)
    for _ in range(2):
        job = client.post(f"/teach/courses/{course}/jobs", json={"steps": ["convert", "embed"]}, headers=headers).json()
        client.post(f"/teach/jobs/{job['id']}/confirm", headers=headers)
        services.jobs.run_next()
        client.delete(f"/teach/courses/{course}/uploads/notes.md", headers=headers)
    assert FakeProcessor.instances[-1].collection.deleted == ["Week01-ReadingA-Notes.md"]
    assert not (services.registry.data_dir / "org_docs" / course / "Week01-ReadingA-Notes.md").exists()


def test_cancelling_before_and_during_a_run(client, teacher, course, services, fake_pipeline):
    username, headers = teacher
    ready(client, headers, course)
    job = client.post(f"/teach/courses/{course}/jobs", json={}, headers=headers).json()
    assert client.post(f"/teach/jobs/{job['id']}/cancel", headers=headers).json()["status"] == "cancelled"
    assert client.post(f"/teach/jobs/{job['id']}/cancel", headers=headers).status_code == 409

    job = client.post(f"/teach/courses/{course}/jobs", json={}, headers=headers).json()  # the course is free again
    client.post(f"/teach/jobs/{job['id']}/confirm", headers=headers)
    original = fake_pipeline.processor_factory

    def cancelling(code, data_dir):
        p = original(code, data_dir)
        p.on_file = lambda name: services.jobs.cancel(username, job["id"])
        return p

    fake_pipeline.processor_factory = cancelling
    services.jobs.run_next()
    after = client.get(f"/teach/jobs/{job['id']}", headers=headers).json()
    assert after["status"] == "cancelled" and len(FakeProcessor.instances[-1].processed) == 1
    assert services.jobs.active(course) is None


def test_a_failed_step_is_reported_and_frees_the_course(client, teacher, course, services, fake_pipeline):
    _, headers = teacher
    ready(client, headers, course)

    def broken(ctx):
        raise ValueError("The model service is unavailable.")

    fake_pipeline.kc_builder = broken
    job = client.post(f"/teach/courses/{course}/jobs", json={}, headers=headers).json()
    client.post(f"/teach/jobs/{job['id']}/confirm", headers=headers)
    services.jobs.run_next()
    failed = client.get(f"/teach/jobs/{job['id']}", headers=headers).json()
    assert failed["status"] == "failed" and "unavailable" in failed["error"] and failed["step"] == "kc_draft"
    assert failed["result"]["staged"] == 3  # the earlier steps' results are kept
    assert services.jobs.active(course) is None


def test_jobs_need_materials_and_objectives(client, teacher, course):
    _, headers = teacher
    r = client.post(f"/teach/courses/{course}/jobs", json={}, headers=headers)
    assert r.status_code == 400 and "Upload" in r.json()["detail"]
    upload(client, headers, course, [("notes.md", MD, "text/markdown")])
    r = client.post(f"/teach/courses/{course}/jobs", json={}, headers=headers)
    assert r.status_code == 400 and "objectives" in r.json()["detail"]
    assert client.post(f"/teach/courses/{course}/jobs", json={"steps": ["convert", "embed"]},
                       headers=headers).status_code == 201
    assert client.post(f"/teach/courses/{course}/jobs", json={"steps": ["nonsense"]}, headers=headers).status_code == 422


def test_a_job_left_running_by_a_restart_is_marked_failed(client, teacher, course, services):
    _, headers = teacher
    upload(client, headers, course, [("notes.md", MD, "text/markdown")])
    job = client.post(f"/teach/courses/{course}/jobs", json={"steps": ["convert"]}, headers=headers).json()
    services.redis_client.get_redis().hset(f"job:{job['id']}", "status", "running")
    services.jobs.recover()
    after = client.get(f"/teach/jobs/{job['id']}", headers=headers).json()
    assert after["status"] == "failed" and "stopped" in after["error"] and services.jobs.active(course) is None


def test_another_teacher_cant_see_or_control_a_job(client, teacher, course, services, fake_pipeline):
    _, headers = teacher
    upload(client, headers, course, [("notes.md", MD, "text/markdown")])
    job = client.post(f"/teach/courses/{course}/jobs", json={"steps": ["convert"]}, headers=headers).json()
    other, other_headers = register_and_login(client)
    services.redis_client.get_redis().hset(f"user:{other}", "role", "teacher")
    for method, path in [("get", ""), ("post", "/confirm"), ("post", "/cancel")]:
        assert client.request(method, f"/teach/jobs/{job['id']}{path}", headers=other_headers).status_code == 403
    assert client.get(f"/teach/jobs/{uuid.uuid4().hex[:12]}", headers=headers).status_code == 404


# ---------------------------------------------------------------------------- pipeline pieces


def test_the_estimate_counts_what_costs_money(tmp_path):
    folder = tmp_path / "course_uploads" / "ABC101"
    folder.mkdir(parents=True)
    (folder / "slides.pptx").write_bytes(pptx(5))
    (folder / "notes.md").write_bytes(MD)
    uploads = {"slides.pptx": {"size": 2_000_000}, "notes.md": {"size": 100}, "talk.mp4": {"size": 10}}
    ctx = JobContext(job_id="j", course="ABC101", data_dir=tmp_path, meta={}, uploads=uploads, plan=plan_for(3))
    est = estimate(ctx, ["convert", "transcribe", "embed", "kc_draft", "profile", "verify"])
    assert est["images"] == 5 and est["documents"] == 2 and est["media"] == 1 and est["model_calls"] == 9
    assert est["per_step"]["kc_draft"] == 0.09 and est["per_step"]["embed"] == round(2 * 0.003 + 5 * 0.004 + 2.0001 * 0.0005, 3)
    assert estimate(ctx, ["convert"])["usd"] == 0


def test_objective_titles_replace_the_generators_names():
    go = {"go_id": "GO_01_01_001", "description": "Students will explain X and its role in wrongname. "
                                                  "This includes understanding wrongname, Basics.",
          "conceptual_tags": ["wrongname", "Basics"]}
    model = {"week_navigation": {"week_01": {"learning_objectives": [
        {"lo_id": "LO_01_01", "title": "WrongName", "short_title": "WrongName", "granular_objectives": [dict(go)]}]}},
        "quick_lookup": {"lo_by_id": {"LO_01_01": {"lo_id": "LO_01_01", "title": "WrongName"}},
                         "go_by_id": {"GO_01_01_001": dict(go)}}}
    apply_objective_titles(model, {"weeks": [{"week": 1, "title": "T", "objectives": ["Explain the right thing"]}]})
    lo = model["week_navigation"]["week_01"]["learning_objectives"][0]
    assert lo["title"] == "Explain the right thing" and lo["short_title"] == ""
    assert "wrongname" not in json.dumps(model).lower()
    with pytest.raises(ValueError):
        apply_objective_titles(model, {"weeks": [{"week": 1, "title": "T", "objectives": ["a" * 20, "b" * 20]}]})


def test_a_file_name_that_states_its_week_and_kind_is_read_and_not_doubled():
    assert F.infer_week_kind("Week03-Lecture-Backprop.pptx") == (3, "Lecture")
    assert F.infer_week_kind("week 2 lab notes.md") == (2, "Lab")
    assert F.infer_week_kind("Week04-ReadingB-Intro.md") == (4, "Reading")
    assert F.infer_week_kind("Week05.md") == (5, None)
    assert F.infer_week_kind("Weekly-plan.md") == (None, None)
    assert F.infer_week_kind("chapter_01.md") == (None, None)
    assert F.staged_name(1, "Reading", "A", "Week01-Reading-Positive-Psychology.md") == "Week01-ReadingA-Positive-Psychology.md"
    assert F.staged_name(1, "Reading", "A", "Week01-ReadingA-Positive-Psychology.md") == "Week01-ReadingA-Positive-Psychology.md"
    assert F.staged_name(2, "Lab", "A", "Week02.md") == "Week02-LabA-Week02.md"  # nothing left after the prefix: keep it
