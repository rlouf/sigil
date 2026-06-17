"""Core runtime for Sigil."""

from __future__ import annotations

import os
from pathlib import Path

MAX_CONTEXT_FILE_CHARS = 24_000
MAX_CONTEXT_TOTAL_CHARS = 48_000


def zeta_context_for_sigil():
    from zeta.context import context_for_session, zeta_state_dir
    from zeta.tools.registry import registry

    from .sessions import session_dir, session_id

    active_session = session_id()
    zeta_dir = zeta_state_dir()
    return context_for_session(
        session_id=active_session,
        state_dir=zeta_dir,
        session_dir=session_dir(active_session),
        tool_registry=registry,
    )


def load_project_context(cwd: str | Path | None = None) -> str:
    """Load Sigil project instruction files from parent directories."""
    current = Path(cwd or os.getcwd()).resolve()
    sections: list[str] = []
    seen: set[Path] = set()
    for directory in _context_directories(current):
        path = _agents_file(directory)
        if path is None:
            continue
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        section = _project_context_section(path)
        if section:
            sections.append(section)
    while sum(len(section) for section in sections) > MAX_CONTEXT_TOTAL_CHARS:
        sections.pop(0)
    return "\n\n".join(sections)


def _project_context_section(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    text = text.strip()
    if not text:
        return None
    if len(text) > MAX_CONTEXT_FILE_CHARS:
        text = text[:MAX_CONTEXT_FILE_CHARS].rstrip() + "\n... truncated ..."
    return f"Project context from {path}:\n{text}"


def _context_directories(current: Path) -> list[Path]:
    global_directory = Path(os.environ.get("ZETA_STATE_DIR") or Path.home() / ".zeta")
    return [global_directory, *reversed(current.parents), current]


def _agents_file(directory: Path) -> Path | None:
    try:
        for entry in directory.iterdir():
            if entry.name == "AGENTS.md" and entry.is_file():
                return entry
    except OSError:
        return None
    return None
