"""Terminal chat: try the assistant without a browser, Telegram or an API key."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from ..core import Assistant, MemoryLog, MemoryNotifier, MockModel, Reply, load_business

DEMO_FOLDER = "demo/clinic"

HELP = """Type a question and press Enter. Commands:
  :human    pass the conversation to a person (the "Talk to a person" button)
  :log      show the conversation log (what would go to Google Sheets)
  :new      start a new conversation
  :quit     exit"""

DEMO_SCRIPT = [
    "What are your opening hours?",
    "How much is teeth whitening?",
    "Do you take BrightCare insurance?",
    "Is there parking?",
    "Do you sell gift cards?",
    "I have a toothache, should I take ibuprofen?",
    "My face is swollen and it hurts",
    "Can I talk to a person?",
]


def build(
    folder: str = DEMO_FOLDER, clock: Callable[[], datetime] | None = None
) -> tuple[Assistant, MemoryLog, MemoryNotifier]:
    business, knowledge = load_business(folder)
    conversation_log, notifier = MemoryLog(), MemoryNotifier()
    assistant = Assistant(business, knowledge, MockModel(), conversation_log, notifier, clock=clock)
    return assistant, conversation_log, notifier


def show(reply: Reply) -> None:
    print(f"\nAssistant [{reply.kind.value}]: {reply.text}")
    if reply.offer_handoff:
        print("  [ Talk to a person ]  (type :human)")


def print_log(conversation_log: MemoryLog) -> None:
    for e in conversation_log.entries:
        print(f"{e.timestamp:%H:%M:%S}  {e.kind.value:<10} {e.question[:50]!r}")
    unanswered = conversation_log.unanswered()
    print(f"Unanswered questions: {len(unanswered)}")
    for e in unanswered:
        print(f"  - {e.question}")


def run_console(folder: str = DEMO_FOLDER) -> None:
    assistant, conversation_log, _ = build(folder)
    conversation = 1
    print(HELP)
    show(assistant.greeting())
    while True:
        try:
            text = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if text == ":quit":
            return
        if text == ":log":
            print_log(conversation_log)
        elif text == ":new":
            conversation += 1
            show(assistant.greeting())
        elif text == ":human":
            show(assistant.request_handoff(f"console-{conversation}", reason="Customer pressed the button"))
        elif text:
            show(assistant.ask(f"console-{conversation}", text, channel="console"))


class _TypingClock:
    """The scripted demo "types" one message every 20 seconds, like a real customer."""

    def __init__(self) -> None:
        self.now = datetime.now(timezone.utc)

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=20)
        return self.now


def run_demo(folder: str = DEMO_FOLDER) -> MemoryLog:
    assistant, conversation_log, notifier = build(folder, clock=_TypingClock())
    show(assistant.greeting())
    for question in DEMO_SCRIPT:
        print(f"\nYou: {question}")
        show(assistant.ask("demo", question, channel="console"))
    print("\n--- Conversation log (goes to Google Sheets) ---")
    print_log(conversation_log)
    print(f"Handoffs sent to staff: {len(notifier.requests)}")
    return conversation_log
