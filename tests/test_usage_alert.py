from __future__ import annotations

from datetime import datetime, timedelta, timezone

from assistant.adapters.usage_alert import UsageAlertLog
from assistant.config import Settings
from assistant.core import MemoryLog
from assistant.core.models import LogEntry, ReplyKind
from assistant.wiring import build_app

T0 = datetime(2026, 11, 18, 18, 0, tzinfo=timezone.utc)


class FakeMailer:
    def __init__(self) -> None:
        self.sent = []

    def send(self, msg) -> None:
        self.sent.append(msg)


def entry(cid: str, q: str = "Do you take Delta Dental?", kind=ReplyKind.ANSWER, t=T0) -> LogEntry:
    return LogEntry(t, cid, "web", q, "Yes, we do.", kind)


def alert_log(per_day: int = 30):
    inner, mailer = MemoryLog(), FakeMailer()
    return (
        UsageAlertLog(inner, mailer, "alerts@x.dev", "me@x.dev", "Trial: Korsmo", per_day, background=False),
        inner,
        mailer,
    )


def test_first_message_of_each_conversation_is_emailed_once():
    log, inner, mailer = alert_log()
    log.append(entry("conv-a"))
    log.append(entry("conv-a", "Where are you?"))
    log.append(entry("conv-b"))
    assert len(inner.entries) == 3
    assert [m["Subject"] for m in mailer.sent] == ["Trial: Korsmo: someone started a conversation"] * 2
    body = mailer.sent[0].get_content()
    assert "Visitor: Do you take Delta Dental?" in body and "Assistant: Yes, we do." in body
    assert mailer.sent[0]["To"] == "me@x.dev"


def test_handoff_is_always_emailed():
    log, _, mailer = alert_log()
    log.append(entry("conv-a"))
    log.append(entry("conv-a", "I want a person", kind=ReplyKind.HANDOFF))
    assert mailer.sent[-1]["Subject"] == "Trial: Korsmo: someone asked for a person"


def test_daily_cap_resets_next_day():
    log, _, mailer = alert_log(per_day=2)
    for i in range(4):
        log.append(entry(f"conv-{i}"))
    assert len(mailer.sent) == 2
    log.append(entry("conv-next", t=T0 + timedelta(days=1)))
    assert len(mailer.sent) == 3


def test_a_failing_mailer_never_breaks_the_chat():
    class Broken:
        def send(self, msg):
            raise OSError("smtp down")

    inner = MemoryLog()
    log = UsageAlertLog(inner, Broken(), "a@x.dev", "b@x.dev", "Demo", background=False)
    log.append(entry("conv-a"))
    assert len(inner.entries) == 1


def test_wiring_adds_alerts_only_when_configured(tmp_path):
    plain = build_app(Settings())
    assert isinstance(plain.conversation_log, MemoryLog)
    configured = build_app(
        Settings(smtp_host="smtp.example", usage_alert_to="me@x.dev", usage_alert_from="alerts@x.dev")
    )
    assert isinstance(configured.conversation_log, UsageAlertLog)
    assert configured.conversation_log.label == "Demo (Riverside Dental Studio)"


def test_each_trial_gets_its_own_alert_label(tmp_path):
    from assistant.trial import Page, write_trial
    from tests.test_trial import DRAFT

    write_trial(DRAFT, [Page("https://brightsmile.example/", "Home", "x")], tmp_path)
    app = build_app(
        Settings(
            trials_folder=str(tmp_path),
            smtp_host="smtp.example",
            usage_alert_to="me@x.dev",
            usage_alert_from="alerts@x.dev",
        )
    )
    trial, _ = app.trials["bright-smile-dental"]
    assert trial.log.label == "Trial: Bright Smile Dental"
