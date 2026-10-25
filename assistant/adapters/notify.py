"""Tell staff that a customer wants a person: Telegram, email, or both.

Each notifier raises if it could not deliver; the core then shows the customer
the business's phone and email instead of promising a reply that won't come.
"""

from __future__ import annotations

import json
import logging
import smtplib
import ssl
import threading
import urllib.request
from collections import OrderedDict
from collections.abc import Callable, Sequence
from email.message import EmailMessage

from ..core.models import HandoffRequest, Role
from ..core.storage import HandoffNotifier

log = logging.getLogger(__name__)

TELEGRAM_LIMIT = 4096
LABELS = {Role.CUSTOMER: "Customer", Role.ASSISTANT: "Assistant", Role.STAFF: "Staff"}


def format_handoff(request: HandoffRequest, business_name: str, max_turns: int = 12) -> str:
    lines = [
        f"Customer wants a person · {business_name}",
        f"Time (UTC): {request.timestamp:%Y-%m-%d %H:%M}",
        f"Channel: {request.channel} · Conversation: {request.conversation_id}",
        f"Reason: {request.reason}",
        "",
    ]
    turns = request.transcript[-max_turns:]
    if len(request.transcript) > max_turns:
        lines.append(f"(last {max_turns} messages)")
    lines += [f"{LABELS[t.role]}: {t.text}" for t in turns] or ["(no messages yet)"]
    return "\n".join(lines)


def _post_json(url: str, payload: dict, timeout: float = 10) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (fixed https URL)
        return json.loads(resp.read().decode())


class TelegramNotifier:
    """Posts the handoff to a staff chat or group through the Telegram Bot API.

    Plain text only (no parse_mode), so nothing a customer types can change the formatting.
    """

    REMEMBER = 2000  # notifications staff can still reply to

    def __init__(
        self, token: str, chat_id: str, business_name: str, post: Callable[[str, dict], dict] = _post_json
    ) -> None:
        self.api = f"https://api.telegram.org/bot{token}"
        self.chat_id = str(chat_id)
        self.business_name = business_name
        self._post = post
        # Telegram message id of each notification -> conversation id, so a staff
        # member's reply to that message can be routed back to the customer.
        self.sent: OrderedDict[int, str] = OrderedDict()
        self._lock = threading.Lock()

    def notify(self, request: HandoffRequest) -> None:
        text = format_handoff(request, self.business_name) + "\n\nReply to this message to answer the customer."
        if len(text) > TELEGRAM_LIMIT:
            text = text[: TELEGRAM_LIMIT - 20] + "\n… (shortened)"
        result = self.send(text)
        message_id = (result.get("result") or {}).get("message_id")
        if message_id is not None:
            with self._lock:
                self.sent[int(message_id)] = request.conversation_id
                while len(self.sent) > self.REMEMBER:
                    self.sent.popitem(last=False)

    def send(self, text: str, reply_to: int | None = None) -> dict:
        payload: dict = {"chat_id": self.chat_id, "text": text, "disable_web_page_preview": True}
        if reply_to is not None:
            payload["reply_to_message_id"] = reply_to
        result = self._post(f"{self.api}/sendMessage", payload)
        if not result.get("ok"):
            raise RuntimeError(f"Telegram refused the message: {result.get('description', 'unknown error')}")
        return result

    def conversation_for(self, message_id: int) -> str | None:
        with self._lock:
            return self.sent.get(message_id)


class EmailNotifier:
    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        sender: str,
        recipients: Sequence[str],
        business_name: str,
        smtp_factory: Callable[[str, int], smtplib.SMTP] | None = None,
    ) -> None:
        self.host, self.port = host, port
        self.username, self.password = username, password
        self.sender, self.recipients = sender, list(recipients)
        self.business_name = business_name
        self._smtp_factory = smtp_factory

    def build_message(self, request: HandoffRequest) -> EmailMessage:
        msg = EmailMessage()
        msg["Subject"] = f"Customer wants a person ({request.channel}, {request.conversation_id[:8]})"
        msg["From"] = self.sender
        msg["To"] = ", ".join(self.recipients)
        msg.set_content(format_handoff(request, self.business_name))
        return msg

    def notify(self, request: HandoffRequest) -> None:
        msg = self.build_message(request)
        if self._smtp_factory is not None:
            smtp = self._smtp_factory(self.host, self.port)
        elif self.port == 465:
            smtp = smtplib.SMTP_SSL(self.host, self.port, timeout=15, context=ssl.create_default_context())
        else:
            smtp = smtplib.SMTP(self.host, self.port, timeout=15)
            smtp.starttls(context=ssl.create_default_context())
        with smtp:
            if self.username:
                smtp.login(self.username, self.password)
            smtp.send_message(msg)


class MultiNotifier:
    """Sends to every channel; succeeds if at least one delivered."""

    def __init__(self, notifiers: Sequence[HandoffNotifier]) -> None:
        if not notifiers:
            raise ValueError("At least one handoff channel is required")
        self.notifiers = list(notifiers)

    def notify(self, request: HandoffRequest) -> None:
        errors = []
        for notifier in self.notifiers:
            try:
                notifier.notify(request)
            except Exception as exc:
                log.exception("%s failed", type(notifier).__name__)
                errors.append(exc)
        if len(errors) == len(self.notifiers):
            raise RuntimeError(f"No handoff channel delivered ({len(errors)} failed)") from errors[0]
