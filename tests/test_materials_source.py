"""FolderMaterialsSource: read-only, stays inside the root, skips what should never be
ingested. See src/onboarding/materials_source.py."""

import hashlib

import pytest

from src.onboarding import files as F
from src.onboarding.materials_source import (FolderMaterialsSource, FolderSourceError, available_subfolders,
                                             materials_root)


@pytest.fixture
def root(tmp_path):
    return tmp_path / "root"


@pytest.fixture
def course_dir(root):
    d = root / "PSYC101"
    d.mkdir(parents=True)
    return d


def write(path, name, content=b"hello world"):
    (path / name).write_bytes(content)
    return path / name


def test_lists_allowed_files_with_size_and_sha256(course_dir, root):
    write(course_dir, "chapter_01.md", b"# Chapter 1\ncontent")
    source = FolderMaterialsSource("PSYC101", root=root)
    files = source.list_files()
    assert len(files) == 1
    f = files[0]
    assert f.relpath == "chapter_01.md" and f.size == len(b"# Chapter 1\ncontent")
    assert f.sha256 == hashlib.sha256(b"# Chapter 1\ncontent").hexdigest()


def test_nested_files_use_a_relative_posix_path(course_dir, root):
    (course_dir / "unit1").mkdir()
    write(course_dir / "unit1", "notes.txt")
    source = FolderMaterialsSource("PSYC101", root=root)
    assert [f.relpath for f in source.list_files()] == ["unit1/notes.txt"]


@pytest.mark.parametrize("bad_path", ["..", "../PSYC101", "PSYC101/../../etc", "/etc/passwd"])
def test_path_traversal_and_absolute_paths_are_refused(root, bad_path):
    with pytest.raises(FolderSourceError):
        FolderMaterialsSource(bad_path, root=root)


def test_a_folder_outside_the_root_is_refused(tmp_path, root):
    outside = tmp_path / "outside"
    outside.mkdir()
    root.mkdir(parents=True, exist_ok=True)
    with pytest.raises(FolderSourceError):
        FolderMaterialsSource(str(outside), root=root)


def test_a_missing_folder_is_refused(root):
    root.mkdir(parents=True, exist_ok=True)
    with pytest.raises(FolderSourceError):
        FolderMaterialsSource("NOPE101", root=root)


def test_underscored_folders_are_never_ingested_or_listed_as_rejected(course_dir, root):
    teacher_dir = course_dir / "_teacher" / "reference_questions"
    teacher_dir.mkdir(parents=True)
    write(teacher_dir, "answers.md")
    write(course_dir, "chapter_01.md")
    source = FolderMaterialsSource("PSYC101", root=root)
    assert [f.relpath for f in source.list_files()] == ["chapter_01.md"]
    assert source.rejected_files() == []  # invisible, not rejected


def test_hidden_files_and_folders_are_never_ingested_or_listed_as_rejected(course_dir, root):
    write(course_dir, ".DS_Store")
    (course_dir / ".git").mkdir()
    write(course_dir / ".git", "config")
    write(course_dir, "chapter_01.md")
    source = FolderMaterialsSource("PSYC101", root=root)
    assert [f.relpath for f in source.list_files()] == ["chapter_01.md"]
    assert source.rejected_files() == []


def test_disallowed_extensions_are_rejected_with_a_reason(course_dir, root):
    write(course_dir, "video.mov")
    source = FolderMaterialsSource("PSYC101", root=root)
    assert source.list_files() == []
    [rejected] = source.rejected_files()
    assert rejected.relpath == "video.mov" and "type" in rejected.reason


def test_an_oversized_file_is_rejected(course_dir, root, monkeypatch):
    monkeypatch.setattr(F, "MAX_FILE_BYTES", 10)
    write(course_dir, "big.txt", b"x" * 11)
    source = FolderMaterialsSource("PSYC101", root=root)
    assert source.list_files() == []
    [rejected] = source.rejected_files()
    assert "MB" in rejected.reason


def test_an_empty_file_is_rejected(course_dir, root):
    write(course_dir, "empty.txt", b"")
    source = FolderMaterialsSource("PSYC101", root=root)
    assert source.list_files() == []
    assert source.rejected_files()[0].reason == "empty file"


def test_a_symlinked_file_pointing_outside_the_root_is_rejected(tmp_path, course_dir, root):
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"secret")
    link = course_dir / "linked.txt"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks aren't permitted on this machine")
    source = FolderMaterialsSource("PSYC101", root=root)
    assert source.list_files() == []
    [rejected] = source.rejected_files()
    assert rejected.relpath == "linked.txt" and "outside" in rejected.reason


def test_a_symlinked_file_pointing_inside_the_root_is_accepted(course_dir, root):
    real = write(course_dir, "real.md")
    link = course_dir / "linked.md"
    try:
        link.symlink_to(real)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks aren't permitted on this machine")
    source = FolderMaterialsSource("PSYC101", root=root)
    names = {f.relpath for f in source.list_files()}
    assert "linked.md" in names and "real.md" in names


def test_a_symlinked_directory_pointing_outside_the_root_is_never_walked_into(tmp_path, course_dir, root):
    outside = tmp_path / "outside_dir"
    outside.mkdir()
    write(outside, "secret.txt")
    link_dir = course_dir / "linked_dir"
    try:
        link_dir.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks aren't permitted on this machine")
    source = FolderMaterialsSource("PSYC101", root=root)
    assert source.list_files() == []


def test_read_bytes_returns_the_file_contents(course_dir, root):
    write(course_dir, "chapter_01.md", b"content here")
    source = FolderMaterialsSource("PSYC101", root=root)
    assert source.read_bytes("chapter_01.md") == b"content here"


def test_read_bytes_refuses_to_escape_the_folder(course_dir, root):
    source = FolderMaterialsSource("PSYC101", root=root)
    with pytest.raises(FolderSourceError):
        source.read_bytes("../../outside.txt")


def test_fingerprint_matches_list_files_and_changes_with_content(course_dir, root):
    write(course_dir, "chapter_01.md", b"v1")
    source = FolderMaterialsSource("PSYC101", root=root)
    fp1 = source.fingerprint("chapter_01.md")
    assert fp1 == hashlib.sha256(b"v1").hexdigest()

    write(course_dir, "chapter_01.md", b"v2")
    source2 = FolderMaterialsSource("PSYC101", root=root)  # a fresh scan, like a new request
    assert source2.fingerprint("chapter_01.md") != fp1


def test_available_subfolders_excludes_hidden_and_underscored_and_files(root):
    root.mkdir(parents=True, exist_ok=True)
    (root / "PSYC101").mkdir()
    (root / "AIML101").mkdir()
    (root / "_scratch").mkdir()
    (root / ".cache").mkdir()
    (root / "readme.txt").write_bytes(b"x")
    assert available_subfolders(root) == ["AIML101", "PSYC101"]


def test_available_subfolders_is_empty_for_a_missing_root(tmp_path):
    assert available_subfolders(tmp_path / "does-not-exist") == []


def test_materials_root_reads_the_env_var(monkeypatch, tmp_path):
    monkeypatch.setenv("LEA_COURSE_MATERIALS_ROOT", str(tmp_path))
    assert materials_root() == tmp_path


def test_materials_root_defaults_when_unset(monkeypatch):
    monkeypatch.delenv("LEA_COURSE_MATERIALS_ROOT", raising=False)
    assert str(materials_root()).endswith("course_materials")
