"""The contract between the core and an AI provider.

The core never imports a provider SDK. Each provider (Claude, OpenAI, the
offline mock) is a small class with one method, `answer`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from ..business import Business
from ..knowledge import KnowledgeBase
from ..models import Turn


class AnswerKind(str, Enum):
    ANSWER = "answer"
    NOT_FOUND = "not_found"
    MEDICAL = "medical"


@dataclass(frozen=True)
class AnswerRequest:
    business: Business
    knowledge: KnowledgeBase
    history: tuple[Turn, ...]
    question: str


@dataclass(frozen=True)
class ModelAnswer:
    kind: AnswerKind
    # Written by the model in the customer's language. Empty means "use the
    # core's standard wording" (the mock leaves it empty for NOT_FOUND/MEDICAL).
    text: str = ""


class LanguageModel(Protocol):
    name: str

    def answer(self, request: AnswerRequest) -> ModelAnswer: ...
