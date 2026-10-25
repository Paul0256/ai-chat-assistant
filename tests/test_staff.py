"""After a handoff the team takes over: forwarding, staff replies, polling, Telegram."""

from __future__ import annotations

import threading

from fastapi.testclient import TestClient

from assistant.adapters.notify import TelegramNotifier
from assistant.adapters.staff_telegram import TelegramStaffListener
from assistant.adapters.web import create_app
from assistant.core import AnswerKind, ModelAnswer, ReplyKind


def handed_off(assistant, cid="conversation-1"):
    assistant.ask(cid, "Do you sell gift cards?")
    assert assistant.request_handoff(cid, reason="button").kind is ReplyKind.HANDOFF
    return cid


def test_after_handoff_messages_go_to_staff_not_the_model(make_assistant, notifier):
    class CountingModel:
        name = "counting"
        calls = 0

        def answer(self, request):
            CountingModel.calls += 1
            return ModelAnswer(AnswerKind.NOT_FOUND)

    bot = make_assistant(model=CountingModel())
    cid = handed_off(bot)
    reply = bot.ask(cid, "It's for my mum, 50 dollars")
    assert reply.kind is ReplyKind.HANDOFF and "team" in reply.text
    assert CountingModel.calls == 1  # only the question before the handoff
    assert notifier.requests[-1].reason == "The customer wrote again"
    assert notifier.requests[-1].transcript[-1].text == "It's for my mum, 50 dollars"


def test_emergency_still_wins_after_handoff(assistant):
    cid = handed_off(assistant)
    assert assistant.ask(cid, "my face is swollen").kind is ReplyKind.EMERGENCY


def test_failed_forwarding_gives_contact_details(assistant, notifier, monkeypatch):
    cid = handed_off(assistant)

    def boom(request):
        raise RuntimeError("telegram down")

    monkeypatch.setattr(notifier, "notify", boom)
    reply = assistant.ask(cid, "hello?")
    assert reply.kind is ReplyKind.ERROR and "+1 555 0100" in reply.text


def test_staff_reply_is_queued_for_the_customer_and_logged(assistant, conversation_log):
    cid = handed_off(assistant)
    assert assistant.staff_reply(cid, "Yes, gift cards from $50 at the front desk.")
    assert assistant.staff_reply(cid, "We're open until 18:00 today.")
    messages = assistant.messages_since(cid)
    assert [(m.seq, m.text) for m in messages] == [
        (1, "Yes, gift cards from $50 at the front desk."),
        (2, "We're open until 18:00 today."),
    ]
    assert [m.seq for m in assistant.messages_since(cid, after=1)] == [2]
    assert conversation_log.entries[-1].kind is ReplyKind.STAFF


def test_staff_reply_to_unknown_or_empty(assistant):
    assert not assistant.staff_reply("nobody-here", "hi")
    cid = handed_off(assistant)
    assert not assistant.staff_reply(cid, "   ")
    assert assistant.messages_since("nobody-here") == []


def test_handed_off_conversations_wait_longer_for_staff(assistant, clock):
    cid = handed_off(assistant)
    assistant.ask("other-conv", "hours?")
    clock.advance(hours=3)
    assert assistant.staff_reply(cid, "Sorry for the wait!")  # still there
    assert assistant.messages_since("other-conv") == [] and "other-conv" not in assistant._conversations
    clock.advance(hours=25)
    assert not assistant.staff_reply(cid, "Hello?")


def test_slow_model_does_not_block_other_visitors(make_assistant):
    started, release = threading.Event(), threading.Event()

    class SlowModel:
        name = "slow"

        def answer(self, request):
            if request.question == "slow":
                started.set()
                release.wait(5)
            return ModelAnswer(AnswerKind.ANSWER, "ok")

    bot = make_assistant(model=SlowModel())
    worker = threading.Thread(target=bot.ask, args=("a-conversation", "slow"))
    worker.start()
    assert started.wait(5)
    assert bot.ask("b-conversation", "fast").text == "ok"  # not stuck behind "slow"
    release.set()
    worker.join(5)


def test_web_polling_returns_staff_replies(assistant):
    client = TestClient(create_app(assistant))
    cid = "web-conversation-1"
    client.post("/api/chat", json={"conversation_id": cid, "message": "Do you sell gift cards?"})
    client.post("/api/handoff", json={"conversation_id": cid})
    assert client.get("/api/messages", params={"conversation_id": cid}).json() == {"messages": []}
    assistant.staff_reply(cid, "Yes we do!")
    data = client.get("/api/messages", params={"conversation_id": cid, "after": 0}).json()
    assert data == {"messages": [{"seq": 1, "text": "Yes we do!"}]}
    assert client.get("/api/messages", params={"conversation_id": cid, "after": 1}).json() == {"messages": []}
    assert client.get("/api/messages", params={"conversation_id": "bad id"}).status_code == 400


# --------------------------------------------------------------------------- Telegram


class FakeTelegram:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.updates: list[dict] = []
        self.next_id = 100

    def __call__(self, url, payload):
        if url.endswith("/sendMessage"):
            self.next_id += 1
            self.sent.append(payload)
            return {"ok": True, "result": {"message_id": self.next_id}}
        if url.endswith("/getUpdates"):
            fresh = [u for u in self.updates if u["update_id"] >= payload["offset"]]
            return {"ok": True, "result": fresh}
        raise AssertionError(url)


def staff_message(update_id, text, reply_to, chat_id=-1001):
    return {
        "update_id": update_id,
        "message": {
            "message_id": 500 + update_id,
            "chat": {"id": chat_id},
            "text": text,
            "reply_to_message": {"message_id": reply_to},
        },
    }


def telegram_setup(make_assistant):
    fake = FakeTelegram()
    notifier = TelegramNotifier("t", "-1001", "Clinic", post=fake)
    bot = make_assistant()
    bot.notifier = notifier
    return fake, notifier, bot, TelegramStaffListener(notifier, bot, post=fake)


def test_staff_reply_in_telegram_reaches_the_customer(make_assistant):
    fake, notifier, bot, listener = telegram_setup(make_assistant)
    cid = handed_off(bot)
    notification_id = fake.next_id
    assert notifier.conversation_for(notification_id) == cid
    assert "Reply to this message" in fake.sent[-1]["text"]
    fake.updates.append(staff_message(1, "Yes, from $50.", reply_to=notification_id))
    assert listener.poll_once() == 1
    assert [m.text for m in bot.messages_since(cid)] == ["Yes, from $50."]
    assert fake.sent[-1]["text"] == "Sent to the customer."
    assert listener.offset == 2 and listener.poll_once() == 0  # not delivered twice


def test_messages_from_other_chats_or_not_replies_are_ignored(make_assistant):
    fake, notifier, bot, listener = telegram_setup(make_assistant)
    cid = handed_off(bot)
    fake.updates += [
        staff_message(1, "hijack", reply_to=fake.next_id, chat_id=-999),  # another chat
        staff_message(2, "random chatter", reply_to=12345),  # not a notification
    ]
    assert listener.poll_once() == 0 and bot.messages_since(cid) == []


def test_reply_after_the_customer_left_is_reported_to_staff(make_assistant, clock):
    fake, notifier, bot, listener = telegram_setup(make_assistant)
    handed_off(bot)
    notification_id = fake.next_id
    clock.advance(days=2)
    fake.updates.append(staff_message(1, "Hello?", reply_to=notification_id))
    assert listener.poll_once() == 0
    assert fake.sent[-1]["text"].startswith("Not delivered")
