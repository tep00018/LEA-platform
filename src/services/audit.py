"""The content audit (B5): findings about a course's materials, objectives and reference
questions, ranked, with the teacher's decisions kept across runs.

Runs are files in ``data/audits/<CODE>/`` (gitignored): ``runs/<id>.json`` (the findings
of one run against the live KC version) and ``decisions.json`` (accept or dismiss, with a
note, by finding key). Every run and every decision goes to the event log: accepted and
dismissed findings are how LEA measures each check's precision.

Only coverage and redundancy call OpenAI (embeddings, a fraction of a cent); everything
else is parsing and rules.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from src.onboarding import audit_checks as A
from src.onboarding import kc_model as K
from src.services.errors import InvalidInput, NotFound
from src.services.events import EventRecorder, disabled

EMBED_MODEL = "text-embedding-3-small"
EMBED_USD_PER_OBJECTIVE = 0.00002  # two short texts per objective, $0.02 per million tokens


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class AuditService:
    def __init__(self, registry, events: Optional[EventRecorder] = None,
                 embedder: Optional[Callable[[List[str]], List[List[float]]]] = None,
                 searcher: Optional[Callable[[str, str], Optional[tuple]]] = None):
        self.registry = registry
        self.events = events or disabled()
        self._embed = embedder
        self._search = searcher

    # ------------------------------------------------------------------ storage

    def folder(self, code: str) -> Path:
        return Path(self.registry.data_dir) / "audits" / code

    def _decisions(self, code: str) -> Dict[str, Dict[str, Any]]:
        path = self.folder(code) / "decisions.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def runs(self, code: str) -> List[Dict[str, Any]]:
        folder = self.folder(code) / "runs"
        if not folder.exists():
            return []
        runs = [json.loads(p.read_text(encoding="utf-8")) for p in folder.glob("*.json")]
        return sorted(({k: v for k, v in r.items() if k != "findings"} for r in runs),
                      key=lambda r: r["ran_at"], reverse=True)

    def _run(self, code: str, run_id: str) -> Dict[str, Any]:
        path = self.folder(code) / "runs" / f"{run_id}.json"
        if not path.exists():
            raise NotFound("No such audit run.")
        return json.loads(path.read_text(encoding="utf-8"))

    def latest(self, code: str) -> Optional[Dict[str, Any]]:
        """The latest run with each finding's decision, what's new since the run before,
        and what that run found that this one no longer does."""
        runs = self.runs(code)
        if not runs:
            return None
        run = self._run(code, runs[0]["id"])
        previous = self._run(code, runs[1]["id"]) if len(runs) > 1 else None
        before = {f["key"] for f in previous["findings"]} if previous else None
        decisions = self._decisions(code)
        for f in run["findings"]:
            d = decisions.get(f["key"], {})
            f["status"], f["note"] = d.get("status", "open"), d.get("note", "")
            f["new"] = before is not None and f["key"] not in before
        now = {f["key"] for f in run["findings"]}
        run["resolved_since_last"] = ([{"key": f["key"], "title": f["title"]} for f in previous["findings"]
                                       if f["key"] not in now] if previous else [])
        run["reviewed"] = sum(1 for f in run["findings"] if f["status"] != "open")
        return run

    # ------------------------------------------------------------------ running

    def estimate(self, code: str) -> Dict[str, Any]:
        model = self.registry.kc_model(code) or {}
        gos = len(K.gos_of(model))
        return {"usd": round(gos * EMBED_USD_PER_OBJECTIVE, 4), "objectives": gos,
                "notes": ["Coverage and redundancy embed each objective with OpenAI (text-embedding-3-small); "
                          "every other check reads the files and the model on this PC."]}

    def run(self, actor: str, code: str) -> Dict[str, Any]:
        model = self.registry.kc_model(code)
        if model is None:
            raise InvalidInput("Publish this course's objectives first: the audit checks the live version.")
        data = Path(self.registry.data_dir)
        bank = A.load_bank(data / "course_sources" / code / "question_bank.json")
        findings = (A.check_files(data / "org_docs" / code) + A.check_readability(data / "md_docs" / code)
                    + A.check_prerequisite_order(model) + A.check_bloom_balance(model)
                    + A.check_alignment(model, bank) + A.check_questions(bank))
        skipped = []
        try:
            findings += A.check_coverage(model, self._searcher(code))
            findings += A.check_redundancy(model, self._embedder())
        except Exception as e:  # no index, no key, no network: the other checks still count
            skipped.append(f"Coverage and redundancy weren't checked: {e}")
        findings = A.rank(findings)
        version = (model.get("version_info") or {}).get("version", 0)
        ran_at = datetime.now(timezone.utc).isoformat(timespec="microseconds")  # runs sort by it
        run = {"id": uuid.uuid4().hex[:12], "course": code, "kc_version": version, "ran_at": ran_at, "ran_by": actor,
               "counts": {s: sum(1 for f in findings if f["severity"] == s) for s in A.SEVERITY_ORDER},
               "total": len(findings), "skipped": skipped, "findings": findings}
        path = self.folder(code) / "runs" / f"{run['id']}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(run, indent=2, ensure_ascii=False), encoding="utf-8")
        self.events.staff(actor, "audit_run", course=code, payload={
            "run": run["id"], "kc_version": version, "total": len(findings), "counts": run["counts"],
            "by_check": {c: sum(1 for f in findings if f["check"] == c) for c in {f["check"] for f in findings}}})
        return self.latest(code)

    def decide(self, actor: str, code: str, key: str, status: str, note: str = "") -> Dict[str, Any]:
        if status not in ("open", "accepted", "dismissed"):
            raise InvalidInput("Status is accepted, dismissed or open.")
        latest = self.latest(code)
        match = next((f for f in (latest or {}).get("findings", []) if f["key"] == key), None)
        if match is None:
            raise NotFound("That finding isn't in the latest audit.")
        decisions = self._decisions(code)
        if status == "open":
            decisions.pop(key, None)
        else:
            decisions[key] = {"status": status, "note": note.strip()[:500], "by": actor, "at": _now(),
                              "check": match["check"], "tier": match["tier"]}
        path = self.folder(code) / "decisions.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(decisions, indent=2, ensure_ascii=False), encoding="utf-8")
        self.events.staff(actor, f"audit_{status}", course=code,
                          payload={"key": key, "check": match["check"], "tier": match["tier"],
                                   "severity": match["severity"], "has_note": bool(note.strip()),
                                   "target": match.get("target")})
        return {**match, "status": status, "note": note.strip()[:500] if status != "open" else ""}

    # ------------------------------------------------------------------ embeddings

    def _embedder(self) -> Callable[[List[str]], List[List[float]]]:
        if self._embed is not None:
            return self._embed
        from openai import OpenAI

        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        def embed(texts: List[str]) -> List[List[float]]:
            vectors: List[List[float]] = []
            for i in range(0, len(texts), 100):
                vectors += [d.embedding for d in client.embeddings.create(model=EMBED_MODEL, input=texts[i:i + 100]).data]
            return vectors
        return embed

    def _searcher(self, code: str) -> Callable[[str], Optional[tuple]]:
        """Best-matching chunk for a text: (similarity, source file), opened once per run."""
        if self._search is not None:
            return lambda text: self._search(code, text)
        import chromadb
        from chromadb.utils import embedding_functions

        path = self.registry.vector_store_path(code)
        if not (path / "chroma.sqlite3").exists():
            raise RuntimeError("the course has no retrieval library yet")
        embed = embedding_functions.OpenAIEmbeddingFunction(api_key=os.getenv("OPENAI_API_KEY"), model_name=EMBED_MODEL)
        collection = chromadb.PersistentClient(path=str(path)).get_collection(code, embedding_function=embed)

        def best(text: str) -> Optional[tuple]:
            found = collection.query(query_texts=[text], n_results=1, include=["metadatas", "distances"])
            if not found["ids"] or not found["ids"][0]:
                return None
            return (1 - found["distances"][0][0] / 2, found["metadatas"][0][0].get("source_file", ""))
        return best
