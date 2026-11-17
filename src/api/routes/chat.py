"""Chat mode."""

from fastapi import APIRouter, Depends, Response, status

from src.api import deps
from src.api.schemas import ChatIn
from src.api.streaming import stream
from src.services.container import Services
from src.services.errors import Unavailable
from src.services.models import ChatMessage, ChatReply

router = APIRouter(prefix="/chat/{code}", tags=["chat"])


def _checked(reply: ChatReply) -> ChatReply:
    if not reply.ok:
        raise Unavailable(reply.message)
    return reply


@router.get("/messages", response_model=list[ChatMessage])
def history(code: str = Depends(deps.enrolled_course), user: str = Depends(deps.current_user),
            svc: Services = Depends(deps.services)):
    return svc.chat.history(user, code)


@router.post("/messages", response_model=ChatReply)
def send(body: ChatIn, code: str = Depends(deps.enrolled_course), user: str = Depends(deps.model_budget),
         svc: Services = Depends(deps.services)):
    """Ask a question; the reply comes back when complete. See ``/messages/stream``."""
    deps.require_week(code, body.week, svc)
    return _checked(svc.chat.send(user, code, body.week, body.text))


@router.post("/messages/stream", response_class=Response,
             responses={200: {"content": {"text/event-stream": {}},
                              "description": "Server-sent events: `token` ({text}) while the model writes, "
                                             "then `done` (ChatReply) or `error` ({detail, code, status})."}})
def send_streamed(body: ChatIn, code: str = Depends(deps.enrolled_course), user: str = Depends(deps.model_budget),
                  svc: Services = Depends(deps.services)):
    deps.require_week(code, body.week, svc)
    return stream(lambda on_token: _checked(svc.chat.send(user, code, body.week, body.text, on_token=on_token)),
                  lambda reply: reply.model_dump())


@router.delete("/messages", status_code=status.HTTP_204_NO_CONTENT)
def clear(code: str = Depends(deps.enrolled_course), user: str = Depends(deps.current_user),
          svc: Services = Depends(deps.services)):
    svc.chat.clear(user, code)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
