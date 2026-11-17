"""The content audit's checks (docs/teacher/BUILD_PLAN.md, B5). Each returns findings:

    {key, check, severity, title, explanation, evidence, target: {kind, ref}, tier, llm}

``key`` is stable across runs (the same problem gets the same key), so a teacher's accept
or dismiss carries over. ``tier`` says how well that kind of check is validated:
``well_supported``, ``rule_based``, ``moderate``, ``experimental`` or ``informational``.
Findings are ranked and capped per check: the audit reports, the teacher decides.
"""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional
from xml.etree import ElementTree

from src.onboarding import kc_model as K

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}
MAX_PER_CHECK = 15
MEDIA = {".mp3", ".mp4", ".wav", ".avi", ".mov", ".mkv", ".webm"}


def finding(check: str, key_parts: Iterable[Any], severity: str, title: str, explanation: str, evidence: str,
            target_kind: str, target_ref: str, tier: str, llm: bool = False, weight: int = 1) -> Dict[str, Any]:
    """``weight`` (how many items it covers: pictures, slides) ranks findings within a check."""
    key = hashlib.sha1("|".join([check, *map(str, key_parts)]).encode()).hexdigest()[:16]
    return {"key": key, "check": check, "severity": severity, "title": title, "explanation": explanation,
            "evidence": evidence, "target": {"kind": target_kind, "ref": target_ref}, "tier": tier, "llm": llm,
            "weight": weight}


# ---------------------------------------------------------------------- accessibility


def _luminance(hex_rgb: str) -> float:
    def channel(c: int) -> float:
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (int(hex_rgb[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast_ratio(a: str, b: str) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


_AUTO_ALT = re.compile(r"^(picture|image|graphic|screenshot|content placeholder)\s*\d*$|\.(png|jpe?g|gif|bmp|emf|wmf|svg|tiff?)$",
                       re.IGNORECASE)


def is_real_alt_text(text: str) -> bool:
    """PowerPoint and python-pptx fill a picture's description with its file name or
    "Picture 3"; that isn't a text alternative."""
    text = text.strip()
    return bool(text) and not _AUTO_ALT.search(text)


def _solid_fill(fill) -> Optional[str]:
    try:
        if fill.type == 1:  # MSO_FILL.SOLID
            return str(fill.fore_color.rgb)
    except Exception:
        return None
    return None


def check_pptx(path: Path) -> List[Dict[str, Any]]:
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    out: List[Dict[str, Any]] = []
    try:
        deck = Presentation(str(path))
    except Exception:
        return out
    no_alt, untitled, low_contrast, dense = [], [], [], []
    for n, slide in enumerate(deck.slides, 1):
        background = _solid_fill(slide.background.fill) if slide.background else None
        if slide.shapes.title is None or not (slide.shapes.title.text or "").strip():
            untitled.append(n)
        words = 0
        for shape in slide.shapes:
            if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                descr = shape._element.xpath("./p:nvPicPr/p:cNvPr/@descr")
                if not descr or not is_real_alt_text(str(descr[0])):
                    no_alt.append(n)
            if not shape.has_text_frame:
                continue
            words += len(shape.text_frame.text.split())
            shape_bg = _solid_fill(shape.fill) if hasattr(shape, "fill") else None
            bg = shape_bg or background
            if not bg:
                continue
            for para in shape.text_frame.paragraphs:
                for run in para.runs:
                    try:
                        color = str(run.font.color.rgb) if run.font.color and run.font.color.type is not None else None
                    except Exception:
                        color = None
                    if color and run.text.strip() and contrast_ratio(color, bg) < 4.5:
                        low_contrast.append((n, round(contrast_ratio(color, bg), 1)))
        if words > 90:
            dense.append((n, words))
    name = path.name
    if no_alt:
        slides = sorted(set(no_alt))
        out.append(finding("accessibility", [name, "alt"], "high",
                           f"{len(no_alt)} picture(s) in {name} have no text alternative",
                           "Screen-reader users miss what these pictures show. WCAG 2.2, 1.1.1 (non-text content).",
                           f"{name} · slides {', '.join(map(str, slides[:12]))}{' …' if len(slides) > 12 else ''}",
                           "file", name, "well_supported", weight=len(no_alt)))
    if low_contrast:
        worst = min(r for _, r in low_contrast)
        slides = sorted({s for s, _ in low_contrast})
        out.append(finding("accessibility", [name, "contrast"], "medium",
                           f"Low-contrast text in {name}",
                           f"Text and background below the 4.5:1 contrast WCAG 2.2 asks for (1.4.3); lowest {worst}:1. "
                           "Only colours set explicitly on the slide are checked.",
                           f"{name} · slides {', '.join(map(str, slides[:12]))}", "file", name, "well_supported"))
    if untitled and len(untitled) < len(deck.slides):
        out.append(finding("accessibility", [name, "titles"], "low",
                           f"{len(untitled)} slide(s) in {name} have no title",
                           "Slide titles let screen-reader users find their way (WCAG 2.2, 2.4.6).",
                           f"{name} · slides {', '.join(map(str, untitled[:12]))}", "file", name, "well_supported"))
    if dense:
        out.append(finding("readability", [name, "density"], "info",
                           f"{len(dense)} dense slide(s) in {name}",
                           "Slides with over 90 words are hard to follow in a lecture. Information only: "
                           "no validated threshold exists.",
                           ", ".join(f"slide {n}: {w} words" for n, w in dense[:8]), "file", name, "informational"))
    return out


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"


def check_docx(path: Path) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    try:
        with zipfile.ZipFile(path) as z:
            root = ElementTree.fromstring(z.read("word/document.xml"))
    except Exception:
        return out
    pictures = root.iter(f"{_WP}docPr")
    no_alt = sum(1 for p in pictures if not (p.get("descr") or "").strip())
    styles = [s.get(f"{_W}val", "") for s in root.iter(f"{_W}pStyle")]
    headings = [s for s in styles if re.match(r"(?i)heading\s*\d|title", s)]
    paragraphs = sum(1 for _ in root.iter(f"{_W}p"))
    name = path.name
    if no_alt:
        out.append(finding("accessibility", [name, "alt"], "high",
                           f"{no_alt} picture(s) in {name} have no text alternative",
                           "Screen-reader users miss what these pictures show. WCAG 2.2, 1.1.1.",
                           name, "file", name, "well_supported"))
    if paragraphs > 25 and not headings:
        out.append(finding("accessibility", [name, "headings"], "low", f"{name} has no headings",
                           "Heading styles let screen-reader users skim and jump between sections (WCAG 2.2, 1.3.1).",
                           f"{name} · {paragraphs} paragraphs, no Heading styles", "file", name, "well_supported"))
    if no_alt:
        out[0]["weight"] = no_alt
    return out


def check_pdf(path: Path) -> List[Dict[str, Any]]:
    try:
        from pdfminer.high_level import extract_text

        text = extract_text(str(path), maxpages=3)
    except Exception:
        return []
    if len(text.strip()) < 40:
        return [finding("accessibility", [path.name, "scanned"], "high", f"{path.name} looks scanned (no text layer)",
                        "Screen readers, search and LEA's own retrieval can't read a PDF that is only images.",
                        f"{path.name} · first pages have no selectable text", "file", path.name, "well_supported")]
    return []


def check_media(paths: List[Path]) -> List[Dict[str, Any]]:
    names = {p.stem.lower() for p in paths if p.suffix.lower() in (".vtt", ".srt")}
    out = []
    for p in paths:
        if p.suffix.lower() in MEDIA and p.stem.lower() not in names:
            out.append(finding("accessibility", [p.name, "captions"], "low", f"{p.name} has no caption file",
                               "If students watch or hear this recording, it needs captions (WCAG 2.2, 1.2.2). "
                               "LEA uses its transcript, but students don't see that.",
                               f"{p.name} · no .vtt or .srt beside it", "file", p.name, "well_supported"))
    return out


def check_files(folder: Path) -> List[Dict[str, Any]]:
    if not folder.exists():
        return []
    files = sorted(p for p in folder.iterdir() if p.is_file())
    out: List[Dict[str, Any]] = []
    for p in files:
        ext = p.suffix.lower()
        if ext == ".pptx":
            out += check_pptx(p)
        elif ext == ".docx":
            out += check_docx(p)
        elif ext == ".pdf":
            out += check_pdf(p)
    return out + check_media(files)


# ---------------------------------------------------------------------- readability


def _syllables(word: str) -> int:
    word = word.lower().strip(".,;:!?\"'()")
    groups = re.findall(r"[aeiouy]+", word)
    count = len(groups) - (1 if word.endswith("e") and len(groups) > 1 else 0)
    return max(1, count)


def flesch(text: str) -> Optional[float]:
    sentences = [s for s in re.split(r"[.!?]+\s", text) if s.strip()]
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", text)
    if len(words) < 150 or not sentences:
        return None
    return 206.835 - 1.015 * (len(words) / len(sentences)) - 84.6 * (sum(map(_syllables, words)) / len(words))


def check_readability(md_folder: Path) -> List[Dict[str, Any]]:
    out = []
    if not md_folder.exists():
        return out
    for p in sorted(md_folder.glob("*.md")):
        text = re.sub(r"```.*?```", " ", p.read_text(encoding="utf-8", errors="ignore"), flags=re.DOTALL)
        score = flesch(text)
        if score is not None and score < 30:
            out.append(finding("readability", [p.name, "flesch"], "info", f"{p.stem} reads as very difficult",
                               f"Flesch reading ease {score:.0f} (below 30 is university-graduate level). "
                               "Information only: technical subjects often score low.",
                               p.name, "file", p.name, "informational"))
    return out


# ---------------------------------------------------------------------- the KC model


def check_prerequisite_order(model: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = K.rows_from_model(model)
    week = {r["go_id"]: int(r["week"]) for r in rows}
    name = {r["go_id"]: r["skill_name"] for r in rows}
    out = []
    for r in rows:
        for p in r.get("prerequisites", []):
            if p in week and week[p] > week[r["go_id"]]:
                out.append(finding("prerequisites", [r["go_id"], p], "medium",
                                   "A prerequisite is taught after the objective that needs it",
                                   f"{r['go_id']} “{r['skill_name']}” (week {week[r['go_id']]}) needs {p} "
                                   f"“{name[p]}”, taught in week {week[p]}.",
                                   f"{r['go_id']} → {p}", "objective", r["go_id"], "rule_based"))
    return out


def check_bloom_balance(model: Dict[str, Any]) -> List[Dict[str, Any]]:
    by_week: Dict[int, Counter] = defaultdict(Counter)
    for r in K.rows_from_model(model):
        by_week[int(r["week"])][K.bloom(r["cognitive_level"])] += 1
    out = []
    for week, counts in sorted(by_week.items()):
        total = sum(counts.values())
        top, n = counts.most_common(1)[0]
        higher = sum(counts[level] for level in ("Apply", "Analyze", "Evaluate", "Create"))
        share = ", ".join(f"{level} {round(100 * counts[level] / total)}%" for level in K.BLOOM if counts[level])
        if total >= 4 and n / total > 0.6:
            out.append(finding("bloom", [week, "dominant", top], "low", f"Week {week} is mostly “{top}”",
                               "Most objectives sit at one level; consider whether students also apply, analyse or "
                               "create. Shown as a distribution, not per objective.",
                               share, "week", str(week), "moderate"))
        elif total >= 4 and higher == 0:
            out.append(finding("bloom", [week, "no-higher"], "low", f"Week {week} has no apply-or-higher objectives",
                               "Every objective asks students to remember or understand.", share, "week", str(week),
                               "moderate"))
    return out


def check_alignment(model: Dict[str, Any], bank: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not bank:
        return []
    tagged = Counter(q.get("go_id") for q in bank.get("questions", []))
    out = []
    by_lo: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in K.rows_from_model(model):
        by_lo[r["lo_id"]].append(r)
    for lo_id, rows in by_lo.items():
        missing = [r for r in rows if not tagged.get(r["go_id"])]
        if missing and len(missing) == len(rows):
            out.append(finding("alignment", [lo_id, "no-questions"], "low",
                               f"No reference questions for “{rows[0]['lo_title'][:80]}”",
                               "None of this learning objective's granular objectives has a question in the reference "
                               "bank. Tags are suggestions (embedding similarity), so check before acting.",
                               ", ".join(r["go_id"] for r in missing), "objective", lo_id, "experimental"))
    return out


# ---------------------------------------------------------------------- the question bank

_NEGATIVE = re.compile(r"\b(not|except|never|incorrect)\b|\bthe least\b", re.IGNORECASE)
_ALL_NONE = re.compile(r"\b(all|none) of the (above|options|answers)\b", re.IGNORECASE)


def check_questions(bank: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not bank:
        return []
    out = []
    for q in bank.get("questions", []):
        stem, options, right = q["text"], q["options"], q["correct_index"]
        problems = []
        if q.get("type") != "true_false" and _NEGATIVE.search(stem):
            problems.append(("negative", "The stem is negatively worded; students often miss the “not”."))
        if any(_ALL_NONE.search(o) for o in options):
            problems.append(("all-none", "“All/none of the above” lets students answer by elimination."))
        if len(options) >= 3:
            lengths = [len(o) for o in options]
            if lengths[right] == max(lengths) and lengths[right] > 1.5 * sorted(lengths)[-2]:
                problems.append(("longest", "The correct option is much longer than the others: a clue."))
            stem_words = {w.lower() for w in re.findall(r"[A-Za-z]{5,}", stem)}
            overlap = [len(stem_words & {w.lower() for w in re.findall(r"[A-Za-z]{5,}", o)}) for o in options]
            if overlap[right] >= 2 and all(overlap[i] == 0 for i in range(len(options)) if i != right):
                problems.append(("clue", "Only the correct option repeats words from the stem: a clue."))
        for kind, why in problems:
            out.append(finding("questions", [q["id"], kind], "medium", f"Question {q['id']}: {why.split(':')[0].rstrip('.')}",
                               why + " (Item-writing rules in the style of SAQUET.)",
                               f"“{stem[:160]}”", "question", q["id"], "well_supported"))
    return out


# ---------------------------------------------------------------------- embeddings


def check_coverage(model: Dict[str, Any], query: Callable[[str], Optional[tuple]]) -> List[Dict[str, Any]]:
    """``query(text)`` returns (similarity, source_file) for the best matching chunk."""
    rows = K.rows_from_model(model)
    scored = []
    for r in rows:
        hit = query(f"{r['skill_name']}. {r['description']}")
        scored.append((r, hit))
    sims = [h[0] for _, h in scored if h]
    if len(sims) < 5:
        return []
    mean = sum(sims) / len(sims)
    sd = (sum((s - mean) ** 2 for s in sims) / len(sims)) ** 0.5
    cutoff = mean - 1.5 * sd
    out = []
    for r, hit in scored:
        if hit is None or hit[0] < cutoff:
            evidence = f"best match {hit[0]:.2f} in {hit[1]}" if hit else "no match"
            out.append(finding("coverage", [r["go_id"]], "medium",
                               f"“{r['skill_name']}” has weak support in the materials",
                               f"Its best match scores below this course's cut-off ({cutoff:.2f}, the mean {mean:.2f} "
                               "minus 1.5 standard deviations). It may need material, or rewording.",
                               f"{r['go_id']} · {evidence}", "objective", r["go_id"], "experimental"))
    return out


def check_redundancy(model: Dict[str, Any], embed: Callable[[List[str]], List[List[float]]],
                     threshold: float = 0.92) -> List[Dict[str, Any]]:
    rows = K.rows_from_model(model)
    if len(rows) < 2:
        return []
    vectors = embed([f"{r['skill_name']}. {r['description']}" for r in rows])
    norms = [sum(x * x for x in v) ** 0.5 or 1 for v in vectors]
    out = []
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            sim = sum(a * b for a, b in zip(vectors[i], vectors[j])) / (norms[i] * norms[j])
            if sim >= threshold:
                a, b = rows[i], rows[j]
                out.append(finding("redundancy", sorted([a["go_id"], b["go_id"]]), "low",
                                   f"“{a['skill_name']}” and “{b['skill_name']}” look alike",
                                   f"Similarity {sim:.2f}. Merge them, or keep both if it's intended spiral review.",
                                   f"{a['go_id']} (week {a['week']}) · {b['go_id']} (week {b['week']})",
                                   "objective", a["go_id"], "experimental"))
    return out


def rank(findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Most severe first, at most MAX_PER_CHECK per check."""
    ordered = sorted(findings, key=lambda f: (SEVERITY_ORDER[f["severity"]], f["check"], -f.get("weight", 1),
                                              f["title"]))
    seen: Counter = Counter()
    out = []
    for f in ordered:
        seen[f["check"]] += 1
        if seen[f["check"]] <= MAX_PER_CHECK:
            out.append(f)
    return out


def load_bank(path: Path) -> Optional[Dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
