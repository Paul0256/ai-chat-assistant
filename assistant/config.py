"""Settings from environment variables (.env). See .env.example."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv


def _list(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


@dataclass(frozen=True)
class Settings:
    business_folder: str = "demo/clinic"
    model: str = "mock"
    allowed_origins: list[str] = field(default_factory=list)
    daily_message_cap: int = 500
    # Google Sheets log (optional)
    spreadsheet_id: str = ""
    google_service_account_file: str = "service_account.json"
    # Handoff to staff: Telegram and/or email (optional in demo mode)
    handoff_telegram_bot_token: str = ""
    handoff_telegram_chat_id: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    handoff_email_from: str = ""
    handoff_email_to: list[str] = field(default_factory=list)

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv()
        env = os.environ.get
        return cls(
            business_folder=env("BUSINESS_FOLDER", "demo/clinic"),
            model=env("MODEL", "mock").strip().lower(),
            allowed_origins=_list(env("ALLOWED_ORIGINS", "")),
            daily_message_cap=int(env("DAILY_MESSAGE_CAP", "500")),
            spreadsheet_id=env("SPREADSHEET_ID", "").strip(),
            google_service_account_file=env("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json"),
            handoff_telegram_bot_token=env("HANDOFF_TELEGRAM_BOT_TOKEN", "").strip(),
            handoff_telegram_chat_id=env("HANDOFF_TELEGRAM_CHAT_ID", "").strip(),
            smtp_host=env("SMTP_HOST", "").strip(),
            smtp_port=int(env("SMTP_PORT", "587")),
            smtp_username=env("SMTP_USERNAME", "").strip(),
            smtp_password=env("SMTP_PASSWORD", ""),
            handoff_email_from=env("HANDOFF_EMAIL_FROM", "").strip(),
            handoff_email_to=_list(env("HANDOFF_EMAIL_TO", "")),
        )

    @property
    def telegram_handoff(self) -> bool:
        return bool(self.handoff_telegram_bot_token and self.handoff_telegram_chat_id)

    @property
    def email_handoff(self) -> bool:
        return bool(self.smtp_host and self.handoff_email_from and self.handoff_email_to)
