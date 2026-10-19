"""Checks that run before any model is asked, so they work the same with every provider."""

from __future__ import annotations

import re

# Clear signs that someone needs urgent help. Deliberately narrow: a false
# alarm is acceptable, a missed emergency is not, but ordinary questions such
# as "do you treat tooth pain?" must still reach the documents.
EMERGENCY_PATTERNS = [
    # "emergency" alone, but not "how much is an emergency appointment?"
    r"\bemergency\b(?!\s+(appointment|visit|fee|price|cost|slot|number|hours?)s?\b)",
    r"\b(can'?t|cannot|hard to|trouble) (breathe|breathing|swallow|swallowing)\b",
    r"\b(won'?t|doesn'?t|does not|will not) stop bleeding\b",
    r"\bbleeding (a lot|heavily|badly)\b",
    r"\b(face|jaw|eye|neck) (is )?(very )?swollen\b",
    r"\bswelling (in|of) (my )?(face|jaw|eye|neck)\b",
    r"\bknocked[- ]out tooth\b|\btooth (got )?knocked out\b",
    r"\bunbearable pain\b|\bsevere pain\b",
]

HANDOFF_PATTERNS = [
    r"^/human\b",
    r"\b(talk|speak|chat) (to|with) (a |an |the |your )?"
    r"(human|person|real person|someone|staff|receptionist|doctor|dentist)\b",
    r"\b(human|real person|operator|receptionist),? please\b",
    r"\bcall me back\b",
]


def is_emergency(text: str) -> bool:
    lowered = text.lower()
    return any(re.search(p, lowered) for p in EMERGENCY_PATTERNS)


def wants_human(text: str) -> bool:
    lowered = text.lower().strip()
    return any(re.search(p, lowered) for p in HANDOFF_PATTERNS)
