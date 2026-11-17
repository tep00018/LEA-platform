"""Test doubles: a scripted stand-in for the OpenAI client and a stub retrieval tool.

``FakeLLM`` mimics the slice of the OpenAI v1 client LEA uses
(``client.chat.completions.create(...)``). Each call is recorded, and the reply comes
from a responder function that receives the messages, so a test can return different
JSON for question generation and for grading.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, Callable


def _completion(text: str) -> SimpleNamespace:
    message = SimpleNamespace(content=text, role="assistant")
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop", index=0)])


def _stream(text: str):
    """Chunks shaped like the OpenAI streaming API: one per word (with its space)."""
    pieces = [w + " " for w in text.split(" ")]
    pieces[-1] = pieces[-1][:-1]
    for piece in pieces:
        yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=piece), index=0)])


class FakeLLM:
    def __init__(self, responder: Callable[[list[dict]], str] | str | dict | None = None):
        self.calls: list[dict[str, Any]] = []
        if responder is None:
            responder = "OK"
        if isinstance(responder, dict):
            payload = json.dumps(responder)
            responder = lambda messages: payload  # noqa: E731
        elif isinstance(responder, str):
            text = responder
            responder = lambda messages: text  # noqa: E731
        self._responder = responder
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self.embeddings = SimpleNamespace(create=self._embed)

    def _embed(self, input, model=None, **kwargs):
        texts = [input] if isinstance(input, str) else list(input)
        # Deterministic 1536-dim vectors so Chroma queries work without the network.
        data = [SimpleNamespace(embedding=[((hash(t) >> i) & 1) * 1.0 for i in range(1536)], index=i)
                for i, t in enumerate(texts)]
        return SimpleNamespace(data=data, model=model or "fake-embedding")

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        text = self._responder(kwargs.get("messages", []))
        if kwargs.get("stream"):
            return _stream(text)
        return _completion(text)

    @property
    def last_prompt(self) -> str:
        messages = self.calls[-1]["messages"] if self.calls else []
        return "\n".join(m.get("content", "") for m in messages)


class StubRAGTool:
    """Replaces RAGRetrievalTool so tests never load models or call embeddings."""

    def __init__(self, *args, **kwargs):
        self.course_collections = {}
        self.queries: list[dict] = []

    def execute(self, parameters: dict):
        query = parameters.get("query", "")
        course = parameters.get("course", "DEMO101")
        max_results = parameters.get("max_results", 3)
        self.queries.append({"query": query, "course": course, "max_results": max_results})
        return {
            "success": True,
            "results": [{"content": f"Course notes about {query}", "metadata": {"source_file": "notes.md"}}],
            "num_results": 1,
            "course": course,
        }

    def get_available_courses(self):
        return list(self.course_collections)

    def get_schema(self):
        return {"name": "rag_retrieval", "description": "stub", "parameters": {"type": "object", "properties": {}}}
