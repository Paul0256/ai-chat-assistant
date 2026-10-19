"""The assistant: one entry point (`ask`) that adapters call for every customer message.

Order of checks for each message:
1. limits (length, messages per minute, daily cap): protect the business's bill;
2. emergency (healthcare only) and "talk to a person": handled without the model;
3. the model answers from the documents, or says it doesn't know, or declines
   medical advice; the core turns that into the final reply;
4. every exchange is logged, unanswered questions included.
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from . import safety
from .business import Business
from .knowledge import KnowledgeBase
from .llm.base import AnswerKind, AnswerRequest, LanguageModel
from .models import HandoffRequest, LogEntry, Reply, ReplyKind, Role, Turn
from .storage import ConversationLog, HandoffNotifier

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Limits:
    max_chars: int = 1000
    per_minute: int = 6  # messages per conversation
    per_day: int = 500  # messages for the whole business
    history_turns: int = 12  # turns sent back to the model
    idle_minutes: int = 120  # a conversation is forgotten after this


class _Conversation:
    def __init__(self, history_turns: int) -> None:
        self.turns: deque[Turn] = deque(maxlen=history_turns)
        self.recent: deque[datetime] = deque()
        self.last_seen: datetime | None = None


class Assistant:
    def __init__(
        self,
        business: Business,
        knowledge: KnowledgeBase,
        model: LanguageModel,
        conversation_log: ConversationLog,
        notifier: HandoffNotifier,
        limits: Limits | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.business = business
        self.knowledge = knowledge
        self.model = model
        self.log = conversation_log
        self.notifier = notifier
        self.limits = limits or Limits()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._conversations: dict[str, _Conversation] = {}
        self._day: date | None = None
        self._day_count = 0

    # ---- entry points ---------------------------------------------------------

    def greeting(self) -> Reply:
        return Reply(ReplyKind.ANSWER, self.business.greeting)

    def ask(self, conversation_id: str, text: str, channel: str = "web") -> Reply:
        text = text.strip()
        now = self.clock()
        conv = self._conversation(conversation_id, now)

        limited = self._check_limits(conv, text, now)
        if limited is not None:
            return limited  # not logged: nothing was answered, and spam would flood the log

        if self.business.medical and safety.is_emergency(text):
            reply = self._emergency()
        elif safety.wants_human(text):
            conv.turns.append(Turn(Role.CUSTOMER, text))
            # request_handoff records the reply and logs the exchange itself
            return self.request_handoff(
                conversation_id, reason="Customer asked for a person", channel=channel, question=text
            )
        else:
            reply = self._answer(conv, text)

        conv.turns.append(Turn(Role.CUSTOMER, text))
        conv.turns.append(Turn(Role.ASSISTANT, reply.text))
        self._log(now, conversation_id, channel, text, reply)
        return reply

    def request_handoff(
        self, conversation_id: str, reason: str, channel: str = "web", question: str | None = None
    ) -> Reply:
        """Pass the conversation to staff (the "Talk to a person" button or a typed request)."""
        now = self.clock()
        conv = self._conversation(conversation_id, now)
        request = HandoffRequest(now, conversation_id, channel, reason, tuple(conv.turns))
        try:
            self.notifier.notify(request)
        except Exception:
            log.exception("handoff notification failed for %s", conversation_id)
            return Reply(ReplyKind.ERROR, self._contact_fallback())
        b = self.business
        reply = Reply(
            ReplyKind.HANDOFF,
            f"I've passed your question to the {b.name} team. They will reply here as soon as possible. "
            f"If it's urgent, please call {b.phone}.",
        )
        conv.turns.append(Turn(Role.ASSISTANT, reply.text))
        self._log(now, conversation_id, channel, question or f"[handoff] {reason}", reply)
        return reply

    # ---- internals ------------------------------------------------------------

    def _answer(self, conv: _Conversation, text: str) -> Reply:
        request = AnswerRequest(self.business, self.knowledge, tuple(conv.turns), text)
        try:
            result = self.model.answer(request)
        except Exception:
            log.exception("model %s failed", self.model.name)
            return Reply(ReplyKind.ERROR, self._contact_fallback(), offer_handoff=True)
        b = self.business
        if result.kind is AnswerKind.ANSWER and result.text:
            return Reply(ReplyKind.ANSWER, result.text)
        if result.kind is AnswerKind.MEDICAL:
            return Reply(
                ReplyKind.MEDICAL,
                result.text
                or f"I can't give medical advice, and I don't want to guess about your health. "
                f"Please book a consultation or call us at {b.phone}, and a specialist will help you.",
                offer_handoff=True,
            )
        return Reply(
            ReplyKind.NOT_FOUND,
            result.text
            or f"I don't have that information, and I don't want to guess. "
            f"I can pass your question to our team, or you can call us at {b.phone}.",
            offer_handoff=True,
        )

    def _emergency(self) -> Reply:
        b = self.business
        return Reply(
            ReplyKind.EMERGENCY,
            f"This sounds urgent. Please call us right away at {b.phone}. "
            f"If we are closed, or you have trouble breathing or heavy bleeding, call {b.emergency_number} now.",
        )

    def _check_limits(self, conv: _Conversation, text: str, now: datetime) -> Reply | None:
        lim = self.limits
        if not text:
            return Reply(ReplyKind.LIMITED, "Please type your question.")
        if len(text) > lim.max_chars:
            return Reply(
                ReplyKind.LIMITED, f"Your message is too long. Please keep it under {lim.max_chars} characters."
            )
        while conv.recent and now - conv.recent[0] > timedelta(minutes=1):
            conv.recent.popleft()
        if len(conv.recent) >= lim.per_minute:
            return Reply(ReplyKind.LIMITED, "You're sending messages very quickly. Please wait a minute and try again.")
        if self._day != now.date():
            self._day, self._day_count = now.date(), 0
        if self._day_count >= lim.per_day:
            return Reply(ReplyKind.LIMITED, f"The assistant is taking a short break. {self._contact_fallback()}")
        conv.recent.append(now)
        self._day_count += 1
        return None

    def _conversation(self, conversation_id: str, now: datetime) -> _Conversation:
        idle = timedelta(minutes=self.limits.idle_minutes)
        for cid in [c for c, v in self._conversations.items() if v.last_seen and now - v.last_seen > idle]:
            del self._conversations[cid]
        conv = self._conversations.setdefault(conversation_id, _Conversation(self.limits.history_turns))
        conv.last_seen = now
        return conv

    def _contact_fallback(self) -> str:
        b = self.business
        return f"Please call us at {b.phone} or email {b.email}."

    def _log(self, now: datetime, conversation_id: str, channel: str, question: str, reply: Reply) -> None:
        try:
            self.log.append(LogEntry(now, conversation_id, channel, question, reply.text, reply.kind))
        except Exception:  # the customer still gets the answer
            log.exception("could not log conversation %s", conversation_id)
