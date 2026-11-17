"""Stage AIML101 (the open demo course) from Microsoft's MIT-licensed curricula.

    git clone --depth 1 https://github.com/microsoft/AI-For-Beginners   <sources>/AI-For-Beginners
    git clone --depth 1 https://github.com/microsoft/ML-For-Beginners   <sources>/ML-For-Beginners
    python data_foundation/stage_aiml101.py <sources>

Run from the repository root. Writes the lesson text to ``data/org_docs/AIML101/`` with
LEA's ``WeekNN-TypeX-Title`` names, and the licences, ``ATTRIBUTION.md`` and the staging
map to ``data/course_sources/AIML101/``. English text only. Changes made to the sources
(all recorded in ATTRIBUTION.md):

- Markdown: images, sketchnote/photo credits, video thumbnails and quiz links removed;
  links to other files in the repos reduced to their text; a source line added on top.
- Notebooks: outputs, execution counts and embedded images removed (code and text kept).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DST = ROOT / "data" / "org_docs" / "AIML101"
META = ROOT / "data" / "course_sources" / "AIML101"

AI4B = "AI-For-Beginners"
ML4B = "ML-For-Beginners"
REPO_URLS = {AI4B: "https://github.com/microsoft/AI-For-Beginners",
             ML4B: "https://github.com/microsoft/ML-For-Beginners"}
LICENCES = {  # source path -> name shipped with the course
    (AI4B, "LICENSE"): "LICENSE-AI-For-Beginners.txt",
    (ML4B, "LICENSE"): "LICENSE-ML-For-Beginners.txt",
    (ML4B, "quiz-app/LICENSE"): "LICENSE-ML-For-Beginners-quiz-app.txt",
}

# LEA name -> (repo, path). Weeks and objectives approved by the researcher, 2026-09-25.
FILES = {
    "Week01-LectureA-Introduction-To-AI.md": (AI4B, "lessons/1-Intro/README.md"),
    "Week01-LectureB-History-Of-Machine-Learning.md": (ML4B, "1-Introduction/2-history-of-ML/README.md"),
    "Week01-AssignmentA-AI-Game-Jam.md": (AI4B, "lessons/1-Intro/assignment.md"),
    "Week01-AssignmentB-History-Timeline.md": (ML4B, "1-Introduction/2-history-of-ML/assignment.md"),

    "Week02-LectureA-Knowledge-Representation-And-Expert-Systems.md": (AI4B, "lessons/2-Symbolic/README.md"),
    "Week02-LabA-Animal-Expert-System.ipynb": (AI4B, "lessons/2-Symbolic/Animals.ipynb"),
    "Week02-LabB-Family-Ontology.ipynb": (AI4B, "lessons/2-Symbolic/FamilyOntology.ipynb"),
    "Week02-LabC-Concept-Graph.ipynb": (AI4B, "lessons/2-Symbolic/MSConceptGraph.ipynb"),
    "Week02-AssignmentA-Build-An-Ontology.md": (AI4B, "lessons/2-Symbolic/assignment.md"),

    "Week03-LectureA-Introduction-To-Machine-Learning.md": (ML4B, "1-Introduction/1-intro-to-ML/README.md"),
    "Week03-LectureB-Techniques-Of-Machine-Learning.md": (ML4B, "1-Introduction/4-techniques-of-ML/README.md"),
    "Week03-LectureC-Linear-Regression.md": (ML4B, "2-Regression/3-Linear/README.md"),
    "Week03-AssignmentA-Get-Up-And-Running.md": (ML4B, "1-Introduction/1-intro-to-ML/assignment.md"),
    "Week03-AssignmentB-Interview-A-Data-Scientist.md": (ML4B, "1-Introduction/4-techniques-of-ML/assignment.md"),
    "Week03-AssignmentC-Regression-Model.md": (ML4B, "2-Regression/3-Linear/assignment.md"),

    "Week04-LectureA-Introduction-To-Neural-Networks.md": (AI4B, "lessons/3-NeuralNetworks/README.md"),
    "Week04-LectureB-Perceptron.md": (AI4B, "lessons/3-NeuralNetworks/03-Perceptron/README.md"),
    "Week04-LabA-Perceptron.ipynb": (AI4B, "lessons/3-NeuralNetworks/03-Perceptron/Perceptron.ipynb"),
    "Week04-LabB-Multi-Class-Perceptron.ipynb": (AI4B, "lessons/3-NeuralNetworks/03-Perceptron/lab/PerceptronMultiClass.ipynb"),
    "Week04-AssignmentA-Multi-Class-Perceptron.md": (AI4B, "lessons/3-NeuralNetworks/03-Perceptron/lab/README.md"),

    "Week05-LectureA-Multi-Layered-Perceptron.md": (AI4B, "lessons/3-NeuralNetworks/04-OwnFramework/README.md"),
    "Week05-LabA-Own-Framework.ipynb": (AI4B, "lessons/3-NeuralNetworks/04-OwnFramework/OwnFramework.ipynb"),
    "Week05-LabB-MNIST-With-Own-Framework.ipynb": (AI4B, "lessons/3-NeuralNetworks/04-OwnFramework/lab/MyFW_MNIST.ipynb"),
    "Week05-AssignmentA-MNIST-With-Own-Framework.md": (AI4B, "lessons/3-NeuralNetworks/04-OwnFramework/lab/README.md"),
    "Week05-LectureB-Frameworks-And-Overfitting.md": (AI4B, "lessons/3-NeuralNetworks/05-Frameworks/README.md"),
    "Week05-LabC-Intro-To-PyTorch.ipynb": (AI4B, "lessons/3-NeuralNetworks/05-Frameworks/IntroPyTorch.ipynb"),
    "Week05-LabD-Intro-To-Keras-And-TensorFlow.ipynb": (AI4B, "lessons/3-NeuralNetworks/05-Frameworks/IntroKerasTF.ipynb"),
    "Week05-LabE-Frameworks-Classification.ipynb": (AI4B, "lessons/3-NeuralNetworks/05-Frameworks/lab/LabFrameworks.ipynb"),
    "Week05-AssignmentB-Classification-With-Frameworks.md": (AI4B, "lessons/3-NeuralNetworks/05-Frameworks/lab/README.md"),

    "Week06-LectureA-Responsible-AI.md": (AI4B, "lessons/7-Ethics/README.md"),
    "Week06-LectureB-Fairness-In-Machine-Learning.md": (ML4B, "1-Introduction/3-fairness/README.md"),
    "Week06-AssignmentA-Explore-The-RAI-Toolbox.md": (ML4B, "1-Introduction/3-fairness/assignment.md"),
}

TITLES = {AI4B: "Microsoft AI for Beginners", ML4B: "Microsoft ML for Beginners"}

_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_HTML_IMG = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_EMPTY_LINK = re.compile(r"\[\s*\]\([^)]*\)")
_REL_LINK = re.compile(r"\[([^\]]+)\]\((?!https?://|mailto:)[^)]*\)")
_DROP_LINE = re.compile(
    r"(sketchnote by|photo by|infographic by|image by|illustration by|click the image above|"
    r"pre-lecture quiz|post-lecture quiz|pre-quiz|post-quiz|lecture quiz\])", re.IGNORECASE)


def clean_markdown(text: str) -> str:
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    text = _HTML_IMG.sub("", _IMAGE.sub("", text))
    text = _EMPTY_LINK.sub("", text)
    text = _REL_LINK.sub(r"\1", text)
    lines = [ln for ln in text.splitlines() if not _DROP_LINE.search(ln)]
    text = "\n".join(ln.rstrip() for ln in lines)
    text = re.sub(r"^\s*>\s*$\n?", "", text, flags=re.MULTILINE)  # quote lines left empty
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


def clean_notebook(nb: dict) -> dict:
    for cell in nb.get("cells", []):
        cell.pop("attachments", None)
        if cell.get("cell_type") == "code":
            cell["outputs"] = []
            cell["execution_count"] = None
        elif cell.get("cell_type") == "markdown":
            source = "".join(cell.get("source", []))
            cell["source"] = clean_markdown(source).splitlines(keepends=True)
    nb.get("metadata", {}).pop("widgets", None)
    return nb


def commit_of(repo: Path) -> tuple[str, str]:
    out = subprocess.run(["git", "-C", str(repo), "log", "-1", "--format=%H %cI"],
                         capture_output=True, text=True, check=True).stdout.split()
    return out[0], out[1]


def main(sources: Path) -> None:
    commits = {name: commit_of(sources / name) for name in (AI4B, ML4B)}
    DST.mkdir(parents=True, exist_ok=True)
    META.mkdir(parents=True, exist_ok=True)
    for old in DST.glob("Week*"):
        old.unlink()

    staged = {}
    for lea_name, (repo, path) in FILES.items():
        src = sources / repo / path
        if src.suffix == ".ipynb":
            nb = clean_notebook(json.loads(src.read_text(encoding="utf-8")))
            (DST / lea_name).write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
            change = "outputs, execution counts and embedded images removed"
        else:
            header = (f"> Source: {TITLES[repo]}, `{path}` (MIT licence, (c) Microsoft Corporation), "
                      f"commit {commits[repo][0][:7]}. Adapted for LEA: images and quiz links removed.\n\n")
            (DST / lea_name).write_text(header + clean_markdown(src.read_text(encoding="utf-8")), encoding="utf-8")
            change = "images, credits, video thumbnails and quiz links removed; relative links reduced to text; source line added"
        staged[lea_name] = {"repo": REPO_URLS[repo], "path": path, "commit": commits[repo][0], "changes": change}

    for (repo, path), name in LICENCES.items():
        (META / name).write_text((sources / repo / path).read_text(encoding="utf-8"), encoding="utf-8")
    (META / "staging_map.json").write_text(json.dumps(staged, indent=2) + "\n", encoding="utf-8")
    write_attribution(commits, staged)
    print(f"Staged {len(staged)} files into {DST.relative_to(ROOT)}")


def write_attribution(commits: dict, staged: dict) -> None:
    rows = "\n".join(f"| `{name}` | {TITLES[AI4B] if AI4B in s['repo'] else TITLES[ML4B]} | `{s['path']}` | {s['changes']} |"
                     for name, s in staged.items())
    text = f"""# AIML101: sources and attribution

AIML101, "Introduction to AI and Machine Learning (open course)", is LEA's open demo
course. Its lesson text comes from two Microsoft curricula, both under the MIT licence:

| Source | Commit | Date | Licence |
|---|---|---|---|
| [AI for Beginners]({REPO_URLS[AI4B]}) | `{commits[AI4B][0]}` | {commits[AI4B][1][:10]} | MIT, (c) Microsoft Corporation ([copy](LICENSE-AI-For-Beginners.txt)) |
| [ML for Beginners]({REPO_URLS[ML4B]}) | `{commits[ML4B][0]}` | {commits[ML4B][1][:10]} | MIT, (c) Microsoft Corporation ([copy](LICENSE-ML-For-Beginners.txt)) |

The ML for Beginners quiz app, whose English question bank LEA uses as reference
questions, also carries an MIT notice (c) 2020 Arpan Adhikari
([copy](LICENSE-ML-For-Beginners-quiz-app.txt)).

Licences re-checked and sources pinned on {date.today().isoformat()}. English text only; no
translations. **No images are included**: the sketchnotes and photos are credited to their
creators, and it is not clear that the MIT licence covers them.

## Files used and changes made

Staged by `data_foundation/stage_aiml101.py` into `data/org_docs/AIML101/`.

| LEA file | Source | Path | Changes |
|---|---|---|---|
{rows}

## Generated by LEA

These are LEA's own work, derived from the lesson text above (see
`docs/COURSE_CREATION.md`):

- the week structure and the learning objectives (written by the LEA owner from the lessons);
- the knowledge-component model (`data/kc_models/AIML101/`): granular objectives, skill
  names, descriptions, cognitive levels, mastery thresholds, difficulty, prerequisites and
  tags, drafted by OpenAI GPT-4o with `data_foundation/kc_model_generator.py` and reviewed;
- short objective titles, the course profile, document summaries and titles (GPT-4o),
  and the retrieval index (OpenAI embeddings) in `data/md_docs`, `data/metadata` and
  `data/chroma_data`;
- the reference question bank's tags to granular objectives.
"""
    (META / "ATTRIBUTION.md").write_text(text, encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    main(Path(sys.argv[1]))
