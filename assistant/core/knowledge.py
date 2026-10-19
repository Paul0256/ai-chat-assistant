"""The business's documents: loading, size checks and sections.

The whole knowledge base goes into the model's context (and its prompt cache),
so there is no vector database. That works up to roughly 150k tokens, which
covers the documents of almost any small business.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

SUPPORTED = {".md", ".txt"}
# ~4 characters per token; leaves room for the conversation and the answer.
MAX_CHARS = 600_000


class KnowledgeError(Exception):
    pass


@dataclass(frozen=True)
class Section:
    document: str
    title: str
    text: str


@dataclass(frozen=True)
class Document:
    name: str
    text: str

    def sections(self) -> list[Section]:
        """Split on markdown headings; text before the first heading is its own section."""
        parts = re.split(r"(?m)^#{1,6}\s+(.+?)\s*$", self.text)
        sections = []
        intro = parts[0].strip()
        if intro:
            sections.append(Section(self.name, self.name, intro))
        for title, body in zip(parts[1::2], parts[2::2], strict=True):
            if body.strip():
                sections.append(Section(self.name, title.strip(), body.strip()))
        return sections


@dataclass(frozen=True)
class KnowledgeBase:
    documents: tuple[Document, ...]

    @classmethod
    def load(cls, folder: str | Path) -> KnowledgeBase:
        folder = Path(folder)
        if not folder.is_dir():
            raise KnowledgeError(f"Knowledge folder not found: {folder}")
        docs = tuple(
            Document(path.name, path.read_text(encoding="utf-8").strip())
            for path in sorted(folder.iterdir())
            if path.suffix.lower() in SUPPORTED and path.is_file()
        )
        kb = cls(tuple(d for d in docs if d.text))
        kb.check()
        return kb

    def check(self) -> None:
        if not self.documents:
            raise KnowledgeError("The knowledge folder has no .md or .txt documents.")
        if self.size > MAX_CHARS:
            raise KnowledgeError(
                f"The documents are too large ({self.size:,} characters, limit {MAX_CHARS:,}). "
                "Split out what customers never ask about, or enable search mode."
            )

    @property
    def size(self) -> int:
        return sum(len(d.text) for d in self.documents)

    def sections(self) -> list[Section]:
        return [s for d in self.documents for s in d.sections()]

    def as_prompt(self) -> str:
        """All documents, each wrapped in a tag, for the model's context."""
        return "\n\n".join(f'<document name="{d.name}">\n{d.text}\n</document>' for d in self.documents)
