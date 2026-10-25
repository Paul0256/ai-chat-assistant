from __future__ import annotations

import pytest

from assistant.adapters.notify import MultiNotifier
from assistant.config import Settings
from assistant.core import MemoryLog, MemoryNotifier
from assistant.wiring import build_app

from .conftest import DEMO


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    for key in [
        "BUSINESS_FOLDER", "MODEL", "ALLOWED_ORIGINS", "DAILY_MESSAGE_CAP", "SPREADSHEET_ID",
        "HANDOFF_TELEGRAM_BOT_TOKEN", "HANDOFF_TELEGRAM_CHAT_ID", "SMTP_HOST", "HANDOFF_EMAIL_FROM", "HANDOFF_EMAIL_TO",
    ]:  # fmt: skip
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)  # no stray .env


def test_settings_from_env(clean_env, monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://a.example, https://b.example")
    monkeypatch.setenv("HANDOFF_EMAIL_TO", "x@a.example,y@a.example")
    monkeypatch.setenv("DAILY_MESSAGE_CAP", "50")
    s = Settings.from_env()
    assert s.allowed_origins == ["https://a.example", "https://b.example"]
    assert s.handoff_email_to == ["x@a.example", "y@a.example"]
    assert s.daily_message_cap == 50 and s.model == "mock"
    assert not s.telegram_handoff and not s.email_handoff


def test_demo_mode_works_without_any_setup_and_says_so():
    app = build_app(Settings(business_folder=str(DEMO)))
    assert isinstance(app.conversation_log, MemoryLog) and isinstance(app.notifier, MemoryNotifier)
    assert len(app.warnings) == 2
    assert app.assistant.ask("c1", "What are your opening hours?").text.startswith("Monday")


def test_configured_channels_are_used():
    settings = Settings(
        business_folder=str(DEMO),
        handoff_telegram_bot_token="t",
        handoff_telegram_chat_id="c",
        smtp_host="smtp.example",
        handoff_email_from="demo@pulauskas.dev",
        handoff_email_to=["staff@clinic.example"],
    )
    app = build_app(settings)
    assert isinstance(app.notifier, MultiNotifier) and len(app.notifier.notifiers) == 2
    assert not any("handoff" in w for w in app.warnings)


def test_daily_cap_comes_from_settings():
    app = build_app(Settings(business_folder=str(DEMO), daily_message_cap=7))
    assert app.assistant.limits.per_day == 7


def test_unknown_model_is_a_clear_error():
    with pytest.raises(ValueError, match="Unknown MODEL"):
        build_app(Settings(business_folder=str(DEMO), model="gpt-9"))
