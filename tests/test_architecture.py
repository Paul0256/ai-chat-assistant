"""The core must stay independent of platforms and AI providers."""

from __future__ import annotations

import ast
from pathlib import Path

CORE = Path(__file__).resolve().parent.parent / "assistant" / "core"
FORBIDDEN = {"aiogram", "anthropic", "openai", "fastapi", "starlette", "gspread", "assistant.adapters"}


def imported_modules(path: Path) -> set[str]:
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
        elif isinstance(node, ast.ImportFrom) and node.level >= 2 and (node.module or "").startswith("adapters"):
            names.add("assistant.adapters")
    return names


def test_core_imports_no_platform_or_provider_code():
    offenders = {
        str(path.relative_to(CORE)): sorted(
            m for m in imported_modules(path) if m.split(".")[0] in FORBIDDEN or m in FORBIDDEN
        )
        for path in CORE.rglob("*.py")
    }
    assert {k: v for k, v in offenders.items() if v} == {}
