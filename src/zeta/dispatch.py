"""Append events, publish them, and route matching agents."""

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, cast

from zeta.kernel.agents import AgentDefinition, AgentInvocation, EventPattern
from zeta.kernel.dispatch import Attempt, QueueItem
from zeta.kernel.events import DraftEvent, Event
from zeta.store.events import EventWriter

AgentResult = dict[str, Any] | Awaitable[dict[str, Any]]
AgentRunner = Callable[["AgentInvocation"], AgentResult]

__all__ = [
    "AgentDefinition",
    "AgentPublicationHopLimitError",
    "AgentInvocation",
    "EventDispatcher",
    "DispatchOutcome",
    "EventPattern",
    "RegisteredAgent",
    "ReservedRuntimeEventError",
    "MAX_AGENT_PUBLICATION_HOPS",
    "RecursiveAgentPublicationError",
    "terminal_agent_result",
    "terminal_queue_item_result",
]

RESERVED_RUNTIME_EVENT_PREFIXES = ("runtime.queue_item.", "runtime.attempt.")
AGENT_PUBLICATION_HOP_KEY = "_zeta_dispatch_hop"
MAX_AGENT_PUBLICATION_HOPS = 8


@dataclass(frozen=True)
class RegisteredAgent:
    """Dispatch registration for an agent definition plus executable runner."""

    definition: AgentDefinition
    run: AgentRunner | None = None


@dataclass(frozen=True)
class DispatchOutcome:
    """Result of accepting and routing one incoming event."""

    event: Event
    inserted: bool
    lifecycle_events: list[Event]


@dataclass(frozen=True)
class ReservedRuntimeEventError(ValueError):
    """Raised when external ingress tries to write runtime-owned lifecycle."""

    event_type: str

    def __post_init__(self) -> None:
        super().__init__(f"external event ingress cannot accept {self.event_type!r}")


@dataclass(frozen=True)
class RecursiveAgentPublicationError(ValueError):
    agent_id: str
    event_type: str

    def __post_init__(self) -> None:
        super().__init__(
            f"agent {self.agent_id!r} cannot publish recursive event "
            f"{self.event_type!r}"
        )


@dataclass(frozen=True)
class AgentPublicationHopLimitError(ValueError):
    event_type: str
    hop: int

    def __post_init__(self) -> None:
        super().__init__(
            f"agent-published event {self.event_type!r} exceeds hop limit "
            f"{MAX_AGENT_PUBLICATION_HOPS}"
        )


class EventDispatcher:
    """Async event dispatcher that routes matching agents in a task group."""

    def __init__(
        self,
        event_sink: EventWriter,
        *,
        agents: Iterable[RegisteredAgent] = (),
        publish_event: Callable[[Event], None] | None = None,
    ) -> None:
        self.event_sink = event_sink
        self.agents = tuple(agents)
        self.publish_callback = publish_event

    async def publish_event(
        self,
        draft: DraftEvent,
        *,
        route: bool = True,
    ) -> DispatchOutcome:
        reject_reserved_runtime_event(draft)
        outcome = self.event_sink.accept(draft)
        if not outcome.inserted:
            return DispatchOutcome(outcome.event, False, [])
        self._publish(outcome.event)
        lifecycle_events = await self.route(outcome.event) if route else []
        return DispatchOutcome(outcome.event, True, lifecycle_events)

    async def route(self, event: Event) -> list[Event]:
        lifecycle_events: list[Event] = []
        matching_agents = self.matching_agents(event)
        if not matching_agents:
            return [self._append_unhandled_queue_item_event(event)]
        task_results: list[list[Event] | None] = [None] * len(matching_agents)
        async with asyncio.TaskGroup() as task_group:
            for index, agent in enumerate(matching_agents):
                task_group.create_task(
                    self._run_agent_into(task_results, index, agent, event)
                )
        for task_result in task_results:
            if task_result is None:
                continue
            lifecycle_events.extend(task_result)
        return lifecycle_events

    def matching_agents(self, event: Event) -> list[RegisteredAgent]:
        return [agent for agent in self.agents if agent.definition.accepts(event)]

    async def _run_agent_into(
        self,
        results: list[list[Event] | None],
        index: int,
        agent: RegisteredAgent,
        triggering_event: Event,
    ) -> None:
        results[index] = await self._run_agent(agent, triggering_event)

    async def _run_agent(
        self,
        agent: RegisteredAgent,
        triggering_event: Event,
    ) -> list[Event]:
        queue_item_id = queue_item_id_for_event(agent, triggering_event)
        available_queue_item = queue_item_for_agent(
            agent,
            triggering_event,
            queue_item_id,
            "available",
        )
        created = self._append_lifecycle_event(
            "runtime.queue_item.created",
            triggering_event,
            queue_item_payload(available_queue_item),
            idempotency_key=queue_item_idempotency_key(
                triggering_event,
                agent.definition.agent_id,
                "created",
            ),
        )
        events = [created]
        if agent.run is None:
            return events
        attempt_number = 1
        attempt_id = attempt_id_for_queue_item(queue_item_id, attempt_number)
        claimed_queue_item = queue_item_for_agent(
            agent,
            triggering_event,
            queue_item_id,
            "claimed",
        )
        claimed = self._append_lifecycle_event(
            "runtime.queue_item.claimed",
            triggering_event,
            queue_item_payload(claimed_queue_item),
            idempotency_key=queue_item_idempotency_key(
                triggering_event,
                agent.definition.agent_id,
                "claimed",
                attempt_number=attempt_number,
            ),
        )
        events.append(claimed)
        started_at = event_timestamp()
        running_attempt = attempt_for_agent(
            agent,
            triggering_event,
            queue_item_id,
            attempt_id,
            attempt_number,
            "running",
            started_at=started_at,
        )
        started = self._append_lifecycle_event(
            "runtime.attempt.started",
            triggering_event,
            attempt_payload(running_attempt),
            idempotency_key=attempt_idempotency_key(
                queue_item_id,
                attempt_number,
                "started",
            ),
        )
        events.append(started)
        try:
            result = await maybe_await(
                agent.run(
                    AgentInvocation(
                        agent.definition,
                        triggering_event,
                        publish_event=self._agent_event_publisher(
                            agent,
                            triggering_event,
                            queue_item_id,
                            attempt_id,
                        ),
                    )
                )
            )
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            failed_attempt_value = attempt_for_agent(
                agent,
                triggering_event,
                queue_item_id,
                attempt_id,
                attempt_number,
                "failed",
                started_at=started_at,
                finished_at=event_timestamp(),
                error=error,
            )
            failed_attempt = self._append_lifecycle_event(
                "runtime.attempt.failed",
                triggering_event,
                attempt_payload(failed_attempt_value),
                idempotency_key=attempt_idempotency_key(
                    queue_item_id,
                    attempt_number,
                    "failed",
                ),
            )
            events.append(failed_attempt)
            failed_queue_item_value = queue_item_for_agent(
                agent,
                triggering_event,
                queue_item_id,
                "failed",
            )
            failed_queue_item = self._append_lifecycle_event(
                "runtime.queue_item.failed",
                triggering_event,
                queue_item_payload(failed_queue_item_value, error=error),
                idempotency_key=queue_item_idempotency_key(
                    triggering_event,
                    agent.definition.agent_id,
                    "failed",
                ),
            )
            events.append(failed_queue_item)
            return events
        attempt_terminal_type = terminal_attempt_event_type(result)
        attempt_status = attempt_terminal_type.rsplit(".", 1)[-1]
        terminal_attempt_value = attempt_for_agent(
            agent,
            triggering_event,
            queue_item_id,
            attempt_id,
            attempt_number,
            attempt_status,
            started_at=started_at,
            finished_at=event_timestamp(),
        )
        completed_attempt = self._append_lifecycle_event(
            attempt_terminal_type,
            triggering_event,
            attempt_payload(terminal_attempt_value, result=result),
            idempotency_key=attempt_idempotency_key(
                queue_item_id,
                attempt_number,
                attempt_status,
            ),
        )
        events.append(completed_attempt)
        queue_terminal_type = terminal_queue_item_event_type(result)
        queue_status = queue_terminal_type.rsplit(".", 1)[-1]
        terminal_queue_item_value = queue_item_for_agent(
            agent,
            triggering_event,
            queue_item_id,
            queue_status,
        )
        completed_queue_item = self._append_lifecycle_event(
            queue_terminal_type,
            triggering_event,
            queue_item_payload(terminal_queue_item_value, result=result),
            idempotency_key=queue_item_idempotency_key(
                triggering_event,
                agent.definition.agent_id,
                queue_status,
            ),
        )
        events.append(completed_queue_item)
        return events

    def _append_lifecycle_event(
        self,
        event_type: str,
        triggering_event: Event,
        payload: dict[str, Any],
        *,
        idempotency_key: str,
    ) -> Event:
        draft = DraftEvent(
            event_type,
            "zeta",
            payload,
            idempotency_key=idempotency_key,
            caused_by=triggering_event.id,
            session_id=triggering_event.session_id,
            turn_id=triggering_event.turn_id,
        )
        event = self.event_sink.accept(draft).event
        self._publish(event)
        return event

    def _append_unhandled_queue_item_event(self, triggering_event: Event) -> Event:
        queue_item_id = f"qi_{triggering_event.id}_unhandled"
        queue_item = QueueItem(
            queue_item_id=queue_item_id,
            event_id=triggering_event.id,
            target_agent="",
            status="unhandled",
        )
        return self._append_lifecycle_event(
            "runtime.queue_item.unhandled",
            triggering_event,
            queue_item_payload(queue_item),
            idempotency_key=unhandled_queue_item_idempotency_key(triggering_event),
        )

    def _publish(self, event: Event) -> None:
        if self.publish_callback is not None:
            self.publish_callback(event)

    def _agent_event_publisher(
        self,
        agent: RegisteredAgent,
        triggering_event: Event,
        queue_item_id: str,
        attempt_id: str,
    ) -> Callable[[DraftEvent], Awaitable[Event]]:
        async def publish(draft: DraftEvent) -> Event:
            if agent_accepts_draft(agent, draft):
                raise RecursiveAgentPublicationError(
                    agent.definition.agent_id,
                    draft.event_type,
                )
            next_hop = agent_publication_next_hop(triggering_event, draft)
            tagged = DraftEvent(
                draft.event_type,
                draft.source,
                {
                    **draft.payload,
                    "_zeta_queue_item_id": queue_item_id,
                    "_zeta_attempt_id": attempt_id,
                    "_zeta_target_agent": agent.definition.agent_id,
                    "_zeta_triggering_event_id": triggering_event.id,
                    AGENT_PUBLICATION_HOP_KEY: next_hop,
                },
                idempotency_key=draft.idempotency_key,
                caused_by=draft.caused_by or triggering_event.id,
                session_id=draft.session_id or triggering_event.session_id,
                turn_id=draft.turn_id or triggering_event.turn_id,
            )
            outcome = await self.publish_event(tagged)
            return outcome.event

        return publish


async def maybe_await(result: AgentResult) -> dict[str, Any]:
    if inspect.isawaitable(result):
        return await cast(Awaitable[dict[str, Any]], result)
    return result


def reject_reserved_runtime_event(draft: DraftEvent) -> None:
    if draft.event_type.startswith(RESERVED_RUNTIME_EVENT_PREFIXES):
        raise ReservedRuntimeEventError(draft.event_type)


def agent_accepts_draft(agent: RegisteredAgent, draft: DraftEvent) -> bool:
    event = Event.from_draft(draft)
    return agent.definition.accepts(event)


def agent_publication_next_hop(
    triggering_event: Event,
    draft: DraftEvent,
) -> int:
    hop = event_publication_hop(triggering_event)
    if hop >= MAX_AGENT_PUBLICATION_HOPS:
        raise AgentPublicationHopLimitError(draft.event_type, hop)
    return hop + 1


def event_publication_hop(event: Event) -> int:
    value = event.payload.get(AGENT_PUBLICATION_HOP_KEY)
    if isinstance(value, int) and value >= 0:
        return value
    return 0


def required_payload_string(event: Event, key: str) -> str | None:
    value = event.payload.get(key)
    if isinstance(value, str):
        return value
    return None


def optional_payload_string(event: Event, key: str) -> str | None:
    value = event.payload.get(key)
    if isinstance(value, str):
        return value
    return None


def queue_item_result(event: Event) -> dict[str, Any] | None:
    result = event.payload.get("result")
    if isinstance(result, dict):
        return result
    return None


def queue_item_id_for_event(agent: RegisteredAgent, event: Event) -> str:
    agent_id = agent.definition.agent_id.replace(":", "_").replace(".", "_")
    return f"qi_{event.id}_{agent_id}"


def attempt_id_for_queue_item(queue_item_id: str, attempt_number: int) -> str:
    return f"att_{queue_item_id}_{attempt_number}"


def queue_item_idempotency_key(
    event: Event,
    target_agent: str,
    status: str,
    *,
    attempt_number: int | None = None,
) -> str:
    key = f"queue_item:{event.id}:{target_agent}:{status}"
    if attempt_number is None:
        return key
    return f"{key}:{attempt_number}"


def unhandled_queue_item_idempotency_key(event: Event) -> str:
    return f"queue_item:{event.id}:unhandled"


def attempt_idempotency_key(
    queue_item_id: str,
    attempt_number: int,
    status: str,
) -> str:
    return f"attempt:{queue_item_id}:{attempt_number}:{status}"


def queue_item_for_agent(
    agent: RegisteredAgent,
    event: Event,
    queue_item_id: str,
    status: Any,
) -> QueueItem:
    return QueueItem(
        queue_item_id=queue_item_id,
        event_id=event.id,
        target_agent=agent.definition.agent_id,
        status=status,
    )


def queue_item_payload(
    queue_item: QueueItem,
    **extra: Any,
) -> dict[str, Any]:
    return {**asdict(queue_item), **extra}


def attempt_for_agent(
    agent: RegisteredAgent,
    event: Event,
    queue_item_id: str,
    attempt_id: str,
    attempt_number: int,
    status: Any,
    *,
    started_at: str,
    finished_at: str | None = None,
    error: str | None = None,
) -> Attempt:
    return Attempt(
        attempt_id=attempt_id,
        queue_item_id=queue_item_id,
        event_id=event.id,
        attempt_number=attempt_number,
        target_agent=agent.definition.agent_id,
        status=status,
        started_at=started_at,
        finished_at=finished_at,
        error=error,
        session_id=event.session_id,
    )


def attempt_payload(
    attempt: Attempt,
    **extra: Any,
) -> dict[str, Any]:
    return {**asdict(attempt), **extra}


def terminal_attempt_event_type(result: dict[str, Any]) -> str:
    outcome = result.get("outcome")
    if outcome in {"aborted", "cancelled"}:
        return "runtime.attempt.cancelled"
    return "runtime.attempt.completed"


def terminal_queue_item_event_type(result: dict[str, Any]) -> str:
    outcome = result.get("outcome")
    if outcome in {"aborted", "cancelled"}:
        return "runtime.queue_item.cancelled"
    return "runtime.queue_item.completed"


TERMINAL_QUEUE_ITEM_EVENT_TYPES = {
    "runtime.queue_item.completed",
    "runtime.queue_item.failed",
    "runtime.queue_item.cancelled",
}


def terminal_agent_result(lifecycle_events: Iterable[Event]) -> dict[str, Any] | None:
    for event in reversed(tuple(lifecycle_events)):
        result = terminal_queue_item_event_result(event)
        if result is not None:
            return result
    return None


def terminal_queue_item_result(
    lifecycle_events: Iterable[Event],
    *,
    event_id: str,
    target_agent: str,
) -> dict[str, Any] | None:
    for event in reversed(tuple(lifecycle_events)):
        if event.event_type not in TERMINAL_QUEUE_ITEM_EVENT_TYPES:
            continue
        if required_payload_string(event, "event_id") != event_id:
            continue
        if required_payload_string(event, "target_agent") != target_agent:
            continue
        return terminal_queue_item_event_result(event)
    return None


def terminal_queue_item_event_result(event: Event) -> dict[str, Any] | None:
    if event.event_type not in TERMINAL_QUEUE_ITEM_EVENT_TYPES:
        return None
    result = queue_item_result(event)
    if result is not None:
        return result_with_final_cursor(result, event)
    return result_with_final_cursor(terminal_fallback_result(event), event)


def terminal_fallback_result(event: Event) -> dict[str, Any]:
    fallback: dict[str, Any] = {
        "outcome": optional_payload_string(event, "status")
        or event.event_type.rsplit(".", 1)[-1]
    }
    error = optional_payload_string(event, "error")
    if error is not None:
        fallback["error"] = error
    return fallback


def result_with_final_cursor(result: dict[str, Any], event: Event) -> dict[str, Any]:
    if event.cursor is None:
        return dict(result)
    return {**result, "final_event_cursor": str(event.cursor)}


def event_timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
