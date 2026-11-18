"""Tell the owner when someone uses a demo or trial assistant.

A trial is only useful if we know when the business tries it: then we can
follow up the same day. Wraps the conversation log: the first exchange of every
conversation, and every "talk to a person", is emailed to the owner. Sending
runs in the background, so the visitor never waits for it, and a daily cap
keeps a busy day from flooding the inbox.
"""

from __future__ import annotations

import logging
import threading
from datetime import date
from email.message import EmailMessage

from ..core.models import LogEntry, ReplyKind
from ..core.storage import ConversationLog

log = logging.getLogger(__name__)


class UsageAlertLog:
    REMEMBER = 5000  # conversation ids already reported

    def __init__(
        self,
        inner: ConversationLog,
        mailer,
        sender: str,
        recipient: str,
        label: str,
        per_day: int = 30,
        background: bool = True,
    ) -> None:
        self.inner = inner
        self.mailer = mailer  # anything with send(EmailMessage), e.g. EmailNotifier
        self.sender, self.recipient, self.label = sender, recipient, label
        self.per_day = per_day
        self.background = background
        self._seen: dict[str, None] = {}
        self._day: date | None = None
        self._sent_today = 0
        self._lock = threading.Lock()

    def append(self, entry: LogEntry) -> None:
        self.inner.append(entry)
        first = entry.conversation_id not in self._seen
        if not (first or entry.kind is ReplyKind.HANDOFF) or entry.kind is ReplyKind.LIMITED:
            return
        with self._lock:
            self._seen[entry.conversation_id] = None
            while len(self._seen) > self.REMEMBER:
                self._seen.pop(next(iter(self._seen)))
            today = entry.timestamp.date()
            if today != self._day:
                self._day, self._sent_today = today, 0
            if self._sent_today >= self.per_day:
                return
            self._sent_today += 1
        msg = self.message(entry, first)
        if self.background:
            threading.Thread(target=self._send, args=(msg,), daemon=True).start()
        else:
            self._send(msg)

    def message(self, entry: LogEntry, first: bool) -> EmailMessage:
        what = "asked for a person" if entry.kind is ReplyKind.HANDOFF else "started a conversation"
        msg = EmailMessage()
        msg["Subject"] = f"{self.label}: someone {what}"
        msg["From"] = self.sender
        msg["To"] = self.recipient
        msg.set_content(
            f"{self.label}: someone {what}.\n\n"
            f"Time (UTC): {entry.timestamp:%Y-%m-%d %H:%M}\n"
            f"Conversation: {entry.conversation_id}\n"
            f"Reply kind: {entry.kind.value}\n\n"
            f"Visitor: {entry.question}\n\n"
            f"Assistant: {entry.answer}\n"
        )
        return msg

    def _send(self, msg: EmailMessage) -> None:
        try:
            self.mailer.send(msg)
        except Exception:  # an alert must never break the chat
            log.exception("usage alert could not be sent")

    def close(self) -> None:
        close = getattr(self.inner, "close", None)
        if close is not None:
            close()
