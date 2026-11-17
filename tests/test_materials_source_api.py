"""Linked materials sources: link/unlink, permissions, sync preview, and a Build job that
actually ingests a linked folder's files alongside uploads."""

import json

import pytest

from tests.test_api import register_and_login
from tests.test_onboarding import course, fake_pipeline, new_code, plan_for, teacher  # noqa: F401 (shared fixtures)


@pytest.fixture
def materials_root(tmp_path, monkeypatch):
    monkeypatch.setenv("LEA_COURSE_MATERIALS_ROOT", str(tmp_path))
    return tmp_path


@pytest.fixture
def linked_folder(materials_root, course):
    folder = materials_root / course
    folder.mkdir()
    return folder


def write(folder, name, content=b"# Chapter\n\nSome real teaching content.\n"):
    (folder / name).write_bytes(content)
    return folder / name


def test_linking_requires_a_real_folder_under_the_root(client, teacher, course, materials_root):
    _, headers = teacher
    r = client.post(f"/teach/courses/{course}/materials-source", json={"type": "folder", "path": "NOPE"},
                    headers=headers)
    assert r.status_code == 400


def test_link_view_and_unlink(client, teacher, course, linked_folder):
    _, headers = teacher
    write(linked_folder, "chapter_01.md")

    r = client.post(f"/teach/courses/{course}/materials-source",
                    json={"type": "folder", "path": course}, headers=headers)
    assert r.status_code == 201 and r.json() == {"type": "folder", "path": course}

    r = client.get(f"/teach/courses/{course}/materials-source", headers=headers)
    assert r.status_code == 200 and r.json() == {"type": "folder", "path": course}

    assert client.delete(f"/teach/courses/{course}/materials-source", headers=headers).status_code == 204
    r = client.get(f"/teach/courses/{course}/materials-source", headers=headers)
    assert r.status_code == 200 and r.json() is None


def test_only_owners_and_admins_can_link_or_view(client, teacher, course, linked_folder):
    other, other_headers = register_and_login(client)
    for method, path in [
        ("post", f"/teach/courses/{course}/materials-source"),
        ("get", f"/teach/courses/{course}/materials-source"),
        ("delete", f"/teach/courses/{course}/materials-source"),
        ("get", f"/teach/courses/{course}/materials-source/sync-preview"),
    ]:
        r = client.request(method, path, json={"type": "folder", "path": course}, headers=other_headers)
        assert r.status_code == 403, (method, path, r.text)


def test_materials_folders_lists_root_subfolders(client, teacher, materials_root):
    (materials_root / "AIML101").mkdir()
    (materials_root / "PSYC101").mkdir()
    (materials_root / "_scratch").mkdir()
    _, headers = teacher
    r = client.get("/teach/materials-folders", headers=headers)
    assert r.status_code == 200
    assert {f["name"] for f in r.json()} == {"AIML101", "PSYC101"}


def test_sync_preview_shows_new_changed_unchanged_removed_and_rejected(client, teacher, course, linked_folder):
    _, headers = teacher
    write(linked_folder, "chapter_01.md", b"v1")
    write(linked_folder, "video.mov")  # rejected: not an allowed type
    client.post(f"/teach/courses/{course}/materials-source", json={"type": "folder", "path": course}, headers=headers)

    preview = client.get(f"/teach/courses/{course}/materials-source/sync-preview", headers=headers).json()
    statuses = {e["relpath"]: e["status"] for e in preview["entries"]}
    assert statuses["chapter_01.md"] == "new" and statuses["video.mov"] == "rejected"
    assert preview["new"] == 1 and preview["rejected"] == 1

    # Sync via a job: chapter_01.md becomes an ordinary upload.
    client.put(f"/teach/courses/{course}/objectives", json=plan_for(2), headers=headers)
    r = client.post(f"/teach/courses/{course}/jobs", json={"steps": ["convert"]}, headers=headers)
    assert r.status_code == 201, r.text
    uploads = client.get(f"/teach/courses/{course}/uploads", headers=headers).json()
    assert {u["name"]: u["linked_relpath"] for u in uploads} == {"chapter_01.md": "chapter_01.md"}

    # Unchanged next time.
    preview = client.get(f"/teach/courses/{course}/materials-source/sync-preview", headers=headers).json()
    assert {e["relpath"]: e["status"] for e in preview["entries"] if e["status"] != "rejected"} == {
        "chapter_01.md": "unchanged"}

    # Changed content -> "changed".
    write(linked_folder, "chapter_01.md", b"v2, different content")
    preview = client.get(f"/teach/courses/{course}/materials-source/sync-preview", headers=headers).json()
    assert next(e for e in preview["entries"] if e["relpath"] == "chapter_01.md")["status"] == "changed"

    # Removed from the folder -> "removed".
    (linked_folder / "chapter_01.md").unlink()
    preview = client.get(f"/teach/courses/{course}/materials-source/sync-preview", headers=headers).json()
    assert next(e for e in preview["entries"] if e["relpath"] == "chapter_01.md")["status"] == "removed"


def test_a_build_job_removes_uploads_whose_linked_file_is_gone(client, teacher, course, linked_folder, services):
    _, headers = teacher
    write(linked_folder, "chapter_01.md")
    client.post(f"/teach/courses/{course}/materials-source", json={"type": "folder", "path": course}, headers=headers)
    client.put(f"/teach/courses/{course}/objectives", json=plan_for(2), headers=headers)
    client.post(f"/teach/courses/{course}/jobs", json={"steps": ["convert"]}, headers=headers)
    assert "chapter_01.md" in services.setup.uploads(course)

    (linked_folder / "chapter_01.md").unlink()
    counts = services.setup.sync_materials_source(teacher[0], course)
    assert counts["removed"] == 1
    assert "chapter_01.md" not in services.setup.uploads(course)


def test_uploads_alongside_a_linked_source_both_survive_sync(client, teacher, course, linked_folder):
    """Uploads keep working alongside a linked source (not replaced by it)."""
    _, headers = teacher
    client.post(f"/teach/courses/{course}/uploads", files=[("files", ("manual.md", b"# Manual notes", "text/markdown"))],
               headers=headers)
    write(linked_folder, "chapter_01.md")
    client.post(f"/teach/courses/{course}/materials-source", json={"type": "folder", "path": course}, headers=headers)
    client.put(f"/teach/courses/{course}/objectives", json=plan_for(2), headers=headers)
    client.post(f"/teach/courses/{course}/jobs", json={"steps": ["convert"]}, headers=headers)

    uploads = client.get(f"/teach/courses/{course}/uploads", headers=headers).json()
    names = {u["name"]: u["linked_relpath"] for u in uploads}
    assert names == {"manual.md": None, "chapter_01.md": "chapter_01.md"}


def test_linking_and_unlinking_go_to_the_event_log_as_staff_actions(client, teacher, course, linked_folder, services):
    _, headers = teacher
    client.post(f"/teach/courses/{course}/materials-source", json={"type": "folder", "path": course}, headers=headers)
    client.delete(f"/teach/courses/{course}/materials-source", headers=headers)
    rows = services.events.log.query("actor IS NOT NULL AND type LIKE 'materials_source%'")
    assert [r["type"] for r in rows] == ["materials_source_link", "materials_source_unlink"]
    assert json.loads(rows[0]["payload_json"]) == {"type": "folder", "path": course}


def test_sync_reads_the_week_and_kind_a_linked_file_name_states(client, teacher, course, linked_folder, services):
    _, headers = teacher
    write(linked_folder, "Week02-Lab-Notes.md")
    write(linked_folder, "Week09-Reading-Beyond-The-Course.md")  # the course has 2 weeks
    write(linked_folder, "plain.md")
    client.post(f"/teach/courses/{course}/materials-source", json={"type": "folder", "path": course}, headers=headers)
    client.put(f"/teach/courses/{course}/objectives", json=plan_for(2), headers=headers)
    client.post(f"/teach/courses/{course}/jobs", json={"steps": ["convert"]}, headers=headers)
    uploads = services.setup.uploads(course)
    assert (uploads["Week02-Lab-Notes.md"]["week"], uploads["Week02-Lab-Notes.md"]["kind"]) == (2, "Lab")
    assert uploads["Week09-Reading-Beyond-The-Course.md"]["week"] is None
    assert uploads["Week09-Reading-Beyond-The-Course.md"]["kind"] == "Reading"
    assert (uploads["plain.md"]["week"], uploads["plain.md"]["kind"]) == (None, "Reading")


def test_a_build_keeps_the_linked_folder_in_the_course_profile(client, teacher, course, linked_folder, services,
                                                               fake_pipeline):
    """The build's profile step rewrote the profile and silently dropped the link (found when building a course)."""
    _, headers = teacher
    write(linked_folder, "chapter_01.md")
    client.post(f"/teach/courses/{course}/materials-source", json={"type": "folder", "path": course}, headers=headers)
    client.put(f"/teach/courses/{course}/objectives", json=plan_for(2), headers=headers)
    job = client.post(f"/teach/courses/{course}/jobs", json={"steps": ["profile"]}, headers=headers).json()
    client.post(f"/teach/jobs/{job['id']}/confirm", headers=headers)
    assert services.jobs.run_next() is True
    profile = json.loads((services.registry.data_dir / "course_profiles" / f"{course}.json").read_text(encoding="utf-8"))
    assert profile["materials_source"] == {"type": "folder", "path": course}
    assert profile["discipline"] == "computing" and profile["allows_code"] is True  # the build's own fields still apply
    services.registry.forget(course)
    assert client.get(f"/teach/courses/{course}/materials-source", headers=headers).json() == {"type": "folder", "path": course}
