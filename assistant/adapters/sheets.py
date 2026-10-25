"""Conversation log in Google Sheets (gspread + service account).

Tabs:
    Conversations  entry_id | timestamp_utc | conversation_id | channel | kind | question | answer
    Unanswered     the same columns, filled by a formula: every "not_found" row

Writing happens on a background thread in small batches, so a slow or failing
Google API never delays a customer's answer. Values are written RAW, so a
customer typing "=HYPERLINK(...)" stores text, never a formula.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from ..core.models import LogEntry

log = logging.getLogger(__name__)

CONVERSATIONS = "Conversations"
UNANSWERED = "Unanswered"
HEADER = ["entry_id", "timestamp_utc", "conversation_id", "channel", "kind", "question", "answer"]
# Whole columns (not A2:G): Sheets rewrites ranges like A2:G when the first
# rows are deleted. The header row never has kind "not_found", so it is skipped.
UNANSWERED_FORMULA = '=IFERROR(FILTER(Conversations!A:G, Conversations!E:E="not_found"), "")'
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
MAX_CELL = 45_000  # Sheets refuses cells over 50,000 characters
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def entry_to_row(entry: LogEntry, entry_id: str | None = None) -> list[str]:
    return [
        entry_id or uuid.uuid4().hex[:12],
        entry.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
        entry.conversation_id,
        entry.channel,
        entry.kind.value,
        entry.question[:MAX_CELL],
        entry.answer[:MAX_CELL],
    ]


def is_retryable(exc: Exception) -> bool:
    code = getattr(exc, "code", None)
    if code is not None:
        return code in RETRYABLE_STATUS
    return isinstance(exc, (ConnectionError, TimeoutError, OSError)) or type(exc).__name__ in {
        "ConnectionError",
        "Timeout",
        "ReadTimeout",
    }


def ensure_tabs(spreadsheet: Any) -> Any:
    """Create the two tabs if they are missing; return the Conversations worksheet."""
    titles = {ws.title: ws for ws in spreadsheet.worksheets()}
    conversations = titles.get(CONVERSATIONS)
    if conversations is None:
        conversations = spreadsheet.add_worksheet(CONVERSATIONS, rows=1000, cols=len(HEADER))
        conversations.update([HEADER], "A1", value_input_option="RAW")
    if UNANSWERED not in titles:
        unanswered = spreadsheet.add_worksheet(UNANSWERED, rows=1000, cols=len(HEADER))
        unanswered.update([[UNANSWERED_FORMULA]], "A1", value_input_option="USER_ENTERED")
    return conversations


def open_spreadsheet(service_account_file: str | Path, spreadsheet_id: str, timeout: float = 30) -> Any:
    import gspread  # optional dependency: only deployments with a sheet need it

    client = gspread.service_account(filename=str(service_account_file), scopes=SCOPES)
    client.set_timeout(timeout)
    return client.open_by_key(spreadsheet_id)


class SheetsLog:
    """ConversationLog that writes to Google Sheets in the background."""

    def __init__(
        self,
        worksheet: Any,
        *,
        batch_size: int = 50,
        attempts: int = 4,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.worksheet = worksheet
        self.batch_size = batch_size
        self.attempts = attempts
        self._sleep = sleep
        self._queue: queue.Queue[list[str]] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    @classmethod
    def connect(cls, service_account_file: str | Path, spreadsheet_id: str, **kwargs: Any) -> SheetsLog:
        return cls(ensure_tabs(open_spreadsheet(service_account_file, spreadsheet_id)), **kwargs)

    # ConversationLog
    def append(self, entry: LogEntry) -> None:
        self._queue.put(entry_to_row(entry))

    def start(self) -> SheetsLog:
        self._thread = threading.Thread(target=self._run, name="sheets-log", daemon=True)
        self._thread.start()
        return self

    def close(self, timeout: float = 30) -> None:
        """Stop the worker and write whatever is still waiting."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
        self.flush()

    def flush(self) -> int:
        """Write every waiting row now (used on shutdown and in tests). Returns rows written."""
        written = 0
        while True:
            batch = self._take(block=False)
            if not batch:
                return written
            self._write(batch)
            written += len(batch)

    @property
    def pending(self) -> int:
        return self._queue.qsize()

    # ---- internals ------------------------------------------------------------

    def _run(self) -> None:
        while not self._stop.is_set():
            batch = self._take(block=True)
            if not batch:
                continue
            try:
                self._write(batch)
            except Exception:
                log.exception("could not write %d log rows to Google Sheets; will retry", len(batch))
                for row in batch:  # keep them; the next round tries again
                    self._queue.put(row)
                self._stop.wait(30)

    def _take(self, block: bool) -> list[list[str]]:
        rows: list[list[str]] = []
        try:
            rows.append(self._queue.get(block=block, timeout=1 if block else None))
        except queue.Empty:
            return rows
        while len(rows) < self.batch_size:
            try:
                rows.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return rows

    def _write(self, rows: Sequence[list[str]]) -> None:
        for attempt in range(self.attempts):
            try:
                self.worksheet.append_rows(
                    list(rows), value_input_option="RAW", insert_data_option="INSERT_ROWS", table_range="A1"
                )
                return
            except Exception as exc:
                if not is_retryable(exc) or attempt == self.attempts - 1:
                    raise
                delay = 2**attempt
                log.warning("Google Sheets append failed (%s), retrying in %ss", exc, delay)
                self._sleep(delay)
