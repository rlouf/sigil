"""Event store implementations."""

from typing import Protocol, runtime_checkable

from zeta.events import AppendOutcome, DraftEvent, Event, Filter
from zeta.store.events.memory import MemoryEventStore
from zeta.store.events.sqlite import (
    EVENT_STORE_NAME,
    ZETA_STORE_NAME,
    SqliteEventStore,
    append_event_to_log,
    append_event_to_log_outcome,
    event_log_causal_chain,
    event_log_children,
    event_log_turn_events,
    event_store_path,
    publish_event_to_log,
    read_event_log,
)


@runtime_checkable
class EventReader(Protocol):
    """Readable event store capability for projections and inspection."""

    def list_events(self, filter: Filter) -> list[Event]:
        """List durable events matching the filter."""


@runtime_checkable
class EventWriter(Protocol):
    """Appendable event store capability for runtime producers."""

    def accept(self, draft: DraftEvent) -> AppendOutcome:
        """Accept one draft event and return the durable append outcome."""


@runtime_checkable
class EventStoreProtocol(EventReader, EventWriter, Protocol):
    """Full event ledger API shared by memory and SQLite implementations."""

    def append(self, event: Event) -> AppendOutcome:
        """Append one already durable event."""

    def get(self, event_id: str) -> Event | None:
        """Return one event by id."""

    def children(self, event_id: str, *, limit: int | None = None) -> list[Event]:
        """Return direct children caused by an event."""

    def causal_chain(self, event_id: str) -> list[Event]:
        """Return the root-to-event causal chain."""

    def events_for_turn(self, turn_id: str) -> list[Event]:
        """Return events associated with a turn."""

    def clear_session_events(self, session_id: str, *, event_type_prefix: str) -> int:
        """Delete events in one session matching a type prefix."""

    def close(self) -> None:
        """Release store resources."""


__all__ = [
    "AppendOutcome",
    "EVENT_STORE_NAME",
    "EventReader",
    "EventStoreProtocol",
    "EventWriter",
    "Filter",
    "MemoryEventStore",
    "SqliteEventStore",
    "ZETA_STORE_NAME",
    "append_event_to_log",
    "append_event_to_log_outcome",
    "event_log_causal_chain",
    "event_log_children",
    "event_log_turn_events",
    "event_store_path",
    "publish_event_to_log",
    "read_event_log",
]
