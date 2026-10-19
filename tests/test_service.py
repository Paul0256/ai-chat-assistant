from __future__ import annotations

from dataclasses import replace

from assistant.core import AnswerKind, Limits, ModelAnswer, ReplyKind, Role
from assistant.core.llm.base import AnswerRequest


class RecordingModel:
    name = "recording"

    def __init__(self, answer: ModelAnswer | None = None) -> None:
        self.requests: list[AnswerRequest] = []
        self._answer = answer or ModelAnswer(AnswerKind.ANSWER, "Sure.")

    def answer(self, request: AnswerRequest) -> ModelAnswer:
        self.requests.append(request)
        return self._answer


class BrokenModel:
    name = "broken"

    def answer(self, request):
        raise RuntimeError("provider down")


def test_answer_is_logged(assistant, conversation_log):
    reply = assistant.ask("c1", "What are your opening hours?")
    assert reply.kind is ReplyKind.ANSWER and not reply.offer_handoff
    [entry] = conversation_log.entries
    assert entry.conversation_id == "c1" and entry.kind is ReplyKind.ANSWER
    assert entry.question == "What are your opening hours?"


def test_unknown_question_offers_a_person_and_lands_in_unanswered(assistant, conversation_log):
    reply = assistant.ask("c1", "Do you sell gift cards?")
    assert reply.kind is ReplyKind.NOT_FOUND and reply.offer_handoff
    assert "+1 555 0100" in reply.text
    assert [e.question for e in conversation_log.unanswered()] == ["Do you sell gift cards?"]


def test_medical_question_is_declined(assistant):
    reply = assistant.ask("c1", "Should I take ibuprofen for a toothache?")
    assert reply.kind is ReplyKind.MEDICAL and reply.offer_handoff and "medical advice" in reply.text


def test_emergency_skips_the_model(make_assistant):
    model = RecordingModel()
    reply = make_assistant(model=model).ask("c1", "My face is swollen and I can't swallow")
    assert reply.kind is ReplyKind.EMERGENCY and "911" in reply.text
    assert model.requests == []


def test_non_medical_business_has_no_emergency_or_medical_rules(make_assistant, clinic):
    business, _ = clinic
    model = RecordingModel()
    shop = make_assistant(model=model, business=replace(business, medical=False))
    assert shop.ask("c1", "This is an emergency, my order is late").kind is ReplyKind.ANSWER
    assert len(model.requests) == 1


def test_typed_request_for_a_person_notifies_staff_with_the_transcript(assistant, notifier, conversation_log):
    assistant.ask("c1", "Do you sell gift cards?")
    reply = assistant.ask("c1", "Can I talk to a person?")
    assert reply.kind is ReplyKind.HANDOFF
    [request] = notifier.requests
    assert [t.text for t in request.transcript if t.role is Role.CUSTOMER] == [
        "Do you sell gift cards?",
        "Can I talk to a person?",
    ]
    assert conversation_log.entries[-1].question == "Can I talk to a person?"


def test_handoff_button(assistant, notifier):
    assistant.ask("c1", "Do you sell gift cards?")
    reply = assistant.request_handoff("c1", reason="Customer pressed the button")
    assert reply.kind is ReplyKind.HANDOFF and notifier.requests[0].reason == "Customer pressed the button"


def test_failed_notification_still_gives_contact_details(assistant, notifier, monkeypatch):
    def boom(request):
        raise RuntimeError("smtp down")

    monkeypatch.setattr(notifier, "notify", boom)
    reply = assistant.request_handoff("c1", reason="button")
    assert reply.kind is ReplyKind.ERROR and "+1 555 0100" in reply.text


def test_model_failure_is_polite_and_logged(make_assistant, conversation_log):
    reply = make_assistant(model=BrokenModel()).ask("c1", "What are your opening hours?")
    assert reply.kind is ReplyKind.ERROR and reply.offer_handoff and "+1 555 0100" in reply.text
    assert conversation_log.entries[0].kind is ReplyKind.ERROR


def test_history_is_sent_to_the_model_and_capped(make_assistant):
    model = RecordingModel()
    bot = make_assistant(model=model, limits=Limits(history_turns=4, per_minute=100))
    for i in range(5):
        bot.ask("c1", f"question {i}")
    last = model.requests[-1]
    assert last.question == "question 4"
    assert [t.text for t in last.history] == ["question 2", "Sure.", "question 3", "Sure."]


def test_conversations_are_separate(make_assistant):
    model = RecordingModel()
    bot = make_assistant(model=model)
    bot.ask("a", "hello from a")
    bot.ask("b", "hello from b")
    assert model.requests[-1].history == ()


def test_idle_conversation_is_forgotten(make_assistant, clock):
    model = RecordingModel()
    bot = make_assistant(model=model)
    bot.ask("c1", "first")
    clock.advance(hours=3)
    bot.ask("c1", "second")
    assert model.requests[-1].history == ()


def test_long_message_is_refused_without_calling_the_model(make_assistant, conversation_log):
    model = RecordingModel()
    reply = make_assistant(model=model, limits=Limits(max_chars=20)).ask("c1", "x" * 21)
    assert reply.kind is ReplyKind.LIMITED and "20 characters" in reply.text
    assert model.requests == [] and conversation_log.entries == []


def test_empty_message(assistant):
    assert assistant.ask("c1", "   ").kind is ReplyKind.LIMITED


def test_messages_per_minute(make_assistant, clock):
    bot = make_assistant(limits=Limits(per_minute=2))
    assert bot.ask("c1", "hours?").kind is not ReplyKind.LIMITED
    assert bot.ask("c1", "parking?").kind is not ReplyKind.LIMITED
    assert bot.ask("c1", "whitening?").kind is ReplyKind.LIMITED
    assert bot.ask("c2", "whitening?").kind is not ReplyKind.LIMITED  # other visitors are not affected
    clock.advance(seconds=61)
    assert bot.ask("c1", "whitening?").kind is not ReplyKind.LIMITED


def test_daily_cap_protects_the_bill_and_resets_next_day(make_assistant, clock):
    model = RecordingModel()
    bot = make_assistant(model=model, limits=Limits(per_day=2))
    bot.ask("a", "one")
    bot.ask("b", "two")
    capped = bot.ask("c", "three")
    assert capped.kind is ReplyKind.LIMITED and "+1 555 0100" in capped.text
    assert len(model.requests) == 2
    clock.advance(days=1)
    assert bot.ask("c", "three").kind is ReplyKind.ANSWER


def test_model_text_wins_over_standard_wording(make_assistant):
    model = RecordingModel(ModelAnswer(AnswerKind.NOT_FOUND, "No lo sé, ¿le paso con el equipo?"))
    reply = make_assistant(model=model).ask("c1", "¿Venden tarjetas regalo?")
    assert reply.kind is ReplyKind.NOT_FOUND and reply.text.startswith("No lo sé")


def test_empty_answer_text_counts_as_not_found(make_assistant):
    reply = make_assistant(model=RecordingModel(ModelAnswer(AnswerKind.ANSWER, ""))).ask("c1", "hours?")
    assert reply.kind is ReplyKind.NOT_FOUND


def test_logging_failure_does_not_hide_the_answer(assistant, conversation_log, monkeypatch):
    def boom(entry):
        raise RuntimeError("sheets down")

    monkeypatch.setattr(conversation_log, "append", boom)
    assert assistant.ask("c1", "What are your opening hours?").kind is ReplyKind.ANSWER


def test_greeting(assistant):
    assert "Riverside Dental Studio" in assistant.greeting().text
