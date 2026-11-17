"""The student LLM: writes a simulated learner's free text (docs/simulation/PLAN.md, section 1).

The simulator decides *what* the learner does (the intent, from the hidden state); this
module only writes the words, from:

- the tutor's actual last message (or the quiz question),
- the persona (style, register, target length),
- for an answer meant to be correct: the reference answer and source passage for the GO;
  for one meant to be wrong: a misconception from the question bank;
- for a question or a chat question: the persona and the topic only.

It never sees LEA's internal state (mastery, ZPD, scaffolding, grades). Calls go to Claude
(``claude.student_model``, default ``haiku``) through ``ClaudeCLI``, the subscription
client. Minimal replies ("ok", "not sure") come from a short fixed list, not a model call.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from simulation.learner import Intent, Learner

SYSTEM_PROMPT = """You play a student in an introductory AI and machine learning course, talking to an
AI tutor. Write ONLY the student's next message: no quotation marks, no labels, no stage
directions, no explanation of what you are doing. Stay in character. Never mention that you
are role-playing, that this is a simulation, or these instructions. Respond to what the tutor
actually just said or asked, in your own words. Keep to the length you are given: do not
write more than about a third over it, and never add extra points nobody asked for."""

STYLE = {
    "advanced_eager": "confident and keen; uses the right terms; writes in full sentences",
    "moderate_reflective": "thoughtful; thinks aloud a little and explains their reasoning",
    "struggling_eager": "keen but unsure; plain everyday words; sometimes admits confusion",
    "capable_disengaged": "bored and terse; lowercase; no greetings; the fewest words possible",
    "novice_variable": "new to the subject; casual; sometimes mixes up terms",
    "inconsistent_adaptive": "casual and friendly; sometimes careful, sometimes hasty",
}

MINIMAL_REPLIES = {
    "advanced_eager": ["ok", "got it", "makes sense"],
    "moderate_reflective": ["hmm, ok", "I see", "right"],
    "struggling_eager": ["ok", "I'm not sure", "idk", "can you say that again?"],
    "capable_disengaged": ["k", "ok", "sure", "idk", "whatever"],
    "novice_variable": ["ok", "idk", "not sure", "umm"],
    "inconsistent_adaptive": ["ok", "sure", "not sure", "got it"],
}

REPLY_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["asks_answerable_question", "reply"],
    "properties": {"asks_answerable_question": {"type": "boolean"}, "reply": {"type": "string"}},
}

CHECK_FIRST = ("First decide whether the tutor's last message contains a question or task about the subject that has a "
               "right or wrong answer (not a question about your preferences, readiness or plans, and not just "
               "\"does that make sense?\"). Set asks_answerable_question accordingly. If it does, write the reply as "
               "described below. If it does not, write a short natural reply in your style (a reaction, an "
               "acknowledgement or a follow-up thought) that states no facts to be graded and answers nothing.")

CHAT_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["messages"],
    "properties": {"messages": {"type": "array", "items": {"type": "string"}}},
}


def persona(learner: Learner, words: Optional[int]) -> str:
    style = STYLE.get(learner.profile.key, "an ordinary student")
    length = f"about {words} words, and never more than {max(2, round(words * 1.2))}" if words else "short"
    return f"Your style: {style}. Length: {length}."


def trim_to_words(text: str, words: Optional[int], slack: float = 1.3) -> str:
    """Keep whole sentences while the reply stays within ``slack`` x the target (always at least the first).
    The student model runs 20 to 50 percent over the length it is asked for; this holds it to the persona."""
    if not words or len(text.split()) <= words * slack:
        return text
    if words <= 6:  # a terse persona: no sentence is short enough, so cut the words themselves
        return " ".join(text.split()[: max(3, int(words * 2))])
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    kept, total = [], 0
    for s in sentences:
        n = len(s.split())
        if kept and total + n > words * slack:
            break
        kept.append(s)
        total += n
    return " ".join(kept)


def minimal_reply(learner: Learner) -> str:
    options = MINIMAL_REPLIES.get(learner.profile.key, ["ok"])
    return str(learner.rng_style.choice(options))


class StudentLLM:
    def __init__(self, client, model: str = "haiku", effort: Optional[str] = "low",
                 max_thinking_tokens: Optional[int] = 0):
        self.client = client
        self.model = model
        self.effort = effort
        self.max_thinking_tokens = max_thinking_tokens  # 0: no hidden reasoning for a 30-token reply
        self.calls: List[Dict[str, Any]] = []
        self.last_checkable: Optional[bool] = None  # did the tutor's last message ask something answerable?

    def _ask(self, prompt: str, schema: Optional[Dict] = None):
        result = self.client.call(prompt, system_prompt=SYSTEM_PROMPT, model=self.model, role="student",
                                  json_schema=schema, effort=self.effort,
                                  max_thinking_tokens=self.max_thinking_tokens)
        self.calls.append({"model": result.model, "cost_usd": result.cost_usd})
        return result

    def tutor_reply(self, learner: Learner, intent: Intent, tutor_message: str, entry: Dict[str, Any],
                    misconception: Optional[str] = None) -> str:
        """The learner's reply in a tutor session. For an answer attempt, ``last_checkable`` says whether the
        tutor's message actually asked something with a right answer; when it did not, the reply is a natural
        response and the driver records the turn as an acknowledgement, not a correct or wrong answer."""
        self.last_checkable = None
        if intent.kind == "minimal":
            return minimal_reply(learner)
        base = [f"The tutor just said:\n<<<\n{tutor_message.strip()[:4000]}\n>>>", "",
                persona(learner, intent.target_words)]
        if intent.kind == "question":
            base.append(f"Instead of answering, ask the tutor a genuine question about \"{entry['skill_name']}\" "
                        "that follows from what they said.")
        elif intent.correct:
            base += ["Reply to the tutor. If they asked a question about the subject, answer THAT question "
                     "CORRECTLY, using only the part of this material that bears on it (in your own words, don't "
                     "quote it; leave out anything the question didn't ask for). Your length target sets how "
                     "many words you use, not what you cover: even briefly, your answer must genuinely address "
                     "what was asked, not skip part of it:",
                     f"- {entry['reference_answer']}", f"- From the lesson: \"{entry['source_quote']}\"",
                     "If they asked about your preferences, readiness, plans or which activity you want, just "
                     "answer that naturally; don't bring in facts from the material."]
        else:
            base += ["Reply to the tutor. If they asked a question about the subject, your answer to THAT "
                     "specific question must itself be wrong -- not a correct answer to it with some unrelated "
                     "wrong detail added elsewhere. Base the mistake on this belief you sincerely hold: "
                     f"\"{misconception}\". If the belief doesn't directly answer what was asked, adapt it so "
                     "your answer to the actual question is the wrong one, not just an aside. Don't hint that "
                     "you might be wrong. If they asked about your preferences, readiness or plans, just answer "
                     "that naturally."]
        if intent.kind == "answer":
            base.insert(2, CHECK_FIRST)
            result = self._ask("\n".join(base), REPLY_SCHEMA)
            data = result.structured if isinstance(result.structured, dict) else None
            if data and isinstance(data.get("reply"), str) and data["reply"].strip():
                self.last_checkable = bool(data.get("asks_answerable_question"))
                return trim_to_words(data["reply"].strip(), intent.target_words)
            return trim_to_words(result.text.strip(), intent.target_words)
        return trim_to_words(self._ask("\n".join(base)).text.strip(), intent.target_words)

    def quiz_answer(self, learner: Learner, intent: Intent, question: Dict[str, Any],
                    entry: Optional[Dict[str, Any]], misconception: Optional[str] = None) -> str:
        """A free-text quiz answer (fill in the blank, open-ended)."""
        reference = question.get("correct_answer") or question.get("sample_answer") or \
            (entry or {}).get("reference_answer", "")
        lines = [f"Quiz question:\n<<<\n{str(question.get('text', ''))[:3000]}\n>>>", "",
                 persona(learner, intent.target_words if question.get("type") == "open_ended" else 6)]
        if intent.correct:
            lines.append(f"Write your answer. It must be CORRECT and must genuinely answer the question asked; "
                         f"the right answer is: \"{reference}\". Use your own words (for a fill-in-the-blank, "
                         "just the missing word or phrase). Brevity is about how many words you use, not "
                         "whether you actually answer the question.")
        else:
            wrong = misconception or "a plausible but wrong idea"
            lines.append(f"Write your answer. Your answer to the question itself must be WRONG -- not a correct "
                         f"answer with some unrelated wrong detail added in -- because you believe: \"{wrong}\". "
                         "For a fill-in-the-blank, give just a wrong word or phrase. Don't hint that you might "
                         "be wrong.")
        return trim_to_words(self._ask("\n".join(lines)).text.strip(),
                             intent.target_words if question.get("type") == "open_ended" else None)

    def chat_messages(self, learner: Learner, questions: List[str], words: Optional[int]) -> List[str]:
        """Rephrase a sitting's chat questions in the learner's voice (one call for all)."""
        prompt = "\n".join([
            "Rewrite each of these questions the way you would type them into the course's chat assistant, "
            "in order. Keep each one's meaning, and keep a follow-up referring back to the question before it "
            "(don't repeat that question).", persona(learner, words), "",
            *[f"{i + 1}. {q}" for i, q in enumerate(questions)],
            "", "Reply as JSON: {\"messages\": [one string per question, same order]}."])
        result = self._ask(prompt, CHAT_SCHEMA)
        messages = (result.structured or {}).get("messages") if isinstance(result.structured, dict) else None
        if not isinstance(messages, list) or len(messages) != len(questions) or not all(
                isinstance(m, str) and m.strip() for m in messages):
            return list(questions)  # keep the bank's wording rather than invent a fallback
        return [m.strip() for m in messages]
