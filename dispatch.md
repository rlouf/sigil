# Event-Sourced Dispatch Implementation Plan

## Target Shape

Refactor the Python dispatcher toward the `zeta-dispatch` model, but use the
clearer queue item / attempt ontology:

```text
validate
  -> enrich/store Event
  -> publish Event
  -> route Event
  -> create QueueItem per matching agent
  -> create Attempt when a worker claims a QueueItem
  -> run loop
  -> finish Attempt
  -> complete, retry, fail, or cancel QueueItem
```

The goal is one event-sourced run path for interactive `session.run` and
event-triggered agents.

## Behavior To Preserve

- `events.publish` appends incoming events and publishes them.
- Duplicate idempotency keys do not route queue items twice.
- Interactive `session.run` validates params and returns the final answer.
- Runtime UI events can still be streamed live.
- Cancellation and deadlines produce terminal run results.
- Agent failures produce failed attempts rather than crashing the dispatcher.
- Existing model/tool loop behavior stays inside `loop.py`.

## Original Pain

- `session.run` creates `session.turn.requested`, routes it through a generic
  dispatcher, and then unwraps a direct agent return value.
- `DispatchOutcome` mixed append results, lifecycle events, and agent return
  values.
- The previous work-event model was vague: it conflated queue item state,
  attempt state, and final agent results.
- Interactive runs and event-triggered runs are conceptually separate even
  though they need the same lifecycle.

## Intended Design Improvement

Make appended events the only trigger surface.

Make queue items the durable association between events and agents.

Make attempts the durable record of one worker trying to process one queue item.

Make synchronous interactive RPC a client-side observation mode over a queue
item or attempt, not a special execution path.

## Refactor TODOs

Use this checklist when continuing the refactor. Keep each slice small, start
with tests, and clean up obsolete code in the same slice that makes it
unnecessary.

- [x] Add kernel `QueueItem` and `Attempt` shapes.
- [x] Replace vague work events with queue item and attempt
  lifecycle events.
- [x] Rename dispatch output to `lifecycle_events`.
- [x] Make `session.run` derive its final RPC result from terminal lifecycle
  events.
- [x] Remove the direct agent result field from `DispatchOutcome`.
  - Added tests proving RPC still returns the same response from lifecycle
    events.
  - Removed the direct agent result field from `DispatchOutcome`.
  - Removed result accumulation from `EventDispatcher.dispatch`.
  - Removed the `run_rpc_session` compatibility fallback.
  - Removed direct agent results from `events.publish` responses and updated
    tests.
- [x] Split `EventDispatcher.dispatch` into append/publish and route/execute
  operations.
  - Added tests for duplicate idempotency keys, reserved runtime lifecycle event
    ingress, and route-disabled appends.
  - [x] Normalize lifecycle idempotency keys to the stable format described below:
    `queue_item:<event_id>:<target_agent>:created` and
    `attempt:<queue_item_id>:<attempt_number>:started`, not the current
    event-type-prefixed compatibility format.
  - Introduced explicit `publish_event(draft, route=True)` and `route(event)`
    methods or equally small names that match the codebase.
  - Kept lifecycle event appends internal so callers cannot inject
    `runtime.queue_item.*` or `runtime.attempt.*` as external facts.
  - Deleted any helper or test fixture that only exists to preserve the old
    all-in-one dispatch API.
- [x] Serialize kernel queue item and attempt objects into lifecycle events.
  - Constructed `QueueItem` and `Attempt` from `zeta.kernel.dispatch` in the
    dispatcher.
  - Serialized those kernel objects into lifecycle event payloads.
  - Removed separate queue item and attempt projection objects from dispatch.
  - Kept lifecycle events as the durable source of truth.
  - Added `session_id` to attempt lifecycle payloads.
- [x] Broaden terminal lifecycle result coverage.
  - Added focused tests for `runtime.queue_item.failed` and
    `runtime.queue_item.cancelled` mapping to RPC results.
  - Kept `runtime.queue_item.completed` as the happy-path terminal result.
  - Replaced `terminal_agent_result` with terminal lifecycle event result
    derivation.
- [x] Register the interactive runner as a normal built-in agent.
  - Added `session_turn_agent(...)` as the built-in
    `session.turn.requested` agent registration.
  - Kept the runner as a thin adapter from `session.turn.requested` to the
    existing loop.
  - Wired the CLI to reuse one dispatcher with the built-in session agent.
  - Deleted the old one-off session dispatcher helper from `session.py`.
  - Deleted the event-to-turn adapter glue from `session.py`.
  - Kept `run_session_turn` as the reusable boundary around session request
    validation, timeline projection, and loop execution.
- [x] Change `session.run` to append and observe.
  - Validate params and append `session.turn.requested`.
  - Observe the terminal queue item for the interactive session agent.
  - Map the terminal lifecycle event to the current JSON-RPC response shape.
  - Kept `events.publish` response semantics focused on appended event plus
    lifecycle/route observation data, not direct agent return values.
  - Deleted direct unwrapping of dispatch execution results.
- [x] Keep `loop.py` as the model/tool execution engine unless a specific
  cleanup becomes obvious.
  - Did not move queue item or attempt ownership into `loop.py`.
  - Kept attempt lifecycle context in dispatcher/session wiring, not in the loop
    engine.
  - Found no loop cleanup made demonstrably safe by this slice.
- [x] Add agent-published events.
  - Added `AgentInvocation.publish(...)` for agent-authored event drafts.
  - Attached active `caused_by`, `session_id`, `turn_id`, queue item, attempt,
    target agent, triggering event, and dispatch hop context.
  - Added a conservative hop limit.
  - Rejected obvious recursive self-publication until there is a real use case.
- [x] Final cleanup pass.
  - Searched for and removed obsolete compatibility names, dead adapters, stale
    tests, and unused helpers introduced during the migration.
  - Ran structural/string searches for old direct-result, work-event, one-off
    session dispatcher, and return-oriented dispatch concepts.
  - Kept only tests that assert old response fields are absent.
  - Did not keep backward compatibility for removed internal APIs.

## Step 1: Lock Existing Behavior

Add or update focused pytest coverage before changing implementation:

- dispatching an unmatched event appends the event and records an unhandled
  queue item outcome
- dispatching a matched event creates a queue item, starts an attempt, and
  completes both on success
- duplicate idempotency keys append once and do not create a second queue item
- a failing agent records a failed attempt and preserves the error
- `session.run` still returns the final answer
- `session.run` duplicate `run_id` does not execute twice
- cancellation maps to cancelled attempt and queue item state
- live stream events still reach `publish_event`

Run targeted tests after this step:

```bash
uv run pytest tests/test_zeta_agent.py tests/test_zeta_agents.py
```

## Step 2: Add Kernel Shapes

Add pure shared shapes under `src/zeta/kernel/`.

Suggested module:

```text
src/zeta/kernel/dispatch.py
```

Suggested shapes:

```python
QueueItemStatus = Literal[
    "available",
    "claimed",
    "completed",
    "failed",
    "cancelled",
    "retry_scheduled",
    "unhandled",
]

AttemptStatus = Literal[
    "running",
    "completed",
    "failed",
    "cancelled",
]
```

And frozen dataclasses for:

```text
QueueItem
Attempt
```

Keep these shapes boring and serializable. Do not put store access, claim logic,
retry scheduling, or bus behavior in kernel.

## Step 3: Introduce Queue Item And Attempt Event Helpers

Create a narrow lifecycle event surface in the dispatch layer.

The helper should build drafts for queue item events:

```text
runtime.queue_item.created
runtime.queue_item.claimed
runtime.queue_item.completed
runtime.queue_item.failed
runtime.queue_item.cancelled
runtime.queue_item.retry_scheduled
runtime.queue_item.unhandled
```

And attempt events:

```text
runtime.attempt.started
runtime.attempt.heartbeat
runtime.attempt.completed
runtime.attempt.failed
runtime.attempt.cancelled
```

Queue item payloads should include:

```text
queue_item_id
event_id
target_agent
status
```

Attempt payloads should include:

```text
attempt_id
queue_item_id
event_id
attempt_number
target_agent
status
started_at
finished_at
error
session_id
```

Keep environment-specific metadata optional:

```text
agent_sha256
base_commit_hash
commit_hash
merge_error
branch_name
worktree_path
```

Use stable idempotency keys:

```text
queue_item:<event_id>:<target_agent>:created
queue_item:<event_id>:<target_agent>:claimed:<attempt_number>
queue_item:<event_id>:<target_agent>:completed
queue_item:<event_id>:<target_agent>:failed
queue_item:<event_id>:<target_agent>:cancelled
queue_item:<event_id>:unhandled
attempt:<queue_item_id>:<attempt_number>:started
attempt:<queue_item_id>:<attempt_number>:completed
attempt:<queue_item_id>:<attempt_number>:failed
attempt:<queue_item_id>:<attempt_number>:cancelled
```

Keep this local and explicit. Do not add a generic framework around it.

## Step 4: Separate Append/Publish From Route/Execute

Change the dispatcher internals into two operations:

```python
publish_event(draft: DraftEvent, *, route: bool = True) -> AppendOutcome
route(event: Event) -> None
```

`publish_event` should:

- reject external ingress for reserved `runtime.queue_item.*` and
  `runtime.attempt.*` events
- append to the event store
- publish the durable event only when inserted
- route only when inserted and `route=True`

`route` should:

- find matching agents
- record an unhandled queue item outcome when none match
- create one queue item per matching agent
- claim each queue item by starting an attempt
- execute matching attempts concurrently where current behavior requires it
- emit terminal attempt and queue item events after execution

At the end of this step, direct agent return values should no longer be the
primary state carrier. The durable event log should be.

## Step 5: Serialize Kernel Queue Items And Attempts

Construct `QueueItem` and `Attempt` values from `zeta.kernel.dispatch` when
emitting lifecycle events.

The lifecycle event payloads should be serialized from those kernel objects,
with terminal result or error fields added explicitly. Do not introduce a
second set of projection objects for queue item or attempt state in dispatch.

The durable lifecycle events remain the source of truth. If a future worker or
dashboard needs replayed state, add that read model at the observation boundary,
not in the hot dispatch path.

## Step 6: Make Interactive Turns A Built-In Agent

Represent interactive execution as an agent accepting:

```text
session.turn.requested
```

Move the one-off session dispatcher idea into dispatcher registration, not a
special helper that builds a one-agent dispatcher per run.

The interactive runner should call the existing session turn logic:

```text
session.turn.requested event
  -> QueueItem(target_agent=zeta.session.turn)
  -> Attempt
  -> SessionRunParams
  -> async_run_agent_turn
  -> Turn result
  -> terminal attempt + queue item events
```

Keep `loop.py` mostly unchanged. The loop should continue to emit draft events
through an event sink supplied by the runner.

## Step 7: Change `session.run` To Append And Observe

Change `run_rpc_session` so it:

1. validates params
2. chooses or reads `run_id`
3. appends `session.turn.requested`
4. waits for the queue item / attempt for `(event_id, zeta.session.turn)` when
   synchronous
5. maps the terminal lifecycle event to the existing JSON-RPC result
   shape

This removes the need to unwrap a direct dispatch execution result.

The request/response API can remain stable while the internal source of truth
moves to events.

## Step 8: Agent-Published Events

Add one path for agents to publish follow-up events into the same dispatcher.

The dispatcher should attach active event context:

```text
caused_by = active_event.id
session_id = active_event.session_id unless explicitly supplied
turn_id = active_event.turn_id when present
queue_item_id = active_queue_item.queue_item_id
attempt_id = active_attempt.id
```

Add a conservative hop limit to prevent self-recursive event storms.

Reject direct self-publication of the same event type from the active event
unless a concrete use case appears.

## Step 9: Clean Up Old Return-Oriented APIs

Once tests pass through the event-sourced path:

- remove obsolete session-event adapter glue
- remove per-run construction of one-off session dispatchers
- remove compatibility references to old dispatch output names
- remove direct agent result fields from dispatch outcomes
- remove any remaining compatibility references to legacy work-event names
- keep compatibility aliases only where external callers still need them

Do not preserve backward compatibility for internal APIs unless a caller still
uses them during the refactor.

## Step 10: Verification

Run targeted tests first:

```bash
uv run pytest tests/test_zeta_agent.py tests/test_zeta_agents.py tests/test_zeta_event_projection.py
```

Then run the full suite:

```bash
uv run pytest
```

Run complexity checks after non-trivial Python edits:

```bash
uvx --with radon radon cc src tests -s
```

If documentation files are updated during implementation, run:

```bash
uv run pre-commit run --all
```

## Open Decisions

- Should stream chunks be durable events or live-only notifications?
- Should unmatched events create a `runtime.queue_item.unhandled` event for
  every event, or only for events that enter a routable namespace?
- Should synchronous `session.run` wait by polling the store, subscribing to a
  bus, or awaiting the dispatch task directly while still deriving the result
  from terminal events?
- Should queue items and attempts first be event-sourced projections only, or
  should there be materialized tables later for efficient worker claiming?
