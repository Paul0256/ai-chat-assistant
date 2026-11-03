"""Run a business's test questions through the configured model and check the replies.

    python -m assistant eval                        # demo/clinic/test_questions.json
    python -m assistant eval --business path/to/folder

Each question says which kind of reply it expects (answer, not_found, medical,
emergency, handoff) and, optionally, words the reply must contain (a price, a
time). Nothing reaches the real staff channels or the Google Sheet: the run
uses an in-memory log and notifier. Results are also written to a CSV file for
review.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

from .core import Assistant, Limits, MemoryLog, MemoryNotifier, Reply, load_business


@dataclass(frozen=True)
class Case:
    question: str
    expect: str
    contains: tuple[str, ...] = ()


@dataclass(frozen=True)
class Result:
    case: Case
    reply: Reply

    @property
    def missing(self) -> list[str]:
        return [word for word in self.case.contains if word.lower() not in self.reply.text.lower()]

    @property
    def ok(self) -> bool:
        return self.reply.kind.value == self.case.expect and not self.missing


def load_cases(path: Path) -> list[Case]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [Case(item["question"], item["expect"], tuple(item.get("contains", ()))) for item in data]


def run(folder: str, model, questions: Path | None = None) -> list[Result]:
    business, knowledge = load_business(folder)
    cases = load_cases(questions or Path(folder) / "test_questions.json")
    # Generous limits: the run sends many messages in a few seconds.
    assistant = Assistant(
        business, knowledge, model, MemoryLog(), MemoryNotifier(), limits=Limits(per_minute=10_000, per_day=10_000)
    )
    # A fresh conversation per question, so answers don't lean on each other.
    return [Result(case, assistant.ask(f"eval-{i:04d}", case.question, "eval")) for i, case in enumerate(cases, 1)]


def report(results: list[Result], csv_path: Path | None = None) -> str:
    lines = []
    for i, r in enumerate(results, 1):
        mark = "OK  " if r.ok else "FAIL"
        got = r.reply.kind.value + (f" (missing {', '.join(r.missing)})" if r.missing else "")
        lines.append(f"{mark} {i:>2}. [{r.case.expect} -> {got}] {r.case.question}")
        if not r.ok:
            lines.append(f"         reply: {r.reply.text}")
    passed = sum(r.ok for r in results)
    lines.append(f"\n{passed}/{len(results)} passed")
    if csv_path is not None:
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["ok", "question", "expected", "got", "missing", "reply"])
            for r in results:
                writer.writerow(
                    [r.ok, r.case.question, r.case.expect, r.reply.kind.value, " ".join(r.missing), r.reply.text]
                )
        lines.append(f"Details: {csv_path}")
    return "\n".join(lines)
