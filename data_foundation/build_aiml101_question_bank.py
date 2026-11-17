"""Build AIML101's reference question bank from the two curricula's quiz apps.

    python data_foundation/build_aiml101_question_bank.py <sources>

Reads the English quiz files (AI for Beginners ``etc/quiz-app/src/assets/translations/en/
lesson-N.json``, ML for Beginners ``quiz-app/src/assets/translations/en.json``), keeps the
quizzes of AIML101's lessons, and writes ``data/course_sources/AIML101/question_bank.json``
in LEA's reference-bank format (see docs/COURSE_CREATION.md). Each question is tagged to
the most similar granular objective of its week by embedding similarity (OpenAI
text-embedding-3-small; well under a cent). Tags are suggestions until reviewed.

The bank is reference material (content audit, examples for question writing). Quiz mode
does not use it: that would change grading and item selection.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KC = ROOT / "data" / "kc_models" / "AIML101" / "kc_model_AIML101.json"
OUT = ROOT / "data" / "course_sources" / "AIML101" / "question_bank.json"

AI4B_QUIZ = "AI-For-Beginners/etc/quiz-app/src/assets/translations/en/lesson-{n}.json"
ML4B_QUIZ = "ML-For-Beginners/quiz-app/src/assets/translations/en.json"
# week -> quizzes: ("ai4b", lesson file number) or ("ml4b", quiz ids)
WEEKS = {
    1: [("ai4b", 1), ("ml4b", (3, 4))],
    2: [("ai4b", 2)],
    3: [("ml4b", (1, 2)), ("ml4b", (7, 8)), ("ml4b", (13, 14))],
    4: [("ai4b", 3)],
    5: [("ai4b", 4), ("ai4b", 5)],
    6: [("ai4b", 24), ("ml4b", (5, 6))],
}
MODEL = "text-embedding-3-small"


def is_true(value) -> bool:
    return value is True or str(value).strip().lower() == "true"


def questions_from(quiz: dict, week: int, source: dict) -> list[dict]:
    kind = "pre" if "pre" in quiz["title"].lower() else "post"
    out = []
    for i, q in enumerate(quiz["quiz"], 1):
        options = [o["answerText"].strip() for o in q["answerOptions"]]
        correct = [j for j, o in enumerate(q["answerOptions"]) if is_true(o["isCorrect"])]
        if len(correct) != 1:
            print(f"  skipped (needs exactly one correct option): {q['questionText'][:60]}")
            continue
        qtype = "true_false" if sorted(o.lower() for o in options) == ["false", "true"] else "multiple_choice"
        out.append({
            "id": f"{source['prefix']}-{quiz['id']}-{i}",
            "week": week,
            "type": qtype,
            "text": q["questionText"].strip(),
            "options": options,
            "correct_index": correct[0],
            "source": {"curriculum": source["curriculum"], "file": source["file"], "quiz_id": quiz["id"],
                       "quiz_title": quiz["title"], "kind": kind},
        })
    return out


def load(sources: Path) -> list[dict]:
    bank = []
    ml4b = {q["id"]: q for q in json.loads((sources / ML4B_QUIZ).read_text(encoding="utf-8"))[0]["quizzes"]}
    for week, quizzes in WEEKS.items():
        for kind, ref in quizzes:
            if kind == "ai4b":
                path = AI4B_QUIZ.format(n=ref)
                src = {"prefix": "AI4B", "curriculum": "AI for Beginners", "file": path}
                for quiz in json.loads((sources / path).read_text(encoding="utf-8"))[0]["quizzes"]:
                    bank += questions_from(quiz, week, src)
            else:
                src = {"prefix": "ML4B", "curriculum": "ML for Beginners", "file": ML4B_QUIZ}
                for quiz_id in ref:
                    bank += questions_from(ml4b[quiz_id], week, src)
    return bank


def tag(bank: list[dict]) -> None:
    from openai import OpenAI

    model = json.loads(KC.read_text(encoding="utf-8"))
    gos = {}  # week -> [(go_id, lo_id, text)]
    for week in model["week_navigation"].values():
        for lo in week["learning_objectives"]:
            for go in lo["granular_objectives"]:
                gos.setdefault(week["week_number"], []).append(
                    (go["go_id"], lo["lo_id"], f"{go['skill_name']}. {lo['title']}. {go['description']}"))
    client = OpenAI()
    go_texts = [t for items in gos.values() for _, _, t in items]
    q_texts = [f"{q['text']} {' / '.join(q['options'])}" for q in bank]
    vectors = client.embeddings.create(model=MODEL, input=go_texts + q_texts).data
    go_vec = dict(zip(go_texts, (v.embedding for v in vectors[:len(go_texts)])))
    for q, v in zip(bank, vectors[len(go_texts):]):
        def score(item):
            return sum(a * b for a, b in zip(v.embedding, go_vec[item[2]]))
        best = max(gos[q["week"]], key=score)
        q["go_id"], q["lo_id"] = best[0], best[1]
        q["tagging"] = {"method": f"embedding similarity ({MODEL}) within the week", "score": round(score(best), 3),
                        "reviewed": False}


def main(sources: Path) -> None:
    bank = load(sources)
    tag(bank)
    OUT.write_text(json.dumps({
        "course": "AIML101",
        "format": "lea-reference-question-bank/1",
        "note": ("Reference questions from Microsoft AI for Beginners and ML for Beginners (MIT; see "
                 "ATTRIBUTION.md). Not used by Quiz mode. GO tags are suggestions until reviewed."),
        "questions": bank,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(bank)} questions to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    if not os.getenv("OPENAI_API_KEY"):
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    main(Path(sys.argv[1]))
