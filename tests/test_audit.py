"""B5: the content audit (checks, ranking, runs, decisions, API)."""

import io
import json
import os
import zipfile

import pytest
from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Inches

from src.onboarding import audit_checks as A
from src.storage.event_log import EventLog
from tests.conftest import FIXTURE_DATA
from tests.test_api import register_and_login
from tests.test_onboarding import new_code

DEMO = json.loads((FIXTURE_DATA / "kc_models/DEMO101/kc_model_DEMO101.json").read_text())

MINIMAL_PDF = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
               b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n")


def deck(path, *, alt=False, title=True, pale_text=False, words=10):
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5 if title else 6])
    if title:
        slide.shapes.title.text = "Perceptrons"
    img = io.BytesIO()
    Image.new("RGB", (10, 10), "red").save(img, "PNG")
    img.seek(0)
    pic = slide.shapes.add_picture(img, Inches(1), Inches(1))
    if alt:
        pic._element.xpath("./p:nvPicPr/p:cNvPr")[0].set("descr", "A red square")
    box = slide.shapes.add_textbox(Inches(1), Inches(3), Inches(5), Inches(2))
    box.fill.solid()
    box.fill.fore_color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    run = box.text_frame.paragraphs[0].add_run()
    run.text = " ".join(["word"] * words)
    if pale_text:
        run.font.color.rgb = RGBColor(0xDD, 0xDD, 0xDD)
    prs.save(path)


def docx(path, *, alt=False, headings=False, paragraphs=30):
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    wp = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
    style = '<w:pPr><w:pStyle w:val="Heading1"/></w:pPr>' if headings else ""
    body = "".join(f"<w:p>{style if i == 0 else ''}<w:r><w:t>Para {i}</w:t></w:r></w:p>" for i in range(paragraphs))
    descr = ' descr="x"' if alt else ""
    drawing = f'<w:p><w:r><w:drawing><wp:inline><wp:docPr id="1" name="p"{descr}/></wp:inline></w:drawing></w:r></w:p>'
    xml = f'<w:document xmlns:w="{w}" xmlns:wp="{wp}"><w:body>{body}{drawing}</w:body></w:document>'
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", xml)


# ---------------------------------------------------------------------------- checks


def test_slides_are_checked_for_alt_text_titles_contrast_and_density(tmp_path):
    deck(tmp_path / "bad.pptx", title=False, pale_text=True, words=120)
    deck(tmp_path / "good.pptx", alt=True)
    found = A.check_files(tmp_path)
    titles = {f["title"] for f in found}
    assert "1 picture(s) in bad.pptx have no text alternative" in titles
    assert "Low-contrast text in bad.pptx" in titles
    assert "1 dense slide(s) in bad.pptx" in titles
    assert not any("good.pptx" in t for t in titles)
    alt = next(f for f in found if "text alternative" in f["title"])
    assert alt["severity"] == "high" and alt["tier"] == "well_supported" and alt["target"] == {"kind": "file", "ref": "bad.pptx"}
    assert A.contrast_ratio("DDDDDD", "FFFFFF") < 4.5 < A.contrast_ratio("000000", "FFFFFF")


def test_word_pdf_and_media_are_checked(tmp_path):
    docx(tmp_path / "notes.docx")
    docx(tmp_path / "fine.docx", alt=True, headings=True)
    (tmp_path / "scan.pdf").write_bytes(MINIMAL_PDF)
    (tmp_path / "talk.mp4").write_bytes(b"")
    (tmp_path / "lab.mp4").write_bytes(b"")
    (tmp_path / "lab.vtt").write_text("WEBVTT")
    titles = {f["title"] for f in A.check_files(tmp_path)}
    assert {"1 picture(s) in notes.docx have no text alternative", "notes.docx has no headings",
            "scan.pdf looks scanned (no text layer)", "talk.mp4 has no caption file"} <= titles
    assert not any("fine.docx" in t or "lab.mp4" in t for t in titles)


def test_question_writing_rules():
    q = lambda i, text, opts, right=0, t="multiple_choice": {"id": i, "text": text, "options": opts,  # noqa: E731
                                                             "correct_index": right, "type": t}
    bank = {"questions": [
        q("neg", "Which of these is not supervised learning?", ["a", "b", "c"]),
        q("all", "Loss functions include", ["MSE", "Cross entropy", "All of the above"], 2),
        q("long", "A perceptron is", ["a single-layer linear classifier with a step activation", "a tree", "a bus"]),
        q("clue", "Gradient descent minimises the training loss by", ["following the gradient of the training loss", "luck", "votes"]),
        q("ok", "Least-Squares Regression fits a line by", ["minimising squared errors", "maximising the error", "sorting the points"]),
        q("tf", "The perceptron can not learn XOR", ["True", "False"], 0, "true_false"),
    ]}
    found = A.check_questions(bank)
    flagged = {(f["target"]["ref"], f["key"]) for f in found}
    refs = [r for r, _ in flagged]
    assert "neg" in refs and "all" in refs and "long" in refs and "clue" in refs
    assert "ok" not in refs and "tf" not in refs  # "least squares" and true/false stems aren't flaws
    assert len({f["key"] for f in A.check_questions(bank)}) == len(found)  # keys are stable


def test_model_checks_bloom_prerequisites_and_alignment():
    model = json.loads(json.dumps(DEMO))
    gos = [g for w in model["week_navigation"].values() for lo in w["learning_objectives"] for g in lo["granular_objectives"]]
    week1 = [g for g in gos if g["go_id"].startswith("GO_01_")]
    for g in week1:
        g["cognitive_level"] = "Understand"
    later = next(g for g in gos if g["go_id"].startswith("GO_03_"))
    week1[0]["prerequisites"] = [later["go_id"]]
    assert any(f["title"] == "Week 1 is mostly “Understand”" for f in A.check_bloom_balance(model))
    order = A.check_prerequisite_order(model)
    assert len(order) == 1 and order[0]["tier"] == "rule_based" and later["go_id"] in order[0]["evidence"]
    bank = {"questions": [{"go_id": g["go_id"]} for g in gos if not g["go_id"].startswith("GO_02_")]}
    assert {f["check"] for f in A.check_alignment(model, bank)} == {"alignment"}


def test_coverage_is_calibrated_per_course_and_redundancy_compares_objectives():
    rows = [g["go_id"] for w in DEMO["week_navigation"].values() for lo in w["learning_objectives"] for g in lo["granular_objectives"]]
    weak = rows[3]
    sims = {g: (0.2 if g == weak else 0.7 + 0.01 * (i % 5)) for i, g in enumerate(rows)}
    names = {g["skill_name"]: g["go_id"] for w in DEMO["week_navigation"].values() for lo in w["learning_objectives"]
             for g in lo["granular_objectives"]}
    cov = A.check_coverage(DEMO, lambda text: (sims[names[text.split(". ")[0]]], "Week01-Notes.md"))
    assert [f["target"]["ref"] for f in cov] == [weak] and cov[0]["tier"] == "experimental"

    first, second = rows[0], rows[1]
    def one_hot(texts):  # the first two identical, every other one distinct
        return [[1.0 if j == max(i, 1) else 0.0 for j in range(len(texts))] for i in range(len(texts))]

    red = A.check_redundancy(DEMO, one_hot)
    assert len(red) == 1 and first in red[0]["evidence"] and second in red[0]["evidence"]


def test_ranking_puts_severe_and_larger_problems_first_and_caps_each_check():
    many = [A.finding("accessibility", [i], "high", f"{i} pictures", "", "", "file", str(i), "well_supported", weight=i)
            for i in range(1, 21)]
    ranked = A.rank(many + [A.finding("readability", ["x"], "info", "dense", "", "", "file", "x", "informational")])
    assert len([f for f in ranked if f["check"] == "accessibility"]) == A.MAX_PER_CHECK
    assert ranked[0]["weight"] == 20 and ranked[-1]["check"] == "readability"


# ---------------------------------------------------------------------------- runs, decisions, API


@pytest.fixture
def teacher(client, services):
    username, headers = register_and_login(client)
    services.redis_client.get_redis().hset(f"user:{username}", "role", "teacher")
    services.staff.add_owner("admin", "DEMO101", username)
    services.audit._embed = lambda texts: [[float(i), 1.0] for i in range(len(texts))]
    services.audit._search = lambda code, text: (0.7, "Week01-Notes.md")
    return username, headers


def test_a_run_ranks_findings_and_decisions_carry_over(client, teacher, services, monkeypatch):
    username, headers = teacher
    assert client.get("/teach/courses/DEMO101/audit", headers=headers).json() is None
    est = client.get("/teach/courses/DEMO101/audit/estimate", headers=headers).json()
    assert est["objectives"] == 32 and est["usd"] < 0.01

    extra = A.finding("questions", ["q1", "neg"], "medium", "Question q1: negative", "why", "stem", "question", "q1", "well_supported")
    monkeypatch.setattr(A, "check_questions", lambda bank: [extra])
    r = client.post("/teach/courses/DEMO101/audit/runs", headers=headers)
    assert r.status_code == 201, r.text
    run = r.json()
    assert run["total"] == len(run["findings"]) >= 1 and run["skipped"] == [] and run["kc_version"] == 0
    key = extra["key"]
    assert next(f for f in run["findings"] if f["key"] == key)["status"] == "open"

    r = client.put(f"/teach/courses/DEMO101/audit/findings/{key}", json={"status": "dismissed", "note": "intended"},
                   headers=headers)
    assert r.json()["status"] == "dismissed" and r.json()["note"] == "intended"
    again = client.post("/teach/courses/DEMO101/audit/runs", headers=headers).json()
    kept = next(f for f in again["findings"] if f["key"] == key)
    assert kept["status"] == "dismissed" and kept["note"] == "intended" and kept["new"] is False
    assert again["reviewed"] == 1

    monkeypatch.setattr(A, "check_questions", lambda bank: [])
    third = client.post("/teach/courses/DEMO101/audit/runs", headers=headers).json()
    assert {x["key"] for x in third["resolved_since_last"]} == {key}
    assert len(client.get("/teach/courses/DEMO101/audit/runs", headers=headers).json()) == 3
    assert client.put(f"/teach/courses/DEMO101/audit/findings/{key}", json={"status": "accepted"},
                      headers=headers).status_code == 404  # not in the latest run

    audit = EventLog(os.environ["LEA_EVENTS_DB"]).query("type LIKE 'audit_%'")
    assert [e["type"] for e in audit] == ["audit_run", "audit_dismissed", "audit_run", "audit_run"]
    assert json.loads(audit[1]["payload_json"])["check"] == "questions" and audit[1]["actor"] == username


def test_embedding_failures_skip_two_checks_not_the_audit(client, teacher, services):
    _, headers = teacher

    def broken(code, text):
        raise RuntimeError("no network")

    services.audit._search = broken
    run = client.post("/teach/courses/DEMO101/audit/runs", headers=headers).json()
    assert run["skipped"] and "no network" in run["skipped"][0]


def test_the_audit_needs_a_published_model_and_ownership(client, teacher, services):
    _, headers = teacher
    code = new_code()
    client.post("/teach/courses", json={"code": code, "name": "X", "discipline": "computing", "weeks": 1}, headers=headers)
    r = client.post(f"/teach/courses/{code}/audit/runs", headers=headers)
    assert r.status_code == 400 and "Publish" in r.json()["detail"]
    other, other_headers = register_and_login(client)
    services.redis_client.get_redis().hset(f"user:{other}", "role", "teacher")
    assert client.post("/teach/courses/DEMO101/audit/runs", headers=other_headers).status_code == 403
    assert client.get("/teach/courses/DEMO101/audit", headers=other_headers).status_code == 403


def test_admins_can_mark_test_accounts(client, services):
    admin, admin_headers = register_and_login(client)
    services.redis_client.get_redis().hset(f"user:{admin}", "role", "admin")
    student, _ = register_and_login(client)
    r = client.patch(f"/admin/users/{student}", json={"session_kind": "test"}, headers=admin_headers)
    assert r.status_code == 200 and r.json()["session_kind"] == "test"
    assert services.events.session_kind(student) == "test"
