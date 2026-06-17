"""Project instruction discovery for Zeta prompts."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .events import EventSink
    from .tools.registry import CapabilityRegistry
    from .trace import Store


@dataclass(frozen=True)
class ZetaContext:
    """Runtime dependencies for one Zeta host/session."""

    session_id: str
    event_sink: EventSink
    trace_store: Store
    tool_registry: CapabilityRegistry
    state_dir: Path
    session_dir: Path


def default_context() -> ZetaContext:
    """Return the default process context for pure Zeta runtime calls."""
    state_dir = zeta_state_dir()
    session_id = os.environ.get("ZETA_SESSION_ID") or "default"
    return context_for_session(
        session_id=session_id,
        state_dir=state_dir,
        session_dir=state_dir / "sessions" / session_id,
    )


def context_for_session(
    *,
    session_id: str,
    state_dir: Path,
    session_dir: Path,
    tool_registry: CapabilityRegistry | None = None,
) -> ZetaContext:
    """Build the default Zeta runtime dependencies for one session."""
    from .events import SqliteEventStore, event_store_path
    from .trace import SqliteStore, zeta_sqlite_path

    if tool_registry is None:
        from .tools.registry import registry as tool_registry

    return ZetaContext(
        session_id=session_id,
        event_sink=SqliteEventStore(event_store_path(state_dir)),
        trace_store=SqliteStore(zeta_sqlite_path(state_dir), session_id=session_id),
        tool_registry=tool_registry,
        state_dir=state_dir,
        session_dir=session_dir,
    )


def zeta_state_dir() -> Path:
    root = os.environ.get("ZETA_STATE_DIR")
    return Path(root).expanduser() if root else Path.home() / ".zeta"
