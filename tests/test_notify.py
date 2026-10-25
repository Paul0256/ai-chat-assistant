from __future__ import annotations

from datetime import datetime, timezone

import pytest

from assistant.adapters.notify import EmailNotifier, MultiNotifier, TelegramNotifier, format_handoff
from assistant.core import HandoffRequest, Role, Turn


def request(turns=None) -> HandoffRequest:
    return HandoffRequest(
        datetime(2026, 10, 25, 9, 30, tzinfo=timezone.utc),
        "abcdef123456",
        "web",
        "Customer pressed the button",
        tuple(turns or [Turn(Role.CUSTOMER, "Do you sell gift cards?"), Turn(Role.ASSISTANT, "I don't know.")]),
    )


def test_format_has_context_and_transcript():
    text = format_handoff(request(), "Riverside Dental Studio")
    assert "Riverside Dental Studio" in text and "Conversation: abcdef123456" in text
    assert "Customer: Do you sell gift cards?" in text and "Assistant: I don't know." in text


def test_format_keeps_only_the_last_turns():
    turns = [Turn(Role.CUSTOMER, f"q{i}") for i in range(20)]
    text = format_handoff(request(turns), "Clinic", max_turns=3)
    assert "(last 3 messages)" in text and "q19" in text and "q16" not in text


class FakePost:
    def __init__(self, result=None) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.result = result if result is not None else {"ok": True}

    def __call__(self, url, payload):
        self.calls.append((url, payload))
        return self.result


def test_telegram_sends_plain_text_to_the_staff_chat():
    post = FakePost()
    TelegramNotifier("123:ABC", "-1001", "Clinic", post=post).notify(request())
    url, payload = post.calls[0]
    assert url == "https://api.telegram.org/bot123:ABC/sendMessage"
    assert payload["chat_id"] == "-1001" and "parse_mode" not in payload
    assert "Do you sell gift cards?" in payload["text"]


def test_telegram_long_messages_are_shortened():
    post = FakePost()
    turns = [Turn(Role.CUSTOMER, "x" * 900) for _ in range(10)]
    TelegramNotifier("t", "c", "Clinic", post=post).notify(request(turns))
    text = post.calls[0][1]["text"]
    assert len(text) <= 4096 and text.endswith("(shortened)")


def test_telegram_refusal_raises():
    with pytest.raises(RuntimeError, match="chat not found"):
        TelegramNotifier("t", "c", "Clinic", post=FakePost({"ok": False, "description": "chat not found"})).notify(
            request()
        )


class FakeSMTP:
    instances: list[FakeSMTP] = []

    def __init__(self, host, port) -> None:
        self.host, self.port = host, port
        self.logged_in = None
        self.sent = []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, user, password):
        self.logged_in = (user, password)

    def send_message(self, msg):
        self.sent.append(msg)


def test_email_is_sent_to_every_recipient():
    FakeSMTP.instances.clear()
    notifier = EmailNotifier(
        "smtp.example", 587, "user", "pw", "demo@pulauskas.dev", ["a@clinic.example", "b@clinic.example"], "Clinic",
        smtp_factory=FakeSMTP,
    )  # fmt: skip
    notifier.notify(request())
    smtp = FakeSMTP.instances[0]
    msg = smtp.sent[0]
    assert smtp.logged_in == ("user", "pw")
    assert msg["To"] == "a@clinic.example, b@clinic.example" and "abcdef12" in msg["Subject"]
    assert "Do you sell gift cards?" in msg.get_content()


class Failing:
    def notify(self, request):
        raise RuntimeError("down")


class Recording:
    def __init__(self) -> None:
        self.requests = []

    def notify(self, request):
        self.requests.append(request)


def test_multi_succeeds_if_any_channel_delivers():
    ok = Recording()
    MultiNotifier([Failing(), ok]).notify(request())
    assert len(ok.requests) == 1


def test_multi_raises_when_every_channel_fails():
    with pytest.raises(RuntimeError, match="No handoff channel delivered"):
        MultiNotifier([Failing(), Failing()]).notify(request())


def test_multi_needs_at_least_one_channel():
    with pytest.raises(ValueError):
        MultiNotifier([])
