# Zeta Semantics

## Run, Session, Queue Item, Attempt

Turbo has the cleaner model for the concepts Zeta is converging on: immutable
events enter the runtime, queue items assign those events to agents, attempts
record concrete executions, and sessions are conversation state associated with
resumable work.

Zeta should not add a separate `turn_id` until there is a concrete durable
`Turn` concept that is different from a run. Today `turn_id` mostly means
`run_id`, which makes the model harder to reason about.

`Session` is durable conversation and workspace state. It owns the transcript,
trace substrate, event sink, and tool registry for one long-lived agent context.

`Run` is a user-visible execution operation. It is the control and correlation
handle for starting, cancelling, timing out, and observing work.

`QueueItem` is dispatch state. It records that one event has been assigned to
one target agent. Queue items should stay generic: event id, target agent, and
status.

`Attempt` is one try at processing a queue item. If retry exists, one queue item
can have multiple attempts. Attempts may be session-scoped, but they are not
intrinsically session state.

The clean identity model is:

```text
session_id    durable conversation/workspace state id
run_id        client-visible operation id; cancellation/status/correlation handle
queue_item_id dispatch id for event -> agent
attempt_id    one execution try for a queue item
```

For session-scoped work, attempt lifecycle payloads should carry both `run_id`
and `session_id` when available. This preserves the links without introducing a
premature turn identity.

## Pre-Refactor Code

Before this refactor, the code mostly linked these concepts indirectly:

- `RpcRunState.run_id` is the live RPC control id.
- `session.turn.requested` uses `turn_id=run_id`.
- dispatch lifecycle events inherit `session_id` and `turn_id` from the
  triggering event.
- `Attempt.session_id` is copied from the triggering event.
- agent-published events carry `_zeta_queue_item_id` and `_zeta_attempt_id`.

That works, but it mixes `run_id` and `turn_id`. The cleaner model should add
`run_id` as first-class event metadata and stop using `turn_id` as the run
correlation id. Remove `turn_id` from the RPC/event shape unless a later
session-history refactor introduces a real `Turn` domain object.

## Kernel Shape

The kernel is missing first-class run identity.

Add a small `kernel/runs.py` domain module:

```python
RunId = str
RunStatus = Literal[
    "starting",
    "running",
    "cancelling",
    "completed",
    "failed",
    "cancelled",
]


@dataclass(frozen=True)
class Run:
    run_id: RunId
    status: RunStatus
    session_id: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
```

Keep mutable execution details such as `asyncio.Task` and cancellation tokens
outside the kernel in RPC/runtime state.

Update `kernel.events.DraftEvent` and `kernel.events.Event` with `run_id` next
to `session_id`. Stores, filters, RPC serialization, and SQLite schema should
follow that metadata.

Update `kernel.dispatch.Attempt` with explicit operation context:

```python
@dataclass(frozen=True)
class Attempt:
    attempt_id: AttemptId
    queue_item_id: QueueItemId
    event_id: str
    attempt_number: int
    target_agent: str
    status: AttemptStatus
    started_at: str
    finished_at: str | None = None
    error: str | None = None
    session_id: str | None = None
    run_id: str | None = None
```

`QueueItem` does not need `run_id` unless queue item payloads must be
self-contained without reading the event envelope. The event envelope should
normally carry `session_id` and `run_id`.

Optionally update `kernel.agents.AgentInvocation` with explicit dispatch
context:

```python
@dataclass(frozen=True)
class AgentInvocation:
    agent: AgentDefinition
    triggering_event: Event
    queue_item_id: str | None = None
    attempt_id: str | None = None
    run_id: str | None = None
    publish_event: AgentEventPublisher | None = None
```

The first implementation step should be `run_id` in event metadata. Once events
can carry `run_id` directly, the rest of the model becomes much less ambiguous.

## Implementation Migration

Most of the implementation work is replacing the current `turn_id=run_id`
convention with first-class `run_id` metadata. Do this as a clean rename unless
a real `Turn` domain object is introduced at the same time.

This should be treated primarily as a semantic rename: everywhere the current
code uses `turn_id` only to mean the client-visible operation handle, rename it
to `run_id`. Do not keep both names for the same value, and do not add
compatibility aliases unless a caller still has a genuine turn concept.

1. Update event storage.

   Add `run_id` to `Filter`, the memory event store, the SQLite event schema,
   event insertion, event hydration, and event listing. Remove or stop using
   `turn_id` filters unless a real turn concept exists.

2. Update event constructors and serializers.

   Helpers in `zeta.events` and RPC wire serialization should expose
   `session_id` and `run_id`, not `turn_id`.

3. Update the session run path.

   `session_turn_requested_draft` should set `run_id=run_id`, not
   `turn_id=run_id`. User, model, tool, and runtime events emitted during the
   session run should inherit the same `run_id`.

4. Update dispatch lifecycle events.

   Queue item and attempt lifecycle events should inherit `run_id` from the
   triggering event. `Attempt` should be constructed with
   `session_id=triggering_event.session_id` and
   `run_id=triggering_event.run_id`.

5. Update agent invocation context.

   If `AgentInvocation` gets first-class dispatch context, pass `run_id`,
   `queue_item_id`, and `attempt_id` there instead of relying only on payload
   tags. Payload tags such as `_zeta_attempt_id` can still remain on
   agent-published events for auditability.

6. Update RPC.

   `session.run` returns `run_id`; `session.cancel` accepts `run_id`;
   `events.list` filters by `run_id`. Remove the `run_id -> turn_id`
   translation.

7. Update trace and history projection.

   Queries that currently use `Filter(turn_id=run_id)` should become
   `Filter(run_id=run_id)`. Final cursor lookup should use
   `session_id + run_id`.

8. Update tests.

   Replace assertions that `turn_id == run_id` with assertions against
   `run_id`. Add one focused test proving attempt lifecycle payloads include
   `run_id` for session-run work.

9. Update docs and planning notes.

   RPC examples and design notes should use `run_id` as the operation
   correlation id. Do not mention `turn_id` unless documenting a future
   session-history `Turn` object.
