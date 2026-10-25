from __future__ import annotations

from datetime import datetime, timezone

import pytest

from assistant.adapters.sheets import HEADER, UNANSWERED_FORMULA, SheetsLog, ensure_tabs, entry_to_row
from assistant.core import LogEntry, ReplyKind


class FakeWorksheet:
    def __init__(self, title: str, fail_times: int = 0, error: Exception | None = None) -> None:
        self.title = title
        self.rows: list[list[str]] = []
        self.updates: list[tuple] = []
        self.calls: list[dict] = []
        self.fail_times = fail_times
        self.error = error

    def append_rows(self, values, **kwargs):
        self.calls.append(kwargs)
        if self.fail_times:
            self.fail_times -= 1
            raise self.error
        self.rows.extend(values)

    def update(self, values, range_name, **kwargs):
        self.updates.append((values, range_name, kwargs))


class FakeSpreadsheet:
    def __init__(self, titles=("Sheet1",)) -> None:
        self.sheets = {t: FakeWorksheet(t) for t in titles}

    def worksheets(self):
        return list(self.sheets.values())

    def add_worksheet(self, title, rows, cols):
        self.sheets[title] = FakeWorksheet(title)
        return self.sheets[title]


class ApiError(Exception):
    def __init__(self, code: int) -> None:
        super().__init__(f"HTTP {code}")
        self.code = code


def entry(question="Do you sell gift cards?", kind=ReplyKind.NOT_FOUND) -> LogEntry:
    return LogEntry(datetime(2026, 10, 25, 9, 30, tzinfo=timezone.utc), "c1", "web", question, "I don't know.", kind)


def test_row_layout():
    assert entry_to_row(entry(), entry_id="abc") == [
        "abc",
        "2026-10-25 09:30:00",
        "c1",
        "web",
        "not_found",
        "Do you sell gift cards?",
        "I don't know.",
    ]


def test_long_text_is_cut_to_fit_a_cell():
    row = entry_to_row(entry(question="x" * 60_000))
    assert len(row[5]) == 45_000


def test_ensure_tabs_creates_header_and_unanswered_formula():
    spreadsheet = FakeSpreadsheet()
    ws = ensure_tabs(spreadsheet)
    assert ws.title == "Conversations"
    assert ws.updates == [([HEADER], "A1", {"value_input_option": "RAW"})]
    unanswered = spreadsheet.sheets["Unanswered"]
    assert unanswered.updates == [([[UNANSWERED_FORMULA]], "A1", {"value_input_option": "USER_ENTERED"})]
    assert "Conversations!E:E" in UNANSWERED_FORMULA  # whole columns survive deleted rows


def test_ensure_tabs_keeps_existing_tabs_untouched():
    spreadsheet = FakeSpreadsheet(titles=("Conversations", "Unanswered"))
    ensure_tabs(spreadsheet)
    assert all(ws.updates == [] for ws in spreadsheet.worksheets())


def test_rows_are_written_raw_in_one_batch():
    ws = FakeWorksheet("Conversations")
    log = SheetsLog(ws)
    log.append(entry('=HYPERLINK("http://evil")'))
    log.append(entry("Is there parking?", ReplyKind.ANSWER))
    assert log.flush() == 2
    assert len(ws.calls) == 1 and ws.calls[0]["value_input_option"] == "RAW"
    assert ws.rows[0][5] == '=HYPERLINK("http://evil")'  # stored as text, never a formula


def test_batches_are_capped():
    ws = FakeWorksheet("Conversations")
    log = SheetsLog(ws, batch_size=2)
    for i in range(5):
        log.append(entry(f"q{i}"))
    log.flush()
    assert len(ws.calls) == 3 and len(ws.rows) == 5


def test_transient_errors_are_retried():
    ws = FakeWorksheet("Conversations", fail_times=2, error=ApiError(503))
    sleeps: list[float] = []
    log = SheetsLog(ws, sleep=sleeps.append)
    log.append(entry())
    log.flush()
    assert len(ws.rows) == 1 and sleeps == [1, 2]


def test_permanent_errors_are_raised():
    ws = FakeWorksheet("Conversations", fail_times=1, error=ApiError(403))
    log = SheetsLog(ws, sleep=lambda s: None)
    log.append(entry())
    with pytest.raises(ApiError):
        log.flush()


def test_background_worker_writes_and_close_flushes():
    ws = FakeWorksheet("Conversations")
    log = SheetsLog(ws).start()
    for i in range(3):
        log.append(entry(f"q{i}"))
    log.close()
    assert [r[5] for r in ws.rows] == ["q0", "q1", "q2"] and log.pending == 0


def test_appending_never_blocks_on_google():
    ws = FakeWorksheet("Conversations", fail_times=99, error=ApiError(503))
    log = SheetsLog(ws)  # no worker started: append only queues
    log.append(entry())
    assert log.pending == 1 and ws.calls == []
