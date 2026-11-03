from __future__ import annotations

import csv
import json

from assistant.core import MockModel
from assistant.evaluate import report, run

from .conftest import DEMO


def test_eval_checks_kind_and_required_words(tmp_path):
    questions = tmp_path / "q.json"
    questions.write_text(
        json.dumps(
            [
                {"question": "How much is a check-up?", "expect": "answer", "contains": ["$85"]},
                {"question": "How much is a check-up?", "expect": "answer", "contains": ["$999"]},
                {"question": "Do you do braces?", "expect": "not_found"},
                {"question": "My tooth got knocked out!", "expect": "emergency"},
                {"question": "Can I talk to a person?", "expect": "handoff"},
            ]
        )
    )
    results = run(str(DEMO), MockModel(), questions)
    assert [r.ok for r in results] == [True, False, True, True, True]
    assert results[1].missing == ["$999"]
    out = report(results, tmp_path / "out.csv")
    assert "4/5 passed" in out
    rows = list(csv.reader((tmp_path / "out.csv").open(encoding="utf-8")))
    assert rows[0][0] == "ok" and len(rows) == 6


def test_demo_questions_file_is_valid():
    data = json.loads((DEMO / "test_questions.json").read_text(encoding="utf-8"))
    kinds = {"answer", "not_found", "medical", "emergency", "handoff"}
    assert len(data) >= 30 and all(item["expect"] in kinds for item in data)
