"""Command line.

python -m assistant demo            scripted conversation (no setup needed)
python -m assistant console         chat in the terminal
python -m assistant web             website chat window + demo page (reads .env)
python -m assistant setup-sheet     create the Conversations and Unanswered tabs
python -m assistant test-handoff    send a test "Customer wants a person" message to staff
"""

from __future__ import annotations

import argparse
import dataclasses
from datetime import datetime, timezone

from .adapters.console import run_console, run_demo
from .config import Settings


def main() -> None:
    parser = argparse.ArgumentParser(prog="assistant", description="AI chat assistant for a business.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text in [
        ("demo", "run a scripted conversation"),
        ("console", "chat in the terminal"),
        ("web", "serve the website chat window and the demo page"),
        ("setup-sheet", "create the Google Sheets tabs"),
        ("test-handoff", "send a test handoff message to staff"),
    ]:
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--business", help="folder with business.json and knowledge/ (default: BUSINESS_FOLDER)")
        if name == "web":
            p.add_argument("--host", default="127.0.0.1")
            p.add_argument("--port", type=int, default=8000)
            p.add_argument("--origins", help="comma-separated websites allowed to embed the widget")
    args = parser.parse_args()

    settings = Settings.from_env()
    if args.business:
        settings = dataclasses.replace(settings, business_folder=args.business)

    if args.command == "demo":
        run_demo(settings.business_folder)
    elif args.command == "console":
        run_console(settings.business_folder)
    elif args.command == "web":
        if args.origins is not None:
            settings = dataclasses.replace(
                settings, allowed_origins=[o.strip() for o in args.origins.split(",") if o.strip()]
            )
        run_web(settings, args.host, args.port)
    elif args.command == "setup-sheet":
        setup_sheet(settings)
    else:
        test_handoff(settings)


def run_web(settings: Settings, host: str, port: int) -> None:
    # Imported here so the console and the core tests run without web dependencies.
    import uvicorn

    from .adapters.web import create_app
    from .wiring import build_app

    app = build_app(settings)
    for warning in app.warnings:
        print(f"Note: {warning}")
    print(f"Model: {settings.model}. Demo page: http://{host}:{port}/")
    try:
        uvicorn.run(
            create_app(app.assistant, allowed_origins=settings.allowed_origins),
            host=host,
            port=port,
            log_level="warning",
        )
    finally:
        app.close()  # writes log rows that are still waiting


def setup_sheet(settings: Settings) -> None:
    from .adapters.sheets import ensure_tabs, open_spreadsheet

    if not settings.spreadsheet_id:
        raise SystemExit("SPREADSHEET_ID is empty in .env")
    spreadsheet = open_spreadsheet(settings.google_service_account_file, settings.spreadsheet_id)
    ensure_tabs(spreadsheet)
    print(f"OK: tabs ready in '{spreadsheet.title}': Conversations, Unanswered.")


def test_handoff(settings: Settings) -> None:
    from .core.models import HandoffRequest, Role, Turn
    from .wiring import build_app

    if not (settings.telegram_handoff or settings.email_handoff):
        raise SystemExit(
            "No handoff channel configured. Set HANDOFF_TELEGRAM_BOT_TOKEN + HANDOFF_TELEGRAM_CHAT_ID "
            "and/or SMTP_HOST + HANDOFF_EMAIL_FROM + HANDOFF_EMAIL_TO in .env."
        )
    app = build_app(settings)
    request = HandoffRequest(
        datetime.now(timezone.utc),
        "test-handoff",
        "test",
        "Test message from `python -m assistant test-handoff`",
        (Turn(Role.CUSTOMER, "Do you sell gift cards?"), Turn(Role.ASSISTANT, "I don't have that information...")),
    )
    try:
        app.notifier.notify(request)
    finally:
        app.close()
    print("OK: test handoff sent. Check the staff Telegram chat and/or inbox.")


if __name__ == "__main__":
    main()
