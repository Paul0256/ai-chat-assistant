"""Where conversations are logged and how staff are told about handoffs.

The core only knows these two small interfaces. The in-memory versions here
serve the console, the demo and the tests; Google Sheets, email and Telegram
implementations plug in the same way.
"""

from __future__ import annotations

from typing import Protocol

from .models import HandoffRequest, LogEntry, ReplyKind


class ConversationLog(Protocol):
    def append(self, entry: LogEntry) -> None: ...


class HandoffNotifier(Protocol):
    def notify(self, request: HandoffRequest) -> None: ...


class MemoryLog:
    def __init__(self) -> None:
        self.entries: list[LogEntry] = []

    def append(self, entry: LogEntry) -> None:
        self.entries.append(entry)

    def unanswered(self) -> list[LogEntry]:
        return [e for e in self.entries if e.kind is ReplyKind.NOT_FOUND]


class MemoryNotifier:
    def __init__(self) -> None:
        self.requests: list[HandoffRequest] = []

    def notify(self, request: HandoffRequest) -> None:
        self.requests.append(request)
