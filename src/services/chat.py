"""Chat mode: course questions answered with retrieval. Ungraded, so it never changes mastery."""

from __future__ import annotations

import logging
import re
import time
from typing import Callable, List, Optional

from src.services.errors import InvalidInput
from src.services.events import EventRecorder, disabled
from src.services.models import ChatMessage, ChatReply, ChatState
from src.services.session_store import SessionStore

logger = logging.getLogger(__name__)

HISTORY_LIMIT = 50          # messages kept per learner and course
CONTEXT_MESSAGES = 10       # earlier messages of the sitting the model sees
FOLLOW_UP_WORDS = 12        # a follow-up is this short and refers back (see _retrieval_query)
# Words that make a short question refer to the previous one ("can you give an example?",
# "why is that?", "what about the second one?")
REFERRING_WORDS = {
    "it", "its", "this", "that", "these", "those", "they", "them", "their", "one", "ones",
    "example", "examples", "more", "else", "another", "why", "elaborate", "same", "above",
    "previous", "instead", "too", "also", "again",
}
MAX_MESSAGE_CHARS = 4000
CHAT_SITTING_GAP = 30 * 60  # seconds without a message that end a sitting (resets Q)
FAILURE_REPLY = "Sorry, I couldn't answer that just now. Please try again in a moment."


class ChatService:
    KIND = "chat"

    def __init__(self, orchestrator, store: SessionStore, redis_client=None, events: EventRecorder | None = None):
        self.orchestrator = orchestrator
        self.store = store
        self.redis_client = redis_client
        self.events = events or disabled()
        self.preview = None  # PreviewService: explanations of a teacher's preview turns

    def _load(self, username: str, course: str) -> ChatState:
        return (self.store.load(ChatState, self.KIND, username, course)
                or ChatState(username=username, course=course))

    def history(self, username: str, course: str) -> List[ChatMessage]:
        return self._load(username, course).messages

    def clear(self, username: str, course: str) -> None:
        self.store.delete(self.KIND, username, course)

    def send(self, username: str, course: str, week: int, text: str,
             on_token: Optional[Callable[[str], None]] = None) -> ChatReply:
        """Answer a question. The model sees the earlier messages of this sitting; with
        ``on_token`` the reply is streamed piece by piece as well as returned."""
        text = (text or "").strip()
        if not text:
            raise InvalidInput("Type a question first.")
        if len(text) > MAX_MESSAGE_CHARS:
            raise InvalidInput(f"Please keep questions under {MAX_MESSAGE_CHARS} characters.")

        with self.store.locked(self.KIND, username, course):
            state = self._load(username, course)
            now = time.time()
            if now - state.last_activity > CHAT_SITTING_GAP:
                state.turns = 0
                state.sitting_started = now
            earlier = [m for m in state.messages if m.timestamp >= state.sitting_started][-CONTEXT_MESSAGES:]
            state.turns += 1
            state.last_activity = now
            state.messages.append(ChatMessage(role="user", message=text, timestamp=now))
            self._remember(username, "chat", {"message": text, "course": course, "week": week, "timestamp": now})

            query = {
                "user_query": text,
                "retrieval_query": self._retrieval_query(text, earlier),
                "username": username,
                "selected_course": course,
                "selected_week": week,
                "current_mode": "chat",
                "conversation_history": [m.model_dump() for m in earlier],
                # Q in the cognitive-load formula: questions asked in this sitting
                "session_metadata": {"timestamp": now, "interface_mode": "chat", "message_count": state.turns},
            }
            result = self.orchestrator.process_query(query, on_token=on_token)

            if result.get("success"):
                reply = ChatReply(ok=True, message=result.get("final_response", ""))
                state.messages.append(ChatMessage(role="assistant", message=reply.message, timestamp=time.time()))
                self._remember(username, "chat_response", {
                    "user_message": text, "assistant_response": reply.message, "course": course,
                    "week": week, "cognitive_state": result.get("cognitive_load", {}), "timestamp": time.time(),
                })
            else:
                logger.error(f"Chat failed for {username}/{course}: {result.get('error')}")
                reply = ChatReply(ok=False, message=FAILURE_REPLY)
                # Unanswered: drop the question so a retry isn't a duplicate or an extra turn.
                state.messages.pop()
                state.turns -= 1

            if self.preview is not None and reply.ok and self.preview.is_preview(username):
                cognitive = result.get("cognitive_load") or {}
                scaffolding = result.get("scaffolding") or {}
                self.preview.record(username, course, {
                    "mode": "chat", "question": text[:300], "graded": False,
                    "learner": {"cognitive_load": cognitive.get("cl_value"), "zpd": cognitive.get("zpd_score"),
                                "motivation": None,
                                "scaffolding": scaffolding.get("intervention_type") if isinstance(scaffolding, dict)
                                else str(scaffolding)},
                    "sources": query.get("retrieved_sources", []),
                })
            del state.messages[:-HISTORY_LIMIT]
            self.store.save(state, self.KIND, username, course)
            self.events.learner(username, course, "chat_question", mode="chat", week=week, payload={
                "text": self.events.scrub(text, username), "answered": reply.ok,
                "turn_in_sitting": state.turns if reply.ok else state.turns + 1,
                "text_note": "own name removed; not fully anonymised",
            })
            return reply

    @staticmethod
    def _retrieval_query(text: str, earlier: List[ChatMessage]) -> str:
        """What to search the course material for. A short question that refers back
        ("can you give an example?", "why is that?") is searched together with the question
        before it; any other question ("what is a Q-table?") on its own."""
        previous = next((m.message for m in reversed(earlier) if m.role == "user"), None)
        words = re.findall(r"[a-z']+", text.lower())
        if previous and len(words) <= FOLLOW_UP_WORDS and REFERRING_WORDS.intersection(words):
            return f"{previous} {text}"
        return text

    def _remember(self, username: str, kind: str, content: dict) -> None:
        """Short-term memory for the consolidation worker (best effort)."""
        if self.redis_client is None:
            return
        try:
            self.redis_client.store_short_term_memory(username=username, interaction_type=kind, content=content)
        except Exception as e:
            logger.debug(f"Memory storage failed: {e}")
