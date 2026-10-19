from __future__ import annotations

import pytest

from assistant.core import KnowledgeBase, KnowledgeError
from assistant.core import knowledge as knowledge_module

from .conftest import DEMO


def test_demo_clinic_loads_every_markdown_document(clinic):
    business, kb = clinic
    assert business.name == "Riverside Dental Studio" and business.medical
    assert len(kb.documents) == 5
    titles = {s.title for s in kb.sections()}
    assert "What are your opening hours?" in titles and "Teeth whitening" in titles


def test_prompt_wraps_each_document(clinic):
    _, kb = clinic
    prompt = kb.as_prompt()
    assert prompt.count("<document name=") == len(kb.documents)
    assert "48 Riverside Avenue" in prompt


def test_text_before_first_heading_is_a_section(tmp_path):
    (tmp_path / "notes.txt").write_text("We are a family business.\n\n## Pets\nDogs are welcome.")
    sections = KnowledgeBase.load(tmp_path).sections()
    assert [(s.title, s.text) for s in sections] == [
        ("notes.txt", "We are a family business."),
        ("Pets", "Dogs are welcome."),
    ]


def test_unsupported_and_empty_files_are_ignored(tmp_path):
    (tmp_path / "faq.md").write_text("## Q\nA")
    (tmp_path / "empty.md").write_text("   ")
    (tmp_path / "logo.png").write_bytes(b"\x89PNG")
    assert [d.name for d in KnowledgeBase.load(tmp_path).documents] == ["faq.md"]


def test_missing_or_empty_folder_is_a_clear_error(tmp_path):
    with pytest.raises(KnowledgeError, match="not found"):
        KnowledgeBase.load(tmp_path / "nope")
    with pytest.raises(KnowledgeError, match="no .md or .txt"):
        KnowledgeBase.load(tmp_path)


def test_too_large_knowledge_base_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(knowledge_module, "MAX_CHARS", 10)
    (tmp_path / "faq.md").write_text("x" * 11)
    with pytest.raises(KnowledgeError, match="too large"):
        KnowledgeBase.load(tmp_path)


def test_demo_folder_exists():
    assert (DEMO / "business.json").is_file()
