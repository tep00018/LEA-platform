"""A Claude stand-in for the OpenAI client LEA uses, to try LEA on Sonnet (never a default).

LEA's model calls all look like ``client.chat.completions.create(messages=..., ...)``,
optionally streamed, and read ``response.choices[0].message.content``. ``ClaudeChatClient``
answers those calls with Claude through the researcher's subscription (``ClaudeCLI``: no API
key, guarded and metered), so ``build_services(openai_client=ClaudeChatClient(...))``
runs the real services, orchestrator, grading and quiz engine on Claude. Nothing in
``src/`` changes and LEA's deployed default stays OpenAI.

- The ``model`` argument (LEA hard-codes ``gpt-4o-mini``) is ignored; ``self.model`` decides.
- ``temperature`` can't be set with ``claude -p`` and is ignored (the manifest says so).
- JSON mode (``response_format={"type": "json_object"}``) becomes an instruction, and
  any code fence around the reply is removed.
- ``max_tokens`` becomes a length hint in the system prompt.
- Streaming yields the whole reply as one chunk.
- Embeddings stay on OpenAI: LEA's retrieval uses Chroma's own OpenAI embedding function,
  which does not go through this client.
"""

from __future__ import annotations

import re
import time
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from simulation.llm.usage_guard import ClaudeStop

FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.S)
JSON_NOTE = "Reply with one valid JSON object only: no markdown, no code fences, no text outside the JSON."


def flatten(messages: List[Dict[str, Any]]) -> tuple[str, str]:
    """(system prompt, prompt) from OpenAI-style messages."""
    system = "\n\n".join(str(m["content"]) for m in messages if m.get("role") == "system")
    turns = [m for m in messages if m.get("role") != "system"]
    if len(turns) == 1 and turns[0].get("role") == "user":
        return system, str(turns[0]["content"])
    lines = [f"{str(m.get('role', 'user')).upper()}: {m['content']}" for m in turns]
    return system, "\n\n".join(lines) + "\n\nWrite the next ASSISTANT message."


def unfence(text: str) -> str:
    """The JSON inside a code fence or surrounded by chatter."""
    text = text.strip()
    fenced = FENCE.match(text)
    if fenced:
        text = fenced.group(1).strip()
    if not text.startswith("{") and "{" in text and "}" in text:
        text = text[text.index("{"): text.rindex("}") + 1]
    return text


class ClaudeChatClient:
    def __init__(self, client, model: str = "sonnet", role: str = "lea", effort: Optional[str] = None,
                 max_thinking_tokens: Optional[int] = 0):
        self.client = client              # a ClaudeCLI (or PausingClient around it)
        self.model = model
        self.role = role
        self.effort = effort
        self.max_thinking_tokens = max_thinking_tokens
        self.calls: List[Dict[str, Any]] = []
        # LEA catches model errors and carries on with a fallback, so a usage stop raised in
        # here would be swallowed; remember it so the harness can end the session instead.
        self.stop_reason: Optional[str] = None
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self.embeddings = SimpleNamespace(create=self._no_embeddings)

    @staticmethod
    def _no_embeddings(*args, **kwargs):
        raise NotImplementedError("Embeddings stay on OpenAI (Chroma's own embedding function).")

    def _create(self, *, messages, model=None, temperature=None, max_tokens=None, response_format=None,
                stream=False, **kwargs):
        system, prompt = flatten(messages)
        wants_json = isinstance(response_format, dict) and response_format.get("type") == "json_object"
        notes = []
        if wants_json:
            notes.append(JSON_NOTE)
        elif max_tokens:
            notes.append(f"Keep your reply within about {int(max_tokens)} tokens.")
        system = "\n\n".join(x for x in [system or "You are a helpful assistant.", *notes] if x)
        started = time.monotonic()
        try:
            result = self.client.call(prompt, system_prompt=system, model=self.model, role=self.role,
                                      effort=self.effort, max_thinking_tokens=self.max_thinking_tokens)
        except ClaudeStop as e:
            self.stop_reason = str(e)
            raise
        text = unfence(result.text) if wants_json else result.text.strip()
        self.calls.append({"seconds": round(time.monotonic() - started, 2), "cost_usd": result.cost_usd,
                           "json": wants_json, "model": result.model, "prompt_head": prompt[:120].replace("\n", " "),
                           "system_head": system[:120].replace("\n", " ")})
        if stream:
            return iter([SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text))])])
        usage = result.usage or {}
        return SimpleNamespace(
            model=result.model,
            choices=[SimpleNamespace(index=0, finish_reason="stop",
                                     message=SimpleNamespace(role="assistant", content=text))],
            usage=SimpleNamespace(prompt_tokens=usage.get("input_tokens", 0),
                                  completion_tokens=usage.get("output_tokens", 0),
                                  total_tokens=usage.get("input_tokens", 0) + usage.get("output_tokens", 0)))
