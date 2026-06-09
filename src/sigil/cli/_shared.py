"""Shared CLI helpers: stdin handling and JSON output."""

from __future__ import annotations

import json
import sys
from typing import Any, TextIO


def piped_stdin_text() -> str | None:
    """Return piped stdin, treating empty test harness stdin as absent."""
    if sys.stdin.isatty():
        return None
    text = sys.stdin.read()
    return text if text else None


def question_with_stdin(question: str, stdin_text: str) -> str:
    """Attach piped input to a question prompt."""
    if question:
        return f"{question}\n\nPiped input:\n{stdin_text}"
    return f"Piped input:\n{stdin_text}"


def read_json_stdin(stdin: TextIO) -> dict[str, Any]:
    """Read a JSON object from stdin."""
    raw = stdin.read()
    if not raw.strip():
        return {}
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("expected JSON object")
    return data


def pretty_print_json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))
