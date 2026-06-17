"""Portable turn-history bundles."""

from __future__ import annotations

from typing import Any

from zeta.events import Event, timestamp_micros_from_time
from zeta.history import HistoryIndex
from zeta.trace import (
    Derivation,
    Object,
    SqliteStore,
    UnknownSessionError,
    available_session_ids,
    zeta_sqlite_path,
)

from .protocols import is_effect_record, is_turn_record
from .state import history_index, sigil_event_store

BUNDLE_VERSION = 1


def export_bundle(
    *,
    since: float | None = None,
    session: str | None = None,
) -> dict[str, Any]:
    """Collect matching turns, their effects, and their trace closures."""
    index = history_index()
    records: list[dict[str, Any]] = []
    turn_ids_by_session: dict[str, list[str]] = {}
    for turn in index.query_turns(session=session, since=since):
        turn_id = str(turn.get("turn_id") or "")
        records.append(turn)
        records.extend(index.effects_for_turn(turn_id))
        session_id = str(turn.get("session") or "")
        turn_ids_by_session.setdefault(session_id, []).append(turn_id)
    sessions: dict[str, dict[str, Any]] = {}
    for session_id, turn_ids in sorted(turn_ids_by_session.items()):
        graph = exported_session_graph(session_id, turn_ids)
        if graph is not None:
            sessions[session_id] = graph
    return {"sigil_bundle": BUNDLE_VERSION, "records": records, "sessions": sessions}


def exported_session_graph(
    session_id: str,
    turn_ids: list[str],
) -> dict[str, Any] | None:
    """Export one session's closure for the given turns, or None.

    A session whose trace store is gone (cleared, or never recorded)
    still exports its history records; only the graph section is absent.
    """
    try:
        available = available_session_ids()
        if session_id not in available:
            raise UnknownSessionError(session_id, available)
        store = SqliteStore(zeta_sqlite_path(), session_id=session_id, read_only=True)
    except UnknownSessionError:
        return None
    try:
        refs: dict[str, str] = {}
        for turn_id in turn_ids:
            target = store.get_ref(f"turn/{turn_id}")
            if target is not None:
                refs[f"turn/{turn_id}"] = target
        if not refs:
            return None
        closure = store.graph_closure(list(refs.values()))
        objects = [
            {
                "id": object_id,
                "kind": obj.kind,
                "schema": obj.schema,
                "data": obj.data,
                "links": list(obj.links),
            }
            for object_id, obj in closure.items()
        ]
        derivations: list[dict[str, Any]] = []
        seen: set[str] = set()
        for object_id in closure:
            for row in store.derivation_records_for_output(object_id):
                if row["id"] not in seen:
                    seen.add(row["id"])
                    derivations.append(row)
        return {"objects": objects, "derivations": derivations, "refs": refs}
    finally:
        store.close()


def import_bundle(payload: dict[str, Any]) -> dict[str, int]:
    """Import a bundle, returning records/objects/sessions counts."""
    if payload.get("sigil_bundle") != BUNDLE_VERSION:
        raise ValueError(f"not a sigil bundle (expected version {BUNDLE_VERSION})")
    records = import_history_records(history_index(), payload.get("records") or [])
    objects = 0
    sessions = payload.get("sessions") or {}
    for session_id, graph in sessions.items():
        objects += import_session_graph(session_id, graph)
    return {"records": records, "objects": objects, "sessions": len(sessions)}


def import_history_records(
    index: HistoryIndex,
    records: list[dict[str, Any]],
) -> int:
    """Import new turn/effect records."""
    imported = 0
    imported_turn_ids: set[str] = set()
    imported_effect_ids: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        if is_turn_record(record):
            record_id = str(record.get("turn_id") or "")
            if record_id in imported_turn_ids or not new_history_record(index, record):
                continue
            imported_turn_ids.add(record_id)
        elif is_effect_record(record):
            record_id = str(record.get("effect_id") or "")
            if record_id in imported_effect_ids or not new_history_record(
                index, record
            ):
                continue
            imported_effect_ids.add(record_id)
        else:
            continue
        if is_effect_record(record):
            event = event_from_effect_record(record)
            store = sigil_event_store()
            try:
                store.append(event)
            finally:
                store.close()
        else:
            event = event_from_record(record)
            store = sigil_event_store()
            try:
                store.append(event)
            finally:
                store.close()
        imported += 1
    return imported


def event_from_effect_record(record: dict[str, Any]) -> Event:
    return Event(
        id=str(record.get("id") or record["effect_id"]),
        event_type="zeta.tool.called",
        source="zeta",
        payload={
            "turn_id": record.get("turn_id"),
            "effects": [record],
        },
        idempotency_key=None,
        caused_by=(
            str(record["caused_by"])
            if isinstance(record.get("caused_by"), str)
            else None
        ),
        session_id=(
            str(record["session"]) if isinstance(record.get("session"), str) else None
        ),
        turn_id=(
            str(record["turn_id"]) if isinstance(record.get("turn_id"), str) else None
        ),
        timestamp_micros=timestamp_micros_from_time(record.get("time")) or 0,
    )


def event_from_record(record: dict[str, Any]) -> Event:
    payload = {
        key: value
        for key, value in record.items()
        if key not in {"id", "type", "time", "session", "source", "caused_by"}
    }
    return Event(
        id=str(record["id"]),
        event_type=str(record["type"]),
        source=str(record.get("source") or "sigil"),
        payload=payload,
        idempotency_key=None,
        caused_by=(
            str(record["caused_by"])
            if isinstance(record.get("caused_by"), str)
            else None
        ),
        session_id=(
            str(record["session"]) if isinstance(record.get("session"), str) else None
        ),
        turn_id=(
            str(record["turn_id"]) if isinstance(record.get("turn_id"), str) else None
        ),
        timestamp_micros=timestamp_micros_from_time(record.get("time")) or 0,
    )


def new_history_record(index: HistoryIndex, record: dict[str, Any]) -> bool:
    """Return whether a record is an importable, not-yet-indexed one."""
    if is_turn_record(record):
        return index.turn(str(record.get("turn_id") or "")) is None
    if is_effect_record(record):
        return index.effect(str(record.get("effect_id") or "")) is None
    return False


def import_session_graph(session_id: str, graph: dict[str, Any]) -> int:
    """Write one session's exported objects, derivations, and refs."""
    store = SqliteStore(zeta_sqlite_path(), session_id=session_id)
    count = 0
    try:
        with store.batch():
            for entry in graph.get("objects") or []:
                store.import_object(
                    str(entry["id"]),
                    Object(
                        kind=str(entry["kind"]),
                        schema=str(entry["schema"]),
                        data=entry["data"],
                        links=tuple(entry["links"]),
                    ),
                )
                count += 1
            for row in graph.get("derivations") or []:
                store.import_derivation(
                    str(row["id"]),
                    Derivation(
                        producer=str(row["producer"]),
                        output_id=str(row["output_id"]),
                        input_ids=tuple(row["input_ids"]),
                        params=row["params"],
                    ),
                    float(row["created_at"]),
                )
            for name, object_id in (graph.get("refs") or {}).items():
                store.set_ref(str(name), str(object_id))
    finally:
        store.close()
    return count
