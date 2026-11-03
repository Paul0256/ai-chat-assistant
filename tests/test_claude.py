"""The Claude adapter, with a fake client: no network, no key, no cost."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from assistant.adapters.claude import ClaudeModel, output_schema, system_prompt, to_messages
from assistant.core import AnswerKind, AnswerRequest, ReplyKind, Role, Turn
from assistant.core.llm.base import ModelAnswer


def response(kind="answer", text="Open 8 to 18.", stop_reason="end_turn", content=None, cache_read=0):
    if content is None:
        content = [SimpleNamespace(type="text", text=json.dumps({"kind": kind, "text": text}))]
    usage = SimpleNamespace(
        input_tokens=50, output_tokens=20, cache_creation_input_tokens=1000, cache_read_input_tokens=cache_read
    )
    return SimpleNamespace(content=content, stop_reason=stop_reason, stop_details=None, usage=usage)


class FakeClient:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls: list[dict] = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


@pytest.fixture
def request_for(clinic):
    business, knowledge = clinic

    def make(question="What are your opening hours?", history=()):
        return AnswerRequest(business, knowledge, tuple(history), question)

    return make


def test_answer_is_parsed_from_the_json_reply(request_for):
    client = FakeClient(response("answer", "  Monday to Thursday 8:00 to 18:00. "))
    result = ClaudeModel(client).answer(request_for())
    assert result == ModelAnswer(AnswerKind.ANSWER, "Monday to Thursday 8:00 to 18:00.")


def test_request_shape(request_for):
    client = FakeClient(response())
    ClaudeModel(client, effort="low").answer(request_for())
    call = client.calls[0]
    assert call["model"] == "claude-sonnet-5-5"
    assert call["fallbacks"] == "default" and call["betas"] == ["server-side-fallback-2026-07-01"]
    assert call["output_config"]["effort"] == "low"
    assert call["output_config"]["format"]["schema"] == output_schema(True)
    assert "temperature" not in call and "thinking" not in call
    (system,) = call["system"]
    assert system["cache_control"] == {"type": "ephemeral"}
    assert "Riverside Dental Studio" in system["text"] and "$390" in system["text"]  # rules + documents
    assert call["messages"] == [{"role": "user", "content": "What are your opening hours?"}]


def test_system_prompt_is_identical_across_requests_so_it_stays_cached(request_for):
    client = FakeClient(response(), response())
    model = ClaudeModel(client)
    model.answer(request_for("Hours?"))
    model.answer(request_for("Parking?"))
    assert client.calls[0]["system"] == client.calls[1]["system"]


def test_medical_rules_only_for_healthcare(clinic):
    business, knowledge = clinic
    shop = business.__class__(**{**business.__dict__, "medical": False})
    assert "medical advice" in system_prompt(business, knowledge)
    assert "medical advice" not in system_prompt(shop, knowledge)
    assert output_schema(False)["properties"]["kind"]["enum"] == ["answer", "not_found"]


def test_history_is_sent_as_alternating_turns(request_for):
    history = [
        Turn(Role.ASSISTANT, "older reply whose question fell out of the window"),
        Turn(Role.CUSTOMER, "Do you have parking?"),
        Turn(Role.ASSISTANT, "Yes, behind the building."),
        Turn(Role.STAFF, "We also have bike racks."),
    ]
    messages = to_messages(request_for("And for bicycles?", history))
    assert [m["role"] for m in messages] == ["user", "assistant", "assistant", "user"]
    assert messages[2]["content"].startswith("(A member of the team replied:)")
    assert messages[-1]["content"] == "And for bicycles?"


def test_refusal_becomes_not_found(request_for):
    client = FakeClient(response(stop_reason="refusal", content=[]))
    assert ClaudeModel(client).answer(request_for()).kind is AnswerKind.NOT_FOUND


def test_cut_off_reply_raises_so_the_core_shows_contacts(request_for):
    client = FakeClient(response(stop_reason="max_tokens"))
    with pytest.raises(RuntimeError):
        ClaudeModel(client).answer(request_for())


def test_usage_and_cost_are_counted(request_for):
    client = FakeClient(response(), response(cache_read=1000))
    model = ClaudeModel(client)
    model.answer(request_for())
    model.answer(request_for())
    u = model.usage
    assert (u.requests, u.input, u.output, u.cache_write, u.cache_read) == (2, 100, 40, 2000, 1000)
    assert u.cost_usd == pytest.approx((100 * 2 + 40 * 10 + 2000 * 2.5 + 1000 * 0.2) / 1_000_000)


def test_through_the_assistant(make_assistant):
    client = FakeClient(
        response("answer", "Cuesta $110."),
        response("not_found", "No tengo esa información. Llame al +1 555 0100."),
        response("medical", ""),
    )
    assistant = make_assistant(model=ClaudeModel(client))
    assert assistant.ask("c1", "¿Cuánto cuesta una limpieza?").text == "Cuesta $110."
    reply = assistant.ask("c2", "¿Venden cepillos?")
    assert reply.kind is ReplyKind.NOT_FOUND and reply.text.startswith("No tengo") and reply.offer_handoff
    assert assistant.ask("c3", "Is this pain normal?").kind is ReplyKind.MEDICAL


def test_model_emergency_needs_the_phone_number_or_the_standard_text_is_used(make_assistant):
    client = FakeClient(
        response("emergency", "Llame ahora al +1 555 0100 o al 911."),
        response("emergency", "Please get help."),
    )
    assistant = make_assistant(model=ClaudeModel(client))
    first = assistant.ask("c1", "Me sangra la encía y no para")
    assert first.kind is ReplyKind.EMERGENCY and first.text.startswith("Llame")
    second = assistant.ask("c2", "Ayuda, es urgente")
    assert second.kind is ReplyKind.EMERGENCY and "911" in second.text and "+1 555 0100" in second.text
