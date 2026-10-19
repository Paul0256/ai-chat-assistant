from __future__ import annotations

import pytest

from assistant.core import AnswerKind, AnswerRequest, MockModel


def ask(clinic, question):
    business, kb = clinic
    return MockModel().answer(AnswerRequest(business, kb, (), question))


@pytest.mark.parametrize(
    "question, expected",
    [
        ("What are your opening hours?", "Monday to Thursday"),
        ("how much does whitening cost", "$390"),
        ("Is there parking?", "Free parking"),
        ("What do I need to bring for my first visit?", "photo ID"),
        ("cancellation fee?", "$40"),
    ],
)
def test_answers_from_the_documents(clinic, question, expected):
    answer = ask(clinic, question)
    assert answer.kind is AnswerKind.ANSWER and expected in answer.text


@pytest.mark.parametrize("question", ["Do you sell gift cards?", "What's the weather like?", "???"])
def test_says_not_found_instead_of_guessing(clinic, question):
    assert ask(clinic, question).kind is AnswerKind.NOT_FOUND


def test_declines_medical_advice_for_healthcare_businesses(clinic):
    assert ask(clinic, "Should I take antibiotics for my tooth?").kind is AnswerKind.MEDICAL
