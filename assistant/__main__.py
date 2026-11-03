"""Command line.

python -m assistant demo            scripted conversation (no setup needed)
python -m assistant console         chat in the terminal
python -m assistant web             website chat window + demo page (reads .env)
python -m assistant setup-sheet     create the Conversations and Unanswered tabs
python -m assistant test-handoff    send a test "Customer wants a person" message to staff
python -m assistant eval            run the business's test questions through the model (reads .env)
python -m assistant check-claude    check the Anthropic API key with one tiny request
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
        ("eval", "run the test questions through the model and check the replies"),
        ("check-claude", "check the Anthropic API key with one tiny request"),
    ]:
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--business", help="folder with business.json and knowledge/ (default: BUSINESS_FOLDER)")
        if name == "web":
            p.add_argument("--host", default="127.0.0.1")
            p.add_argument("--port", type=int, default=8000)
            p.add_argument("--origins", help="comma-separated websites allowed to embed the widget")
        if name == "eval":
            p.add_argument("--questions", help="JSON test questions (default: <business>/test_questions.json)")
            p.add_argument("--csv", default="eval-results.csv", help="where to write the details")
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
    elif args.command == "eval":
        evaluate(settings, args.questions, args.csv)
    elif args.command == "check-claude":
        check_claude(settings)
    else:
        test_handoff(settings)


def run_web(settings: Settings, host: str, port: int) -> None:
    # Imported here so the console and the core tests run without web dependencies.
    import uvicorn

    from .adapters.web import create_app
    from .wiring import build_app

    app = build_app(settings)
    app.start_staff_replies()
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


def evaluate(settings: Settings, questions: str | None, csv_path: str) -> None:
    from pathlib import Path

    from .evaluate import report, run
    from .wiring import build_model

    model = build_model(settings)
    print(f"Model: {model.name}. Running the test questions...")
    results = run(settings.business_folder, model, Path(questions) if questions else None)
    print(report(results, Path(csv_path)))
    usage = getattr(model, "usage", None)
    if usage is not None and usage.requests:
        print(
            f"Cost: ~${usage.cost_usd:.3f} for {usage.requests} model calls "
            f"(~${usage.cost_usd / usage.requests:.4f} per answer; cache read {usage.cache_read:,} tokens)"
        )


def check_claude(settings: Settings) -> None:
    """Says what is wrong with the key without ever printing it."""
    import os

    import anthropic

    key = settings.anthropic_api_key
    source = next((n for n in ("ANTHROPIC_API_KEY", "ASSISTANT_ANTHROPIC_API_KEY") if os.environ.get(n)), None)
    if not key:
        raise SystemExit("No key: set ANTHROPIC_API_KEY or ASSISTANT_ANTHROPIC_API_KEY in .env or the environment.")
    # The type part (e.g. "sk-ant-api03") is not secret; the rest is.
    parts = key.split("-")
    kind = "-".join(parts[:3]) if len(parts) > 3 and parts[0] == "sk" else "(not an sk-... key)"
    print(f"Key from {source}: {len(key)} characters, type {kind}")
    if "=" in key:
        print("Warning: the value contains '='. Put only the key after the variable name, not NAME=key again.")
    if not key.startswith("sk-") and "sk-ant-" in key:
        print(f"Warning: 'sk-ant-' starts at character {key.index('sk-ant-') + 1}; something is pasted before the key.")
    if any(c in key for c in "\"' \t"):
        print("Warning: the key contains quotes or spaces; paste it without them.")
    for name in ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"):
        if os.environ.get(name):
            print(f"Note: {name} is set in the environment; the assistant ignores it.")

    def ask(**auth):
        client = anthropic.Anthropic(**auth, base_url="https://api.anthropic.com", timeout=30.0, max_retries=0)
        return client.messages.create(
            model=settings.claude_model,
            max_tokens=200,
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": "Reply with the single word: ok"}],
        )

    try:
        try:
            reply = ask(api_key=key)
        except anthropic.AuthenticationError as exc:
            print(f"x-api-key header: rejected ({exc.message}). Trying Authorization: Bearer...")
            reply = ask(api_key=None, auth_token=key)
            print("Bearer works: this key type must be sent as a bearer token.")
    except anthropic.AuthenticationError as exc:
        raise SystemExit(
            f"The API rejected the key both ways: {exc.message}. Create a new key and paste it whole."
        ) from None
    except anthropic.PermissionDeniedError as exc:
        raise SystemExit(f"The key has no access: {exc.message}") from None
    except anthropic.NotFoundError as exc:
        raise SystemExit(f"Model {settings.claude_model!r} not found: {exc.message}") from None
    except anthropic.APIConnectionError as exc:
        raise SystemExit(f"Could not reach api.anthropic.com: {exc}") from None
    text = next((b.text for b in reply.content if b.type == "text"), "")
    print(
        f"OK: {settings.claude_model} replied {text.strip()!r} ({reply.usage.input_tokens} in, "
        f"{reply.usage.output_tokens} out tokens)."
    )


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
