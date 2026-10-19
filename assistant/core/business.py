"""The business the assistant works for: contact details and the knowledge folder."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .knowledge import KnowledgeBase


@dataclass(frozen=True)
class Business:
    name: str
    assistant_name: str
    phone: str
    email: str
    address: str
    emergency_number: str
    greeting: str
    # Healthcare businesses get the "no medical advice" rule.
    medical: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> Business:
        return cls(
            name=data["name"],
            assistant_name=data.get("assistant_name", "Assistant"),
            phone=data["phone"],
            email=data["email"],
            address=data.get("address", ""),
            emergency_number=data.get("emergency_number", "112"),
            greeting=data.get("greeting", f"Hi! I'm the assistant of {data['name']}. How can I help?"),
            medical=bool(data.get("medical", False)),
        )


def load_business(folder: str | Path) -> tuple[Business, KnowledgeBase]:
    """Load `business.json` and the documents in `knowledge/` from a business folder."""
    folder = Path(folder)
    business = Business.from_dict(json.loads((folder / "business.json").read_text(encoding="utf-8")))
    return business, KnowledgeBase.load(folder / "knowledge")
