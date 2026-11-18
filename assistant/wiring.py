"""Builds an Assistant from Settings: picks the model, the log and the handoff channels."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from html import escape
from pathlib import Path

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
    trials: dict = field(default_factory=dict)  # slug -> (Assistant, page html)

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
    if settings.model == "claude":
        if not settings.anthropic_api_key:
            raise SystemExit(
                "MODEL=claude needs ANTHROPIC_API_KEY (or ASSISTANT_ANTHROPIC_API_KEY) in .env or the environment "
                "(console.anthropic.com -> API keys)."
            )
        import anthropic

        from .adapters.claude import ClaudeModel  # imported only when used: the mock runs without the SDK

        # base_url is fixed: a host's own ANTHROPIC_BASE_URL (e.g. Claude Code's) must not redirect the bot.
        client = anthropic.Anthropic(
            api_key=settings.anthropic_api_key, base_url="https://api.anthropic.com", timeout=30.0, max_retries=2
        )
        return ClaudeModel(client, model=settings.claude_model, effort=settings.claude_effort)
    raise ValueError(f"Unknown MODEL {settings.model!r}. Available: mock, claude.")


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

    model = build_model(settings)
    assistant = Assistant(
        business,
        knowledge,
        model,
        conversation_log,
        notifier,
        limits=Limits(per_day=settings.daily_message_cap),
    )
    trials = build_trials(settings.trials_folder, model) if settings.trials_folder else {}
    return App(assistant, conversation_log, notifier, warnings, trials=trials)


# A trial is tried by the business itself and a few of its staff: a small daily cap protects the bill.
TRIAL_DAILY_CAP = 200
TRIAL_PAGE = Path(__file__).parent / "adapters" / "web" / "static" / "trial.html"


def build_trials(folder: str, model) -> dict:
    """One trial assistant per business folder in `folder`. Conversations stay in memory; nobody is notified."""
    trials = {}
    root = Path(folder)
    if not root.is_dir():
        log.warning("TRIALS_FOLDER %s does not exist", folder)
        return trials
    for path in sorted(p for p in root.iterdir() if (p / "business.json").is_file()):
        try:
            business, knowledge = load_business(path)
        except Exception as exc:  # one broken folder must not stop the others
            log.warning("Skipping trial %s: %s", path.name, exc)
            continue
        assistant = Assistant(
            business, knowledge, model, MemoryLog(), MemoryNotifier(), limits=Limits(per_day=TRIAL_DAILY_CAP)
        )
        trials[path.name] = (assistant, trial_page(path, business))
    return trials


def trial_page(folder: Path, business) -> str:
    raw = json.loads((folder / "business.json").read_text(encoding="utf-8"))
    examples = []
    questions = folder / "test_questions.json"
    if questions.is_file():
        examples = [q["question"] for q in json.loads(questions.read_text(encoding="utf-8")) if q["expect"] == "answer"]
    values = {
        "name": escape(business.name),
        "phone": escape(business.phone),
        "address": escape(business.address),
        "website": escape(raw.get("website", "")),
        "color": escape(raw.get("color", "#0f766e")),
        "api": escape(f"/t/{folder.name}"),
        "examples": "".join(f"<li>{escape(q)}</li>" for q in examples[:5]),
    }
    page = TRIAL_PAGE.read_text(encoding="utf-8")
    for key, value in values.items():
        page = page.replace("{{" + key + "}}", value)
    return page
