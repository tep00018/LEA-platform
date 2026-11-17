"""Server-sent events for streamed chat and tutor replies.

The stream sends ``token`` events (``{"text": ...}``) as the model writes, then exactly
one of:

- ``done``  with the same JSON body the non-streaming endpoint returns. Clients should
  replace the streamed text with the final message it contains;
- ``error`` with ``{"detail", "code", "status"}``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from typing import Any, AsyncIterator, Callable

from fastapi.responses import StreamingResponse

from src.api.errors import status_for
from src.services.errors import ServiceError

logger = logging.getLogger(__name__)

_END = object()


def sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def stream(call: Callable[[Callable[[str], None]], Any], finish: Callable[[Any], dict]) -> StreamingResponse:
    """Run ``call(on_token)`` on its own thread and stream its tokens, then ``finish(result)``.

    The response body is an async generator waiting on an asyncio queue, so a stream holds
    no worker thread while it waits for the model. If the client disconnects, the call
    still completes, so the reply is saved and shows up next time the conversation loads.
    """

    async def body() -> AsyncIterator[str]:
        loop = asyncio.get_running_loop()
        events: "asyncio.Queue" = asyncio.Queue()

        def put(item) -> None:
            loop.call_soon_threadsafe(events.put_nowait, item)

        def work():
            try:
                result = call(lambda text: put(("token", text)))
                put(("done", finish(result)))
            except ServiceError as e:
                put(("error", {"detail": str(e), "code": type(e).__name__, "status": status_for(e)}))
            except Exception:
                logger.exception("Streamed request failed")
                put(("error", {"detail": "Something went wrong. Please try again.", "code": "InternalError",
                               "status": 500}))
            finally:
                put(_END)

        threading.Thread(target=work, name="sse-worker", daemon=True).start()
        while True:
            item = await events.get()
            if item is _END:
                return
            kind, payload = item
            yield sse(kind, {"text": payload} if kind == "token" else payload)

    return StreamingResponse(body(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
