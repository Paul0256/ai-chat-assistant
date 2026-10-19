"""Offline stand-in for a real model: keyword matching over the document sections.

Good enough to run the demo, the console and the tests without an API key or
costs. It answers in English only and quotes the best-matching section.
"""

from __future__ import annotations

import re

from .base import AnswerKind, AnswerRequest, ModelAnswer

STOPWORDS = set(
    "a an the and or but if to of in on at for with by from is are was were be been do does did can could "
    "would should will i you we my your our me us it this that these those what when where which who how "
    "much many there their have has had any some about please hi hello thanks thank".split()
)

# Questions about symptoms or treatment, not about the business.
MEDICAL_PATTERNS = [
    r"\bshould i (take|use|be worried)\b",
    r"\bis (it|this) normal\b",
    r"\b(antibiotic|painkiller|ibuprofen|paracetamol|medication|medicine)s?\b",
    r"\bwhat (should|can) i do (about|for|with)\b",
    r"\bdo i need (a|an) (filling|root canal|extraction|crown)\b",
]

MIN_SCORE = 2.0


def words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOPWORDS and len(w) > 1]


def stem(word: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


class MockModel:
    name = "mock"

    def answer(self, request: AnswerRequest) -> ModelAnswer:
        question = request.question.lower()
        if request.business.medical and any(re.search(p, question) for p in MEDICAL_PATTERNS):
            return ModelAnswer(AnswerKind.MEDICAL)
        asked = {stem(w) for w in words(question)}
        if not asked:
            return ModelAnswer(AnswerKind.NOT_FOUND)
        best, best_score = None, 0.0
        for section in request.knowledge.sections():
            title = {stem(w) for w in words(section.title)}
            body = {stem(w) for w in words(section.text)}
            score = 2 * len(asked & title) + len(asked & body)
            if score > best_score:
                best, best_score = section, score
        if best is None or best_score < MIN_SCORE:
            return ModelAnswer(AnswerKind.NOT_FOUND)
        return ModelAnswer(AnswerKind.ANSWER, best.text)
