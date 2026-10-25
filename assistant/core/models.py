"""Plain data types shared by the core and the adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Role(str, Enum):
    CUSTOMER = "customer"
    ASSISTANT = "assistant"
    STAFF = "staff"


@dataclass(frozen=True)
class Turn:
    role: Role
    text: str


class ReplyKind(str, Enum):
    ANSWER = "answer"  # answered from the documents
    NOT_FOUND = "not_found"  # the documents don't cover it; nothing was made up
    MEDICAL = "medical"  # asks for medical advice; the assistant never gives it
    EMERGENCY = "emergency"  # urgent; points to the phone or emergency services
    HANDOFF = "handoff"  # passed to a person
    STAFF = "staff"  # a person from the team replied
    LIMITED = "limited"  # message too long, too many messages, daily cap reached
    ERROR = "error"  # something failed on our side


@dataclass(frozen=True)
class Reply:
    kind: ReplyKind
    text: str
    # Show a "Talk to a person" button under this reply.
    offer_handoff: bool = False


@dataclass(frozen=True)
class StaffMessage:
    seq: int  # increases per conversation; the website asks for "everything after seq N"
    text: str
    timestamp: datetime


@dataclass(frozen=True)
class LogEntry:
    timestamp: datetime
    conversation_id: str
    channel: str
    question: str
    answer: str
    kind: ReplyKind


@dataclass(frozen=True)
class HandoffRequest:
    timestamp: datetime
    conversation_id: str
    channel: str
    reason: str
    transcript: tuple[Turn, ...] = field(default_factory=tuple)
