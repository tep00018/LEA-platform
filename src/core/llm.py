"""One helper for chat completions, streamed or not.

With ``on_token`` the reply is streamed and each piece of text is passed to the callback
as it arrives (the API forwards them to the browser); the full text is returned either way.
"""

from __future__ import annotations

from typing import Callable, Optional

TokenCallback = Callable[[str], None]


def complete(client, *, on_token: Optional[TokenCallback] = None, **kwargs) -> str:
    if on_token is None:
        response = client.chat.completions.create(**kwargs)
        return (response.choices[0].message.content or "").strip()
    parts = []
    for chunk in client.chat.completions.create(stream=True, **kwargs):
        if not chunk.choices:
            continue
        text = chunk.choices[0].delta.content or ""
        if text:
            parts.append(text)
            on_token(text)
    return "".join(parts).strip()
