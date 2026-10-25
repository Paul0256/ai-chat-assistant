"""Staff answer customers from Telegram: reply to the bot's notification, the customer sees it in the chat window.

Long polling (getUpdates), so no public webhook URL is needed. Only messages
from the configured staff chat that reply to one of the bot's notifications
are used; everything else is ignored.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from ..core import Assistant
from .notify import TelegramNotifier, _post_json

log = logging.getLogger(__name__)


class TelegramStaffListener:
    def __init__(
        self,
        notifier: TelegramNotifier,
        assistant: Assistant,
        post: Callable[[str, dict], dict] | None = None,
        poll_timeout: int = 30,
    ) -> None:
        self.notifier = notifier
        self.assistant = assistant
        self._post = post or (lambda url, payload: _post_json(url, payload, timeout=poll_timeout + 10))
        self.poll_timeout = poll_timeout
        self.offset = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> TelegramStaffListener:
        self._thread = threading.Thread(target=self._run, name="telegram-staff", daemon=True)
        self._thread.start()
        return self

    def close(self) -> None:
        self._stop.set()

    def poll_once(self) -> int:
        """Fetch and handle one batch of updates. Returns how many staff replies were delivered."""
        result = self._post(
            f"{self.notifier.api}/getUpdates",
            {"offset": self.offset, "timeout": self.poll_timeout, "allowed_updates": ["message"]},
        )
        if not result.get("ok"):
            raise RuntimeError(result.get("description", "getUpdates failed"))
        delivered = 0
        for update in result.get("result", []):
            self.offset = max(self.offset, int(update["update_id"]) + 1)
            delivered += self.handle(update.get("message") or {})
        return delivered

    def handle(self, message: dict) -> int:
        if str((message.get("chat") or {}).get("id")) != self.notifier.chat_id:
            return 0  # not the staff chat
        original = message.get("reply_to_message") or {}
        text = (message.get("text") or "").strip()
        conversation_id = self.notifier.conversation_for(int(original.get("message_id", -1)))
        if conversation_id is None or not text:
            return 0
        if self.assistant.staff_reply(conversation_id, text):
            self._confirm("Sent to the customer.", message)
            return 1
        self._confirm("Not delivered: the customer's conversation has ended. Please contact them directly.", message)
        return 0

    def _confirm(self, text: str, message: dict) -> None:
        try:
            self.notifier.send(text, reply_to=message.get("message_id"))
        except Exception:
            log.warning("could not confirm the staff reply in Telegram", exc_info=True)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception:
                log.exception("Telegram staff polling failed; retrying in 10s")
                self._stop.wait(10)
