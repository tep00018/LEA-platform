"""Watching LEA from inside the simulator process, without changing it.

- ``OpenAIMeter`` wraps the OpenAI SDK's chat-completion and embedding ``create`` methods
  (class level, for the run only) to record every model ID, token count and cost LEA
  incurs. It never changes a request or a response. The harness checks the budget
  between turns; the meter never interrupts a call.
- ``RetrievalSpy`` wraps LEA's ``get_course_content_via_rag`` on one orchestrator to
  record each query and the sources it returned (Chat and Tutor both retrieve through
  it). The call and its result pass through untouched.
- ``read_decisions`` reads the orchestrator's decisions (learner state, cognitive load,
  scaffolding, motivation) that LEA itself wrote to the run's event log.

Principle 1 of the plan: the simulator may read internal state a student can't see; it
never adds an API route or response field.
"""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

import openai.resources.chat.completions as chat_mod
import openai.resources.embeddings as emb_mod

# USD per 1M tokens (input, output). Unknown models are priced as the dearest listed and flagged.
PRICES = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    "text-embedding-3-small": (0.02, 0.0),
    "text-embedding-3-large": (0.13, 0.0),
}
FALLBACK_PRICE = (2.50, 10.00)


def price(model: str) -> tuple[tuple[float, float], bool]:
    name = (model or "").lower()
    for known in sorted(PRICES, key=len, reverse=True):  # longest prefix first (gpt-4o-mini before gpt-4o)
        if name.startswith(known):
            return PRICES[known], True
    return FALLBACK_PRICE, False


class BudgetExceeded(RuntimeError):
    pass


class OpenAIMeter:
    """Records LEA's OpenAI usage while active (a context manager)."""

    def __init__(self, budget_usd: float):
        self.budget_usd = float(budget_usd)
        self.calls: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        self._originals: Dict[Any, Any] = {}
        self._mark = 0

    # -- totals
    @property
    def usd(self) -> float:
        return round(sum(c["usd"] for c in self.calls), 6)

    def models(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for c in self.calls:
            out[c["model"]] = out.get(c["model"], 0) + 1
        return out

    def since_mark(self) -> Dict[str, Any]:
        """Usage since the last call to this method (one simulated turn)."""
        with self._lock:
            new, self._mark = self.calls[self._mark:], len(self.calls)
        return {"calls": len(new), "usd": round(sum(c["usd"] for c in new), 6),
                "tokens": sum(c["input_tokens"] + c["output_tokens"] for c in new),
                "models": sorted({c["model"] for c in new})}

    def check_budget(self) -> None:
        if self.usd >= self.budget_usd:
            raise BudgetExceeded(f"LEA's OpenAI spend reached the run budget (${self.usd:.2f} of "
                                 f"${self.budget_usd:.2f}); stopping cleanly.")

    # -- recording
    def _record(self, kind: str, response: Any, requested: Optional[str]) -> None:
        model = getattr(response, "model", None) or requested or "unknown"
        usage = getattr(response, "usage", None)
        tin = int(getattr(usage, "prompt_tokens", 0) or 0)
        tout = int(getattr(usage, "completion_tokens", 0) or 0)
        (pin, pout), known = price(model)
        with self._lock:
            self.calls.append({"kind": kind, "model": model, "input_tokens": tin, "output_tokens": tout,
                               "usd": (tin * pin + tout * pout) / 1_000_000, "priced": known,
                               "metered": usage is not None})

    def _wrap(self, cls, kind: str):
        original = cls.create
        meter = self

        def create(self_, *args, **kwargs):
            response = original(self_, *args, **kwargs)
            if kwargs.get("stream"):
                meter._record(kind, None, kwargs.get("model"))  # usage unknown for streams; counted as a call
            else:
                meter._record(kind, response, kwargs.get("model"))
            return response

        self._originals[cls] = original
        cls.create = create

    def __enter__(self) -> "OpenAIMeter":
        self._wrap(chat_mod.Completions, "chat")
        self._wrap(emb_mod.Embeddings, "embedding")
        return self

    def __exit__(self, *exc) -> None:
        for cls, original in self._originals.items():
            cls.create = original
        self._originals.clear()


class RetrievalSpy:
    """Records what LEA retrieved for each query (per turn: ``take()``)."""

    def __init__(self, orchestrator):
        self.client = orchestrator.mcp_client
        self._original = self.client.get_course_content_via_rag
        self._buffer: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        spy = self

        def get_course_content_via_rag(*args, **kwargs):
            result = spy._original(*args, **kwargs)
            query = kwargs.get("query", args[0] if args else None)
            sources = result.get("sources", []) if isinstance(result, dict) else []
            with spy._lock:
                spy._buffer.append({"query": query, "success": bool(isinstance(result, dict) and result.get("success")),
                                    "content": (result.get("content") or "")[:8000] if isinstance(result, dict) else "",
                                    "sources": [{"source": s.get("source") or s.get("source_file"),
                                                 "excerpt": (s.get("excerpt") or s.get("content") or "")[:1500]}
                                                for s in sources if isinstance(s, dict)]})
            return result

        self.client.get_course_content_via_rag = get_course_content_via_rag

    def take(self) -> List[Dict[str, Any]]:
        with self._lock:
            out, self._buffer = self._buffer, []
        return out

    def remove(self) -> None:
        self.client.get_course_content_via_rag = self._original


def read_decisions(log, pseudonym: str, after_id: int) -> tuple[List[Dict[str, Any]], int]:
    """Rows LEA wrote to the run's event log for this learner since ``after_id``."""
    rows = log.query("id > ? AND username_hash = ?", [after_id, pseudonym])
    last = max([after_id] + [int(r["id"]) for r in rows])
    out = []
    for r in rows:
        payload = r.get("payload_json")
        try:
            payload = json.loads(payload) if payload else {}
        except (TypeError, json.JSONDecodeError):
            payload = {}
        out.append({"id": r["id"], "type": r["type"], "mode": r.get("mode"), "go_id": r.get("go_id"),
                    "correct": r.get("correct"), "score": r.get("score"), "payload": payload})
    return out, last


@contextmanager
def spies(services, budget_usd: float):
    meter = OpenAIMeter(budget_usd)
    spy = RetrievalSpy(services.learning.orchestrator)
    with meter:
        try:
            yield meter, spy
        finally:
            spy.remove()
