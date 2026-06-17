"""Portable turn-history bundles."""

from __future__ import annotations

from typing import Any

from zeta.history import import_history_records
from zeta.trace import (
    Derivation,
    Object,
    SqliteStore,
    UnknownSessionError,
    available_session_ids,
    zeta_sqlite_path,
)

from .state import event_store_path, history_view

BUNDLE_VERSION = 1


def export_bundle(
    *,
    since: float | None = None,
    session: str | None = None,
) -> dict[str, Any]:
    """Collect matching turns, their effects, and their trace closures."""
    history = history_view()
    records: list[dict[str, Any]] = []
    turn_ids_by_session: dict[str, list[str]] = {}
    for turn in history.query_turns(session=session, since=since):
        turn_id = str(turn.get("turn_id") or "")
        records.append(turn)
        records.extend(history.effects_for_turn(turn_id))
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
    records = import_history_records(
        history_view(),
        payload.get("records") or [],
        path=event_store_path(),
    )
    objects = 0
    sessions = payload.get("sessions") or {}
    for session_id, graph in sessions.items():
        objects += import_session_graph(session_id, graph)
    return {"records": records, "objects": objects, "sessions": len(sessions)}


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
