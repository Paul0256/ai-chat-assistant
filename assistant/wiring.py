"""Builds an Assistant from Settings: picks the model, the log and the handoff channels."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .adapters.notify import EmailNotifier, MultiNotifier, TelegramNotifier
from .config import Settings
from .core import Assistant, Limits, MemoryLog, MemoryNotifier, MockModel, load_business
from .core.storage import ConversationLog, HandoffNotifier

log = logging.getLogger(__name__)


@dataclass
class App:
    assistant: Assistant
    conversation_log: ConversationLog
    notifier: HandoffNotifier
    warnings: list[str]
    background: list = field(default_factory=list)  # threads to stop on shutdown

    def start_staff_replies(self) -> None:
        """Let staff answer from Telegram (only when Telegram handoff is configured)."""
        from .adapters.staff_telegram import TelegramStaffListener

        channels = self.notifier.notifiers if isinstance(self.notifier, MultiNotifier) else [self.notifier]
        for channel in channels:
            if isinstance(channel, TelegramNotifier):
                self.background.append(TelegramStaffListener(channel, self.assistant).start())

    def close(self) -> None:
        for worker in self.background:
            worker.close()
        close = getattr(self.conversation_log, "close", None)
        if close is not None:
            close()


def build_model(settings: Settings):
    if settings.model == "mock":
        return MockModel()
    raise ValueError(f"Unknown MODEL {settings.model!r}. Available now: mock.")


def build_app(settings: Settings) -> App:
    business, knowledge = load_business(settings.business_folder)
    warnings: list[str] = []

    conversation_log: ConversationLog
    if settings.spreadsheet_id:
        from .adapters.sheets import SheetsLog

        conversation_log = SheetsLog.connect(settings.google_service_account_file, settings.spreadsheet_id).start()
    else:
        conversation_log = MemoryLog()
        warnings.append("SPREADSHEET_ID is empty: conversations are kept in memory only.")

    channels: list[HandoffNotifier] = []
    if settings.telegram_handoff:
        channels.append(
            TelegramNotifier(settings.handoff_telegram_bot_token, settings.handoff_telegram_chat_id, business.name)
        )
    if settings.email_handoff:
        channels.append(
            EmailNotifier(
                settings.smtp_host,
                settings.smtp_port,
                settings.smtp_username,
                settings.smtp_password,
                settings.handoff_email_from,
                settings.handoff_email_to,
                business.name,
            )
        )
    notifier: HandoffNotifier
    if channels:
        notifier = MultiNotifier(channels)
    else:
        notifier = MemoryNotifier()
        warnings.append("No handoff channel configured: 'Talk to a person' requests reach nobody (demo mode).")

    assistant = Assistant(
        business,
        knowledge,
        build_model(settings),
        conversation_log,
        notifier,
        limits=Limits(per_day=settings.daily_message_cap),
    )
    return App(assistant, conversation_log, notifier, warnings)
