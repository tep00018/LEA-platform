"""The onboarding pipeline a job runs: convert -> transcribe -> chunk and embed -> draft KC
model -> course profile -> verify retrieval.

The steps drive the existing onboarding code in ``data_foundation/`` (see
docs/COURSE_CREATION.md), with LEA's data folder passed in. The KC step writes a **draft**
(``kc_models/<CODE>/drafts/<job>.json``), never the model students use: publishing is a
separate, explicit step (B4). Steps check for cancellation between files.

``estimate`` prices a run before it starts, so the teacher can confirm it.
"""

from __future__ import annotations

import json
import logging
import shutil
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from src.onboarding.files import DEFAULT_KIND, MEDIA, staged_name

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
FOUNDATION = ROOT / "data_foundation"

STEPS = ("convert", "transcribe", "embed", "kc_draft", "profile", "verify")
STEP_LABELS = {
    "convert": "Converting uploads", "transcribe": "Transcribing audio and video",
    "embed": "Chunking and embedding", "kc_draft": "Drafting the KC model",
    "profile": "Writing the course profile", "verify": "Checking retrieval for each objective",
}
KC_MODEL = "gpt-4o"

# Prices (USD) used for estimates: GPT-4o $2.50/M input, $10/M output; text-embedding-3-small $0.02/M.
SUMMARY_PER_FILE = 0.003       # one GPT-4o summary of the first 2,000 characters
CAPTION_PER_IMAGE = 0.004      # MarkItDown asks GPT-4o to describe each picture in slides/Word files
EMBED_PER_MB = 0.0005          # generous: ~250k tokens per MB of document text
KC_PER_CALL = 0.01             # one call per week (objective names) and per objective (granular objectives)
VERIFY_PER_GO = 0.00001


class Cancelled(Exception):
    """The teacher cancelled the job."""


@dataclass
class JobContext:
    """What a running job gives the pipeline."""
    job_id: str
    course: str
    data_dir: Path
    meta: Dict[str, Any]
    uploads: Dict[str, Dict[str, Any]]           # stored name -> upload metadata
    plan: Optional[Dict[str, Any]] = None        # weekly objectives set by the teacher
    log: Callable[[str], None] = print
    progress: Callable[[str, float], None] = lambda step, fraction: None
    is_cancelled: Callable[[], bool] = lambda: False
    result: Dict[str, Any] = field(default_factory=dict)

    def check(self) -> None:
        if self.is_cancelled():
            raise Cancelled()

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "course_uploads" / self.course

    @property
    def staged_dir(self) -> Path:
        return self.data_dir / "org_docs" / self.course


def _foundation():
    if str(FOUNDATION) not in sys.path:
        sys.path.insert(0, str(FOUNDATION))


def image_count(path: Path) -> int:
    """Pictures inside a PowerPoint or Word file (each is captioned by GPT-4o)."""
    if path.suffix.lower() not in (".pptx", ".docx"):
        return 0
    try:
        with zipfile.ZipFile(path) as z:
            return sum(1 for n in z.namelist() if "/media/" in n)
    except zipfile.BadZipFile:
        return 0


def estimate(ctx: JobContext, steps: List[str]) -> Dict[str, Any]:
    """An upper-end cost estimate in USD, per step, with notes."""
    docs = [n for n in ctx.uploads if Path(n).suffix.lower() not in MEDIA]
    media = [n for n in ctx.uploads if Path(n).suffix.lower() in MEDIA]
    images = sum(image_count(ctx.uploads_dir / n) for n in docs)
    mb = sum(ctx.uploads[n].get("size", 0) for n in docs) / 1e6
    weeks = (ctx.plan or {}).get("weeks", [])
    calls = len(weeks) + sum(len(w.get("objectives", [])) for w in weeks)
    gos = sum(len(w.get("objectives", [])) for w in weeks) * 4
    per_step = {
        "convert": 0.0,
        "transcribe": 0.0,
        "embed": round(len(docs) * SUMMARY_PER_FILE + images * CAPTION_PER_IMAGE + mb * EMBED_PER_MB, 3),
        "kc_draft": round(calls * KC_PER_CALL, 3),
        "profile": 0.0,
        "verify": round(gos * VERIFY_PER_GO, 3),
    }
    notes = []
    if "transcribe" in steps and media:
        notes.append(f"{len(media)} audio/video file(s) are transcribed on this PC with Whisper: no OpenAI cost, "
                     "but it can take about as long as the recordings themselves.")
    if "embed" in steps and images:
        notes.append(f"{images} picture(s) in slides and Word files are described by GPT-4o.")
    if "embed" in steps:
        notes.append("Files unchanged since the last run are skipped and cost nothing.")
    per_step = {s: per_step[s] for s in steps}
    return {"usd": round(sum(per_step.values()), 3), "per_step": per_step, "files": len(ctx.uploads),
            "documents": len(docs), "media": len(media), "images": images, "model_calls": calls, "notes": notes}


class Pipeline:
    """Runs the steps. ``processor_factory`` and ``kc_builder`` default to the real
    data_foundation code; tests pass fakes."""

    def __init__(self, processor_factory: Optional[Callable[[str, Path], Any]] = None,
                 kc_builder: Optional[Callable[[JobContext], Dict[str, Any]]] = None):
        self.processor_factory = processor_factory or self._real_processor
        self.kc_builder = kc_builder or build_kc_draft
        self._processor = None

    @staticmethod
    def _real_processor(course: str, data_dir: Path):
        _foundation()
        from rag_library_creation import DocumentProcessor
        return DocumentProcessor(course, data_dir=str(data_dir))

    def processor(self, ctx: JobContext):
        if self._processor is None:
            self._processor = self.processor_factory(ctx.course, ctx.data_dir)
        return self._processor

    def run(self, ctx: JobContext, steps: List[str]) -> Dict[str, Any]:
        self._processor = None
        for step in STEPS:
            if step not in steps:
                continue
            ctx.check()
            ctx.progress(step, 0.0)
            ctx.log(f"== {STEP_LABELS[step]}")
            getattr(self, f"step_{step}")(ctx)
            ctx.progress(step, 1.0)
        return ctx.result

    # ------------------------------------------------------------------ steps

    def step_convert(self, ctx: JobContext) -> None:
        """Copy the uploads into the course folder under LEA's names; files staged by an
        earlier run and since deleted are listed for removal from the index."""
        state_path = ctx.uploads_dir / ".staged.json"
        previous = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
        ctx.staged_dir.mkdir(parents=True, exist_ok=True)
        letters: Dict[tuple, int] = {}
        staged: Dict[str, Dict[str, Any]] = {}
        names = sorted(ctx.uploads, key=lambda n: (ctx.uploads[n].get("week") or 0, n.lower()))
        for i, name in enumerate(names):
            ctx.check()
            meta = ctx.uploads[name]
            kind = meta.get("kind") or DEFAULT_KIND.get(Path(name).suffix.lower(), "Other")
            key = (meta.get("week") or 0, kind)
            letters[key] = letters.get(key, 0) + 1
            letter = chr(ord("A") + letters[key] - 1) if letters[key] <= 26 else str(letters[key])
            target = staged_name(meta.get("week"), kind, letter, name)
            shutil.copyfile(ctx.uploads_dir / name, ctx.staged_dir / target)
            staged[target] = {"upload": name, "sha256": meta.get("sha256")}
            ctx.progress("convert", (i + 1) / max(1, len(names)))
        removed = [n for n in previous if n not in staged]
        for name in removed:
            (ctx.staged_dir / name).unlink(missing_ok=True)
        state_path.write_text(json.dumps(staged, indent=2), encoding="utf-8")
        ctx.result["staged"] = len(staged)
        ctx.result["removed_files"] = removed
        ctx.log(f"{len(staged)} file(s) staged; {len(removed)} removed since the last run.")

    def _ingest(self, ctx: JobContext, step: str, media: bool) -> None:
        state_path = ctx.uploads_dir / ".staged.json"
        staged = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
        names = sorted(n for n in staged if (Path(n).suffix.lower() in MEDIA) == media)
        if not names and not (step == "embed" and ctx.result.get("removed_files")):
            ctx.log("Nothing to do.")
            return
        processor = self.processor(ctx)
        if step == "embed":
            for name in ctx.result.get("removed_files", []):
                self._forget(processor, name)
                ctx.log(f"Removed from the index: {name}")
        processed = skipped = 0
        for i, name in enumerate(names):
            ctx.check()
            ctx.log(f"{name}")
            if processor.process_file(str(ctx.staged_dir / name)):
                processed += 1
            else:
                skipped += 1
            processor._save_metadata()
            ctx.progress(step, (i + 1) / len(names))
        processor._save_errors()
        errors = [n for n in names if n in getattr(processor, "errors", {})]
        ctx.result[step] = {"processed": processed, "unchanged": skipped, "errors": errors}
        ctx.log(f"{processed} processed, {skipped} unchanged" + (f", problems with: {', '.join(errors)}" if errors else "."))

    @staticmethod
    def _forget(processor, name: str) -> None:
        try:
            processor.collection.delete(where={"source_file": name})
        except Exception as e:
            logger.warning(f"Couldn't remove {name} from the index: {e}")
        entry = processor.metadata.pop(name, None)
        if entry and entry.get("markdown_path"):
            Path(entry["markdown_path"]).unlink(missing_ok=True)
        processor._save_metadata()

    def step_transcribe(self, ctx: JobContext) -> None:
        self._ingest(ctx, "transcribe", media=True)

    def step_embed(self, ctx: JobContext) -> None:
        self._ingest(ctx, "embed", media=False)

    def step_kc_draft(self, ctx: JobContext) -> None:
        draft = self.kc_builder(ctx)
        path = ctx.data_dir / "kc_models" / ctx.course / "drafts" / f"{ctx.job_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(draft, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        ctx.result["kc_draft"] = str(path.relative_to(ctx.data_dir)).replace("\\", "/")
        gos = sum(len(lo["granular_objectives"]) for w in draft["week_navigation"].values()
                  for lo in w["learning_objectives"])
        ctx.log(f"Draft KC model: {len(draft['week_navigation'])} weeks, {gos} granular objectives "
                "(not published: students keep the current model).")

    def step_profile(self, ctx: JobContext) -> None:
        meta = ctx.meta
        path = ctx.data_dir / "course_profiles" / f"{ctx.course}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        try:  # keep what the build does not own, such as the linked materials folder
            existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except ValueError:
            existing = {}
        profile = {**existing, "code": ctx.course, "name": meta.get("name", ""),
                   "discipline": meta.get("discipline", "unspecified"), "allows_code": bool(meta.get("allows_code")),
                   "code_language": meta.get("code_language") if meta.get("allows_code") else None}
        path.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")
        ctx.log(f"Profile written: {profile['discipline']}, code questions {'on' if profile['allows_code'] else 'off'}.")

    def step_verify(self, ctx: JobContext) -> None:
        """Search the course content with each granular objective; flag the ones whose best
        match is weak for this course (below its mean similarity by 1.5 standard deviations)."""
        draft_rel = ctx.result.get("kc_draft")
        path = ctx.data_dir / draft_rel if draft_rel else ctx.data_dir / "kc_models" / ctx.course / f"kc_model_{ctx.course}.json"
        if not path.exists():
            ctx.log("No KC model to check yet: skipped.")
            return
        model = json.loads(path.read_text(encoding="utf-8"))
        gos = [go for w in model["week_navigation"].values() for lo in w["learning_objectives"]
               for go in lo["granular_objectives"]]
        collection = self.processor(ctx).collection
        for i, go in enumerate(gos):
            ctx.check()
            found = collection.query(query_texts=[f"{go.get('skill_name', '')}. {go.get('description', '')}"],
                                     n_results=1, include=["documents", "metadatas", "distances"])
            if found["ids"] and found["ids"][0]:
                similarity = 1 - found["distances"][0][0] / 2  # unit vectors: squared L2 -> cosine
                go["provenance"] = {"source_file": found["metadatas"][0][0].get("source_file"),
                                    "excerpt": found["documents"][0][0][:400], "similarity": round(similarity, 3)}
            ctx.progress("verify", (i + 1) / max(1, len(gos)))
        scores = [go["provenance"]["similarity"] for go in gos if "provenance" in go]
        if scores:
            mean = sum(scores) / len(scores)
            sd = (sum((s - mean) ** 2 for s in scores) / len(scores)) ** 0.5
            cutoff = mean - 1.5 * sd
            weak = [go["go_id"] for go in gos if go.get("provenance", {}).get("similarity", 0) < cutoff
                    or "provenance" not in go]
        else:
            cutoff, weak = None, [go["go_id"] for go in gos]
        if draft_rel:  # keep the evidence with the draft for the teacher's review (B4)
            path.write_text(json.dumps(model, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        ctx.result["verify"] = {"objectives": len(gos), "weak_support": weak,
                                "cutoff": round(cutoff, 3) if cutoff is not None else None}
        ctx.log(f"{len(gos)} objectives checked; {len(weak)} with weak support in the content.")


# ---------------------------------------------------------------------- KC draft


def apply_objective_titles(model: Dict[str, Any], plan: Dict[str, Any]) -> None:
    """Give each learning objective the teacher's own text. The generator names objectives
    with GPT "concept names" that can come back in the wrong order (seen with AIML101), and
    those names leak into the GO descriptions and tags; they are replaced here."""
    texts = [obj for w in sorted(plan["weeks"], key=lambda w: w["week"]) for obj in w["objectives"]]
    los = [lo for _, w in sorted(model["week_navigation"].items()) for lo in w["learning_objectives"]]
    if len(texts) != len(los):
        raise ValueError(f"The draft has {len(los)} objectives but the plan has {len(texts)}.")
    by_id = model.get("quick_lookup", {}).get("lo_by_id", {})
    gos_by_id = model.get("quick_lookup", {}).get("go_by_id", {})
    for lo, text in zip(los, texts):
        wrong = lo["title"]
        for target in (lo, by_id.get(lo["lo_id"], {})):
            target["title"], target["short_title"] = text, ""
            if "conceptual_tags" in target:
                target["conceptual_tags"] = [t for t in target["conceptual_tags"] if t.lower() != wrong.lower()]
            for go in target.get("granular_objectives", []):
                _drop_name(go, wrong)
        for go in lo.get("granular_objectives", []):
            _drop_name(gos_by_id.get(go["go_id"], {}), wrong)


def _drop_name(go: Dict[str, Any], wrong: str) -> None:
    import re

    if not go:
        return
    go["description"] = re.sub(rf"\s*(and its role in|This includes understanding)\s+{re.escape(wrong)}\b[,.]?", "",
                               go.get("description", ""), flags=re.IGNORECASE).strip()
    go["conceptual_tags"] = [t for t in go.get("conceptual_tags", []) if t.lower() != wrong.lower()]


def build_kc_draft(ctx: JobContext) -> Dict[str, Any]:
    """Draft the KC model from the teacher's weekly objectives with the existing generator
    (GPT-4o) and converter, in a scratch folder, without installing anything."""
    if not ctx.plan or not ctx.plan.get("weeks"):
        raise ValueError("Add the weekly learning objectives before drafting the KC model.")
    _foundation()
    import os

    import pandas as pd
    from create_kc_model import AgenticAITemplateConverter
    from kc_model_generator import ImprovedKCExtractor

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        template = pd.DataFrame([{
            "Week": w["week"], "Week Description": w["title"],
            "Learning Objectives": "\n".join(f"{i}. {o}" for i, o in enumerate(w["objectives"], 1)),
            "Supporting Materials": f"data/md_docs/{ctx.course}/Week{w['week']:02d}-",
        } for w in sorted(ctx.plan["weeks"], key=lambda w: w["week"])])
        example = pd.read_excel(FOUNDATION / "DEMO101.xlsx", sheet_name="Partial_Example")
        with pd.ExcelWriter(tmp / "template.xlsx", engine="openpyxl") as x:
            template.to_excel(x, sheet_name="Template", index=False)
            example.to_excel(x, sheet_name="Partial_Example", index=False)
        ctx.log(f"Generating granular objectives with {KC_MODEL}...")
        extractor = ImprovedKCExtractor(os.getenv("OPENAI_API_KEY"), ctx.course, ctx.meta.get("name"), model=KC_MODEL)
        extractor.process_complete_course(str(tmp / "template.xlsx"), str(tmp / "generated.xlsx"))
        ctx.check()
        AgenticAITemplateConverter().process_complete_conversion(str(tmp / "generated.xlsx"), str(tmp / "kc.json"))
        model = json.loads((tmp / "kc_ui_navigation.json").read_text(encoding="utf-8"))
    apply_objective_titles(model, ctx.plan)
    model.setdefault("course_info", {})["course_name"] = ctx.meta.get("name", "")
    return model
