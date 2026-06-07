"""Read tool implementation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import ToolSpec, analysis, effect, error_result, missing

DEFAULT_READ_LIMIT = 2_000

SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["path"],
    "properties": {
        "path": {"type": "string"},
        "offset": {
            "type": "integer",
            "minimum": 0,
            "description": "Number of leading lines to skip (0-based).",
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "description": "Maximum number of lines to return.",
        },
    },
}

SPEC = ToolSpec("read", "Read a UTF-8 text file.", SCHEMA)


def analyze(params: dict[str, Any]) -> dict[str, Any]:
    path = str(params.get("path") or "")
    if not path:
        return missing("path")
    return analysis(effects=[effect("read", path)])


def run(params: dict[str, Any]) -> dict[str, Any]:
    path = Path(str(params.get("path") or ""))
    offset = int(params.get("offset") or 0)
    limit = int(params.get("limit") or DEFAULT_READ_LIMIT)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return error_result("read-failed", str(exc))
    lines = text.splitlines(keepends=True)
    content = "".join(lines[offset : offset + limit])
    return {
        "ok": True,
        "content": [{"type": "text", "text": content}],
        "metadata": {"path": str(path), "offset": offset, "limit": limit},
    }
