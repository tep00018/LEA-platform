"""Clean auto-generated lecture transcripts before they go into a course's RAG library.

Speech-to-text transcripts mishear names and terms ("Ackinson Schiffrin"), have no
paragraphs, and carry recording chatter. This script asks an OpenAI model to produce a
clean, faithful version of each transcript, one ~600-word segment at a time, using a
glossary of the course's own terms so names are corrected rather than guessed.

The model is told to fix, format and trim, never to add content; each segment is checked
afterwards (word-count drop, glossary terms that disappeared) and flagged for review.

Usage (from the repository root):

    python data_foundation/clean_transcripts.py AIML101 --files Week08-VideoB-...txt
    python data_foundation/clean_transcripts.py AIML101 --all

Reads transcripts (``*Transcript*.txt``) from data/org_docs/<COURSE>/ and writes cleaned
copies and a report to data/metadata/clean_transcripts/<COURSE>/ (git-ignored). Nothing in
org_docs is changed: copy approved files over the originals yourself, then rerun
rag_library_creation.py, which replaces those files' chunks.

Needs OPENAI_API_KEY in .env. Stops at once, with a clear message, if the key is rejected
or the account has no funds.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

SEGMENT_WORDS = 600  # longer pieces make the model condense instead of edit
# USD per million tokens (gpt-4o list price); only used for the cost estimate printed.
PRICES = {"gpt-4o": (2.50, 10.00), "gpt-4o-mini": (0.15, 0.60)}

SYSTEM_PROMPT = """You lightly edit automatic speech-to-text transcripts of university lectures into "clean verbatim" text for study material. Return only the edited transcript.

This is an edit, not a rewrite or a summary. Keep the speaker's own words, phrasing, examples, asides and sentence order. The result should read as what the lecturer said, minus the noise; for ordinary lecture speech it is usually 80-95% of the original length.

Do:
- Correct misheard words, names and technical terms. Use the course glossary; when a misheard phrase clearly matches a glossary entry or a well-known researcher or theory in the field, write it correctly (e.g. "Ackinson Schiffrin" -> "Atkinson-Shiffrin").
- Add punctuation and capitals, and split the text into paragraphs by topic.
- Delete only: filler words (um, uh, you know, sort of, kind of when meaningless), false starts, stutters, and words or phrases repeated by mistake.
- Delete recording set-up, room logistics and small talk that is not course content, and the names of students or audience members.

Never:
- Paraphrase, condense, merge or reorder sentences, or replace the speaker's words with more formal ones.
- Add explanations, facts, examples or summaries that the speaker did not say.
- Change the meaning of what was said, or "correct" the lecturer's claims.
- Use headings, bullet points or commentary about your edits.

If a passage is unintelligible, write [unclear] rather than guessing. If the whole piece is \
unintelligible, return exactly: [unclear]"""


NOT_AUTHORS = {"Week", "Slide", "Figure", "Table", "Page", "In", "The", "This", "Since", "From", "By"}
MONTHS = {"January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December"}
COMMON_WORDS = MONTHS | {"Turn", "Society", "Point", "Rotation", "Experiment", "Study", "Model", "Theory",
                         "Research", "Psychology", "Report", "Review", "Journal", "Press", "University",
                         "Date", "Jan", "Med", "Figure", "Source"}


class ApiProblem(Exception):
    """The OpenAI key or account can't be used; stop the whole run."""


def build_glossary(course: str, limit: int = 250) -> list[str]:
    """Course terms: objective names from the KC model, and researchers cited in the slides."""
    terms: list[str] = []
    model = json.loads(Path(f"data/kc_models/{course}/kc_model_{course}.json").read_text(encoding="utf-8"))
    for week in model.get("week_navigation", {}).values():
        for lo in week.get("learning_objectives", []):
            terms.append(lo.get("short_title") or lo.get("title", ""))
            terms.extend(go.get("skill_name", "") for go in lo.get("granular_objectives", []))
    citation = re.compile(
        r"\b([A-Z][a-zA-Z'\-]+(?:\s*(?:&|and)\s*[A-Z][a-zA-Z'\-]+)?(?:\s+et\s+al\.?)?),?\s*\(?((?:19|20)\d\d)\)?"
    )
    for md in sorted(Path(f"data/md_docs/{course}").glob("*.md")):
        if "Transcript" in md.name:
            continue
        for name, year in citation.findall(md.read_text(encoding="utf-8", errors="replace")):
            first = name.split()[0]
            # A lone capitalised word before a year is usually not an author ("September 1956").
            if first not in NOT_AUTHORS and (len(name.split()) > 1 or first not in COMMON_WORDS):
                terms.append(f"{name} ({year})")
    seen: dict[str, None] = {}
    for t in terms:
        t = " ".join(t.split()).removesuffix("...").strip()
        if t and t.lower() not in {s.lower() for s in seen}:
            seen[t] = None
    return list(seen)[:limit]


def segments(text: str, size: int = SEGMENT_WORDS) -> list[str]:
    """Split on sentence ends into pieces of about `size` words."""
    sentences = re.split(r"(?<=[.!?])\s+", " ".join(text.split()))
    out, current, count = [], [], 0
    for s in sentences:
        words = len(s.split())
        if current and count + words > size:
            out.append(" ".join(current))
            current, count = [], 0
        current.append(s)
        count += words
    if current:
        out.append(" ".join(current))
    return out


def clean_segment(client, model: str, glossary: list[str], segment: str, part: str) -> tuple[str, dict]:
    import openai

    user = (
        "Course glossary (correct spellings of names and terms that may appear):\n"
        + "; ".join(glossary)
        + f"\n\nTranscript {part}:\n\n{segment}"
    )
    for attempt in range(4):
        try:
            response = client.chat.completions.create(
                model=model,
                temperature=0,
                messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}],
            )
            usage = response.usage
            return response.choices[0].message.content.strip(), {
                "input_tokens": usage.prompt_tokens,
                "output_tokens": usage.completion_tokens,
            }
        except openai.AuthenticationError as e:
            raise ApiProblem("The OpenAI API key was rejected (401). Check OPENAI_API_KEY in .env.") from e
        except openai.PermissionDeniedError as e:
            raise ApiProblem(f"The OpenAI key can't use {model} (403): {e.message}") from e
        except openai.RateLimitError as e:
            if "insufficient_quota" in str(e) or "billing" in str(e).lower():
                raise ApiProblem(
                    "The OpenAI account is out of funds or over its spending limit (insufficient_quota). "
                    "Add credit, then rerun: finished transcripts are skipped."
                ) from e
            time.sleep(5 * (attempt + 1))  # a real rate limit: wait and retry
        except openai.APIConnectionError as e:
            if attempt == 3:
                raise ApiProblem(f"Couldn't reach the OpenAI API: {e}") from e
            time.sleep(5 * (attempt + 1))
    raise ApiProblem("OpenAI kept rate-limiting the requests; try again later.")


REFUSAL = re.compile(r"^\s*(I'm sorry|I am sorry|I'm unable|I am unable|I cannot|I can't|Sorry,)", re.IGNORECASE)


def clean_piece(client, model: str, glossary: list[str], part: str, label: str) -> tuple[str, dict, dict]:
    """Clean one piece, with two safeguards.

    - A refusal ("I'm sorry, the text is unintelligible...") is stored as [unclear], never
      as transcript text.
    - A piece cut to under half its length is cleaned again as two halves, and the version
      that keeps more is used (the model sometimes condenses instead of editing).
    """
    cleaned, usage = clean_segment(client, model, glossary, part, label)
    refused = bool(REFUSAL.match(cleaned))
    if refused:
        cleaned = "[unclear]"
    seg = check(part, cleaned, glossary)
    if not refused and seg["ratio"] < 0.5 and len(part.split()) > 200:
        halves = segments(part, len(part.split()) // 2 + 1)
        retried, total = [], {"input_tokens": 0, "output_tokens": 0}
        for j, half in enumerate(halves, 1):
            text, u = clean_segment(client, model, glossary, half, f"{label}, half {j}")
            retried.append("[unclear]" if REFUSAL.match(text) else text)
            total = {k: total[k] + u[k] for k in total}
        usage = {k: usage[k] + total[k] for k in usage}
        again = "\n\n".join(retried)
        if len(again.split()) > len(cleaned.split()):
            cleaned, seg = again, check(part, again, glossary)
            seg["retried"] = True
    seg["refused"] = refused
    seg["flag"] = seg["flag"] or refused
    return cleaned, seg, usage


def check(original: str, cleaned: str, glossary: list[str]) -> dict:
    """Flags for review: how much shorter it got, and glossary terms that disappeared."""
    words_in, words_out = len(original.split()), len(cleaned.split())
    ratio = words_out / words_in if words_in else 1.0
    def has(term: str, text: str) -> bool:
        return re.search(r"\b" + re.escape(term) + r"\b", text, re.IGNORECASE) is not None

    lost = [
        t for t in glossary
        if len(t) > 5 and has(t.split(" (")[0], original) and not has(t.split(" (")[0], cleaned)
    ]
    return {
        "words_in": words_in,
        "words_out": words_out,
        "ratio": round(ratio, 2),
        "unclear": cleaned.count("[unclear]"),
        "glossary_terms_lost": lost,
        "flag": ratio < 0.6 or ratio > 1.1 or bool(lost),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("course")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--files", nargs="+", help="transcript file names in data/org_docs/<COURSE>/")
    group.add_argument("--all", action="store_true", help="every *Transcript*.txt in the course")
    parser.add_argument("--model", default="gpt-4o")
    parser.add_argument("--force", action="store_true", help="redo transcripts already cleaned")
    parser.add_argument("--segment-words", type=int, default=SEGMENT_WORDS, help="words per request")
    args = parser.parse_args()

    load_dotenv()
    from openai import OpenAI

    src_dir = Path(f"data/org_docs/{args.course}")
    out_dir = Path(f"data/metadata/clean_transcripts/{args.course}")
    out_dir.mkdir(parents=True, exist_ok=True)
    files = sorted(src_dir.glob("*Transcript*.txt")) if args.all else [src_dir / f for f in args.files]
    missing = [f.name for f in files if not f.exists()]
    if missing:
        print(f"Not found in {src_dir}: {missing}")
        return 1

    glossary = build_glossary(args.course)
    print(f"Glossary: {len(glossary)} terms. Model: {args.model}. Files: {len(files)}.")
    client = OpenAI()
    report_path = out_dir / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    price_in, price_out = PRICES.get(args.model, (0.0, 0.0))
    spent = 0.0

    try:
        for f in files:
            target = out_dir / f.name
            if target.exists() and not args.force:
                print(f"[SKIP] already cleaned: {f.name}")
                continue
            original = f.read_text(encoding="utf-8", errors="replace")
            parts = segments(original, args.segment_words)
            cleaned_parts, file_report = [], {"segments": [], "input_tokens": 0, "output_tokens": 0}
            for i, part in enumerate(parts, 1):
                cleaned, seg, usage = clean_piece(client, args.model, glossary, part, f"part {i} of {len(parts)}")
                cleaned_parts.append(cleaned)
                file_report["segments"].append(seg)
                file_report["input_tokens"] += usage["input_tokens"]
                file_report["output_tokens"] += usage["output_tokens"]
            text = "\n\n".join(cleaned_parts) + "\n"
            target.write_text(text, encoding="utf-8")
            cost = file_report["input_tokens"] / 1e6 * price_in + file_report["output_tokens"] / 1e6 * price_out
            spent += cost
            whole = check(original, text, glossary)
            file_report.update(whole, cost_usd=round(cost, 4))
            report[f.name] = file_report
            report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
            flag = "  FLAG" if any(s["flag"] for s in file_report["segments"]) else ""
            print(f"[DONE] {f.name}: {whole['words_in']} -> {whole['words_out']} words "
                  f"({whole['ratio']:.0%}), {whole['unclear']} unclear, ${cost:.3f}{flag}")
    except ApiProblem as e:
        print(f"\nSTOPPED: {e}")
        print(f"Spent so far: about ${spent:.2f}. Finished files are kept in {out_dir}.")
        return 2

    print(f"\nFinished. About ${spent:.2f} spent. Cleaned files and report.json are in {out_dir}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
