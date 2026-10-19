from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from assistant.core import Assistant, Limits, MemoryLog, MemoryNotifier, MockModel, load_business

DEMO = Path(__file__).resolve().parent.parent / "demo" / "clinic"


class FakeClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 19, 9, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs) -> None:
        self.now += timedelta(**kwargs)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def clinic():
    return load_business(DEMO)


@pytest.fixture
def conversation_log() -> MemoryLog:
    return MemoryLog()


@pytest.fixture
def notifier() -> MemoryNotifier:
    return MemoryNotifier()


@pytest.fixture
def make_assistant(clinic, conversation_log, notifier, clock):
    def make(model=None, limits: Limits | None = None, business=None) -> Assistant:
        biz, knowledge = clinic
        return Assistant(
            business or biz, knowledge, model or MockModel(), conversation_log, notifier, limits=limits, clock=clock
        )

    return make


@pytest.fixture
def assistant(make_assistant) -> Assistant:
    return make_assistant()
