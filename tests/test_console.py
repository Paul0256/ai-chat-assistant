from __future__ import annotations

from assistant.adapters.console import run_demo
from assistant.core import ReplyKind

from .conftest import DEMO


def test_scripted_demo_shows_every_reply_kind(capsys):
    log = run_demo(str(DEMO))
    out = capsys.readouterr().out
    assert "Traceback" not in out
    kinds = [e.kind for e in log.entries]
    assert kinds == [
        ReplyKind.ANSWER,
        ReplyKind.ANSWER,
        ReplyKind.ANSWER,
        ReplyKind.ANSWER,
        ReplyKind.NOT_FOUND,
        ReplyKind.MEDICAL,
        ReplyKind.EMERGENCY,
        ReplyKind.HANDOFF,
    ]
    assert "Unanswered questions: 1" in out and "Handoffs sent to staff: 1" in out
