"""Persistent state for Sigil sessions.

Global state captures audit/debug events. Session state captures continuity for
one shell, so multiple terminal windows do not overwrite each other's comma
context.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from zeta.events import (
    EVENT_STORE_NAME,
    DraftEvent,
    Filter,
    SqliteEventStore,
    durable_event_draft,
    model_called_event,
    tool_called_event,
    turn_idempotency_key,
)

if TYPE_CHECKING:
    from zeta.events import Event

EVENT_LOG_MAX_BYTES = 10 * 1024 * 1024
SESSION_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,64}\Z")


def state_dir() -> Path:
    """Return the global Sigil state directory."""
    base = os.environ.get("SIGIL_STATE_DIR")
    if base:
        return Path(base)
    return Path.home() / ".sigil"


def safe_session_id(raw: str) -> str:
    """Map a raw session id onto a safe path component.

    The id becomes a path component under the state directory, so values
    that could escape it (separators, `..`, control characters) map to a
    deterministic digest instead of being used verbatim.
    """
    if SESSION_ID_PATTERN.fullmatch(raw) and raw not in {".", ".."}:
        return raw
    return "unsafe-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def session_id() -> str:
    """Return the current shell session identifier."""
    return safe_session_id(os.environ.get("SIGIL_SESSION_ID") or "default")


def session_dir(session_id: str | None = None) -> Path:
    """Return the directory that stores continuity for one shell session.

    Without an explicit id this is the current session, honoring the
    `SIGIL_SESSION_DIR` override. An explicit id names another session
    under the state directory; the override never applies to it.
    """
    if session_id is None:
        base = os.environ.get("SIGIL_SESSION_DIR")
        if base:
            return Path(base)
    raw = session_id or os.environ.get("SIGIL_SESSION_ID") or "default"
    return state_dir() / "sessions" / safe_session_id(raw)


def append_jsonl_line(path: Path, payload: dict[str, Any]) -> None:
    """Append one JSONL payload as a single unbuffered write.

    Concurrent shells append to the same files; one write(2) call per line
    keeps lines from interleaving regardless of payload size.
    """
    line = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    with path.open("ab", buffering=0) as f:
        f.write(line.encode("utf-8"))


def rotate_oversized_log(path: Path) -> None:
    """Move a log aside once it exceeds the size cap, keeping one generation."""
    try:
        size = path.stat().st_size
    except OSError:
        return
    if size < EVENT_LOG_MAX_BYTES:
        return
    try:
        path.replace(path.with_name(f"{path.name}.1"))
    except OSError:
        pass


def _with_envelope(event: dict[str, Any]) -> dict[str, Any]:
    """Stamp default cwd onto event domain data."""
    return {
        "cwd": os.getcwd(),
        **event,
    }


def _session_root() -> Path:
    """Return the session directory, creating it if needed."""
    root = session_dir()
    root.mkdir(parents=True, exist_ok=True)
    return root


def event_store_path() -> Path:
    """Return Sigil's frontend event journal path."""
    return state_dir() / EVENT_STORE_NAME


def sigil_event_store() -> SqliteEventStore:
    """Open Sigil's frontend event journal."""
    return SqliteEventStore(event_store_path())


def read_events() -> list[Event]:
    """Read Sigil's frontend event journal."""
    store = sigil_event_store()
    try:
        return store.list_events(Filter())
    finally:
        store.close()


def history_index(events: list[Event] | None = None) -> Any:
    """Return a Zeta history view over Sigil's durable events."""
    from zeta.history import HistoryIndex

    return HistoryIndex(read_events() if events is None else events)


def event_children(event_id: str, *, limit: int | None = None) -> list[Event]:
    store = sigil_event_store()
    try:
        return store.children(event_id, limit=limit)
    finally:
        store.close()


def causal_chain(event_id: str) -> list[Event]:
    store = sigil_event_store()
    try:
        return store.causal_chain(event_id)
    finally:
        store.close()


def events_for_turn(turn_id: str) -> list[Event]:
    store = sigil_event_store()
    try:
        return store.events_for_turn(turn_id)
    finally:
        store.close()


def append_event(event: dict[str, Any]) -> Event:
    """Append a global audit/debug event with session metadata."""
    from zeta.events import (
        publish_event,
        timestamp_micros_from_time,
    )

    payload = _with_envelope(event)
    event_id = payload.get("id") if isinstance(payload.get("id"), str) else None
    event_type = str(payload.get("type") or "event")
    turn_id = (
        payload.get("turn_id") if isinstance(payload.get("turn_id"), str) else None
    )
    event_session_id = str(payload.get("session") or session_id())
    event_timestamp = timestamp_micros_from_time(payload.get("time"))
    caused_by = (
        str(payload["caused_by"]) if isinstance(payload.get("caused_by"), str) else None
    )
    domain_payload = {
        key: value
        for key, value in payload.items()
        if key not in {"id", "type", "time", "session", "source", "caused_by"}
    }
    draft = durable_draft_from_payload(
        durable_event,
        event_type=event_type,
        payload=domain_payload,
        turn_id=turn_id,
        session_id=event_session_id,
        caused_by=caused_by,
        event_id=event_id,
        timestamp_micros=event_timestamp,
    )
    if draft is None:
        draft = DraftEvent(
            event_type=event_type,
            source=str(payload.get("source") or "sigil"),
            payload=domain_payload,
            caused_by=caused_by,
            session_id=event_session_id,
            turn_id=turn_id,
            timestamp_micros=event_timestamp,
            event_id=event_id,
        )
    store = sigil_event_store()
    try:
        outcome = publish_event(draft, sink=store)
        return outcome.event
    finally:
        store.close()


def append_prompt_submitted_event(event: dict[str, Any]) -> Event:
    prompt_event = dict(event)
    prompt_event["type"] = "sigil.prompt.submitted"
    return append_event(prompt_event)


def append_turn_record(record: dict[str, Any]) -> Event:
    """Append one durable turn record."""
    from .protocols import turn_event_type

    return append_event(
        {
            **record,
            "type": turn_event_type(str(record.get("outcome") or "")),
        }
    )


def append_effect_record(record: dict[str, Any]) -> dict[str, Any]:
    """Append one durable tool-effect event and return its history record."""
    from zeta.history import effect_event_record, event_time

    event = append_event(
        {
            "type": "zeta.tool.called",
            "turn_id": record.get("turn_id"),
            "effects": [record],
        }
    )
    return effect_event_record(
        record,
        timestamp=event_time(event),
        session_id=event.session_id or session_id(),
        cwd=event.payload.get("cwd"),
    )


class DurableEventConstructors:
    """Factories for Sigil durable events with stable metadata."""

    def prompt_submitted(
        self,
        *,
        payload: dict[str, Any],
        turn_id: str | None,
        session_id: str,
        caused_by: str | None = None,
        event_id: str | None = None,
        timestamp_micros: int | None = None,
    ) -> DraftEvent:
        return durable_event_draft(
            "sigil.prompt.submitted",
            "sigil",
            payload=payload,
            turn_id=turn_id,
            session_id=session_id,
            caused_by=caused_by,
            event_id=event_id,
            idempotency_key=turn_idempotency_key("sigil.prompt.submitted", turn_id),
            timestamp_micros=timestamp_micros,
        )

    def turn_completed(
        self,
        *,
        payload: dict[str, Any],
        turn_id: str | None,
        session_id: str,
        caused_by: str | None = None,
        event_id: str | None = None,
        timestamp_micros: int | None = None,
    ) -> DraftEvent:
        return self._turn_event(
            "sigil.turn.completed",
            payload=payload,
            turn_id=turn_id,
            session_id=session_id,
            caused_by=caused_by,
            event_id=event_id,
            timestamp_micros=timestamp_micros,
        )

    def turn_failed(
        self,
        *,
        payload: dict[str, Any],
        turn_id: str | None,
        session_id: str,
        caused_by: str | None = None,
        event_id: str | None = None,
        timestamp_micros: int | None = None,
    ) -> DraftEvent:
        return self._turn_event(
            "sigil.turn.failed",
            payload=payload,
            turn_id=turn_id,
            session_id=session_id,
            caused_by=caused_by,
            event_id=event_id,
            timestamp_micros=timestamp_micros,
        )

    def turn_aborted(
        self,
        *,
        payload: dict[str, Any],
        turn_id: str | None,
        session_id: str,
        caused_by: str | None = None,
        event_id: str | None = None,
        timestamp_micros: int | None = None,
    ) -> DraftEvent:
        return self._turn_event(
            "sigil.turn.aborted",
            payload=payload,
            turn_id=turn_id,
            session_id=session_id,
            caused_by=caused_by,
            event_id=event_id,
            timestamp_micros=timestamp_micros,
        )

    def _turn_event(
        self,
        event_type: str,
        *,
        payload: dict[str, Any],
        turn_id: str | None,
        session_id: str,
        caused_by: str | None,
        event_id: str | None,
        timestamp_micros: int | None,
    ) -> DraftEvent:
        return durable_event_draft(
            event_type,
            "sigil",
            payload=payload,
            turn_id=turn_id,
            session_id=session_id,
            caused_by=caused_by,
            event_id=event_id,
            idempotency_key=turn_idempotency_key(event_type, turn_id),
            timestamp_micros=timestamp_micros,
        )


durable_event = DurableEventConstructors()


def durable_draft_from_payload(
    durable_event: Any,
    *,
    event_type: str,
    payload: dict[str, Any],
    turn_id: str | None,
    session_id: str,
    caused_by: str | None,
    event_id: str | None,
    timestamp_micros: int | None,
) -> Any | None:
    if event_type == "sigil.prompt.submitted":
        return durable_event.prompt_submitted(
            payload=payload,
            turn_id=turn_id,
            session_id=session_id,
            caused_by=caused_by,
            event_id=event_id,
            timestamp_micros=timestamp_micros,
        )
    if event_type == "sigil.turn.completed":
        return durable_event.turn_completed(
            payload=payload,
            turn_id=turn_id,
            session_id=session_id,
            caused_by=caused_by,
            event_id=event_id,
            timestamp_micros=timestamp_micros,
        )
    if event_type == "sigil.turn.failed":
        return durable_event.turn_failed(
            payload=payload,
            turn_id=turn_id,
            session_id=session_id,
            caused_by=caused_by,
            event_id=event_id,
            timestamp_micros=timestamp_micros,
        )
    if event_type == "sigil.turn.aborted":
        return durable_event.turn_aborted(
            payload=payload,
            turn_id=turn_id,
            session_id=session_id,
            caused_by=caused_by,
            event_id=event_id,
            timestamp_micros=timestamp_micros,
        )
    if event_type == "zeta.model.called":
        return model_called_event(
            payload=payload,
            turn_id=turn_id,
            session_id=session_id,
            caused_by=caused_by,
            event_id=event_id,
            timestamp_micros=timestamp_micros,
        )
    if event_type == "zeta.tool.called":
        return tool_called_event(
            payload=payload,
            turn_id=turn_id,
            session_id=session_id,
            caused_by=caused_by,
            event_id=event_id,
            timestamp_micros=timestamp_micros,
        )
    return None


def write_text_atomic(path: Path, text: str) -> None:
    """Replace a file through a unique fsynced tmp file in the same directory.

    Unique tmp names keep concurrent writers from clobbering each other's
    half-written files; fsync before rename keeps a crash from leaving an
    empty renamed file behind.
    """
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f"{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(f.name, path)


def write_json(name: str, value: Any) -> None:
    """Atomically write a session-scoped JSON document."""
    write_text_atomic(
        _session_root() / name, json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    )


def remove_json(name: str) -> bool:
    """Remove a session-scoped JSON document if it exists."""
    path = session_dir() / name
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    return True


def append_jsonl(name: str, event: dict[str, Any]) -> dict[str, Any]:
    """Append a session-scoped JSONL event."""
    payload = _with_envelope(event)
    append_jsonl_line(_session_root() / name, payload)
    return payload


def write_jsonl(name: str, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Replace a session-scoped JSONL file atomically."""
    payloads = [_with_envelope(event) for event in events]
    write_text_atomic(
        _session_root() / name,
        "".join(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
            for payload in payloads
        ),
    )
    return payloads


def read_jsonl(name: str) -> list[dict[str, Any]]:
    """Read a session-scoped JSONL file, skipping malformed lines."""
    return read_jsonl_path(session_dir() / name)


def read_jsonl_path(path: Path) -> list[dict[str, Any]]:
    """Read a JSONL file at an explicit path, skipping malformed lines."""
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except Exception:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def read_json(name: str) -> Any | None:
    """Read a session-scoped JSON document if it exists and parses."""
    path = session_dir() / name
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return value
