from __future__ import annotations

import pytest

from assistant.core.safety import is_emergency, wants_human


@pytest.mark.parametrize(
    "text",
    [
        "This is an emergency",
        "My face is swollen and it hurts",
        "swelling in my jaw since yesterday",
        "the gum won't stop bleeding",
        "I can't breathe properly after the extraction",
        "my tooth got knocked out playing football",
        "I'm in severe pain",
    ],
)
def test_emergencies_are_caught(text):
    assert is_emergency(text)


@pytest.mark.parametrize(
    "text",
    [
        "How much is an emergency appointment?",
        "Do you have emergency appointment slots on Saturday?",
        "Do you treat tooth pain?",
        "Is whitening painful?",
        "What are your opening hours?",
    ],
)
def test_ordinary_questions_are_not_emergencies(text):
    assert not is_emergency(text)


@pytest.mark.parametrize(
    "text", ["/human", "Can I talk to a person?", "I want to speak with the receptionist", "human, please"]
)
def test_requests_for_a_person(text):
    assert wants_human(text)


@pytest.mark.parametrize("text", ["Is the dentist friendly?", "Do you treat children?", "How much is a crown?"])
def test_normal_questions_do_not_trigger_handoff(text):
    assert not wants_human(text)
