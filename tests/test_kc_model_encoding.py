"""A published model with curly quotes or accented letters must load on Windows, where the default file
encoding is not UTF-8 (found when a course's first published model could not be opened)."""

import json

import fakeredis

from src.core.kc_model_loader import KCModelLoader


def test_a_kc_model_with_non_ascii_text_loads(tmp_path):
    course_dir = tmp_path / "ENC101"
    course_dir.mkdir()
    model = {"course_info": {"course_code": "ENC101", "course_name": "Caf\u00e9 \u201cquoted\u201d course", "total_weeks": 1},
             "week_navigation": {}}
    (course_dir / "kc_model_ENC101.json").write_text(json.dumps(model, ensure_ascii=False), encoding="utf-8")
    loader = KCModelLoader(fakeredis.FakeStrictRedis(), "ENC101", kc_model_path=str(tmp_path))
    loaded = loader.load_course_model("ENC101")
    assert loaded["course_info"]["course_name"] == "Caf\u00e9 \u201cquoted\u201d course"
