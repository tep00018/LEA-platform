"""Chat remembers the current sitting: earlier messages reach the model, and short
follow-ups are searched together with the question before them."""

from src.services.chat import CHAT_SITTING_GAP
from src.services.models import ChatState

COURSE = "DEMO101"


def _chat_turns(call):
    return [(m["role"], m["content"]) for m in call["messages"][1:]]  # skip the system prompt


def _rag_queries(services):
    return [q["query"] for q in services.orchestrator.mcp_client.mcp_server.tool_registry.rag_tool.queries]


def test_model_sees_earlier_messages_of_the_sitting(services, fake_llm, username):
    replies = iter(["Supervised learning uses labelled data.", "For example, spam filtering."])
    fake_llm._responder = lambda m: next(replies)
    services.chat.send(username, COURSE, 1, "What is supervised learning?")
    services.chat.send(username, COURSE, 1, "Can you give an example?")
    assert _chat_turns(fake_llm.calls[-1]) == [
        ("user", "What is supervised learning?"),
        ("assistant", "Supervised learning uses labelled data."),
        ("user", "Can you give an example?"),
    ]
    # The short follow-up is searched with the question it follows
    assert _rag_queries(services)[-1] == "What is supervised learning? Can you give an example?"


def test_a_new_sitting_starts_without_context(services, fake_llm, username):
    fake_llm._responder = lambda m: "ok"
    services.chat.send(username, COURSE, 1, "What is supervised learning?")
    state = services.chat.store.load(ChatState, "chat", username, COURSE)
    state.last_activity -= CHAT_SITTING_GAP + 1
    state.messages = [m.model_copy(update={"timestamp": m.timestamp - CHAT_SITTING_GAP - 1}) for m in state.messages]
    services.chat.store.save(state, "chat", username, COURSE)

    services.chat.send(username, COURSE, 1, "What is reinforcement learning?")
    assert _chat_turns(fake_llm.calls[-1]) == [("user", "What is reinforcement learning?")]
    assert _rag_queries(services)[-1] == "What is reinforcement learning?"
    assert len(services.chat.history(username, COURSE)) == 4  # history is still shown


def test_long_questions_are_searched_on_their_own(services, fake_llm, username):
    fake_llm._responder = lambda m: "ok"
    services.chat.send(username, COURSE, 1, "What is supervised learning?")
    question = "How does the bias variance trade off change when a model gets more parameters and more data?"
    services.chat.send(username, COURSE, 1, question)
    assert _rag_queries(services)[-1] == question


def test_chat_reply_can_be_streamed(services, fake_llm, username):
    fake_llm._responder = lambda m: "Machine learning is learning from data."
    pieces = []
    reply = services.chat.send(username, COURSE, 1, "What is ML?", on_token=pieces.append)
    assert len(pieces) > 1 and "".join(pieces) == reply.message == "Machine learning is learning from data."
    assert fake_llm.calls[-1]["stream"] is True


def test_a_short_new_question_is_not_mixed_with_the_last_one(services, fake_llm, username):
    fake_llm._responder = lambda m: "ok"
    services.chat.send(username, COURSE, 1, "What is the bias variance trade-off?")
    services.chat.send(username, COURSE, 1, "What is a Q-table?")
    assert _rag_queries(services)[-1] == "What is a Q-table?"
    services.chat.send(username, COURSE, 1, "Why is that useful?")
    assert _rag_queries(services)[-1] == "What is a Q-table? Why is that useful?"
