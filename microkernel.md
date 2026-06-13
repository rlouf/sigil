# Zeta as an Agent Microkernel

Zeta should become an agent microkernel: the smallest durable substrate that
can coordinate agents, tools, frontends, and human approvals without owning the
whole product surface.

Sigil today already points in this direction. The zsh binding is one frontend.
It owns shell-shaped interaction: punctuation commands, prompt insertion,
command capture, and handoff resume. The Zeta runtime owns the model loop,
tools, prompt construction, trace objects, and run timeline. An Emacs frontend
should be able to use the same runtime without pretending to be a terminal. A
future daemon should be able to use the same runtime without pretending to be
interactive at all.

The microkernel framing makes that boundary explicit.

## The Analogy

A traditional monolithic kernel absorbs drivers, filesystems, networking,
process policy, and device-specific behavior. A microkernel keeps only the
irreducible coordination mechanisms in the kernel and moves everything else to
userland.

Zeta should make the same trade.

The kernel should not be a terminal UI, editor plugin, task manager, prompt
library, model marketplace, or coding-agent persona. Those are userland
programs. The kernel should provide the primitives that make all of those
programs interoperable, inspectable, and governable.

In operating-system terms:

- Events are interrupts and syscalls: observations and requests entering the
  system.
- The append-only log is the kernel journal: the source of truth for what
  happened.
- Trace objects are inodes with provenance: durable objects linked to what
  produced them.
- Refs are file descriptors or process handles: mutable names for otherwise
  immutable state.
- Tools are device drivers: capability-bearing interfaces to the outside
  world.
- Staged effects are permission faults: userland must acknowledge authority
  before the effect becomes real.
- Frontends are processes: zsh, Emacs, CI, and future UIs speak the same
  protocol but own their own interaction model.
- Remote tool hosts are userland drivers: they attach, register capabilities,
  receive calls, and disappear without corrupting kernel state.
- Agents are schedulable userland programs: they consume event projections and
  emit proposed or executed effects.

The analogy is useful because it keeps pressure on the boundary. If a concept
only exists because zsh needs it, it belongs in the zsh frontend. If Emacs, zsh,
and a headless daemon all need it to coordinate safely, it probably belongs in
Zeta.

## Kernel Responsibilities

The Zeta kernel should own a small set of central mechanisms.

### Append-Only Event Log

Every observed fact enters the system as an immutable event:

- user prompts
- shell commands and exit statuses
- editor selections and diagnostics
- model requests and responses
- tool calls and tool results
- staged commands and file edits
- approvals, rejections, cancellations, and resumes
- agent starts, stops, retries, budgets, and failures

The event log is the system of record. Frontends render projections of it; they
do not define truth. A frontend can crash, disappear, or be replaced without
destroying the run's history.

### Content-Addressed Object Graph

The existing prompt trace points in the right direction. Prompts, prompt
components, assistant messages, tool calls, tool results, turn records, and
future artifacts should be content-addressed objects linked by derivations.

The log says what happened. The object graph says what each durable artifact
was and why it exists.

This distinction matters. A prompt is not just a log line. It is a derived
object built from system instructions, project context, timeline events, tool
descriptors, and transforms. The object graph lets Zeta answer questions that a
flat transcript cannot:

- What exact payload did the model see?
- Which event or component caused this prompt to change?
- Which tool result justified this edit?
- Can this prompt be replayed against another model?
- Did the model fail because the prompt was wrong, or despite a good prompt?

### Refs

The kernel needs mutable names for immutable objects and event positions:

- `session/<id>/head`
- `run/<id>/head`
- `turn/<id>`
- `agent/<id>/last-run`
- `agent/<id>/task-state`
- `frontend/<id>/cursor`

Refs are the escape hatch that lets the system have continuity without making
history mutable. They are also how frontends and agents coordinate without
sharing in-memory state.

### Projection API

Agents should not hand-roll context reconstruction. The kernel should expose
projections over the event log and object graph:

- current conversation timeline
- recent shell activity
- active failure context
- project instructions
- prompt-ready context window
- task state
- pending approvals
- effects by file or command
- trace closure for audit and replay

This is where compaction belongs. Compaction is not a UI feature; it is a
projection strategy over durable history.

### Capability Boundary

The kernel should classify and mediate effects. Tools declare capabilities and
effects; workflows decide whether those effects run directly or stage for
review.

The important split is already present:

- read-only tools can run immediately
- mutating tools can stage handoffs
- direct workflows can execute approved effects
- approvals and rejections become events

This is not the same as a full sandbox. Sandboxes are useful userland or
deployment mechanisms. The kernel's job is to make authority explicit and
auditable even when the process has local permissions.

Tools should also be host-scoped. A tool named `edit` in Emacs is not the same
capability as a tool named `edit` in the daemon's local workspace. The kernel
should route by the full ownership tuple:

```text
(session_id, host_id, tool_name)
```

The model-facing name can be host-qualified, while the host sees the original
tool name. This lets Emacs expose live-buffer operations without replacing the
daemon's filesystem tools. If the host disconnects, the kernel can unregister
that host's tools and fail pending calls deterministically.

### Scheduler

The first scheduler should be deliberately small. It should dispatch agent runs
from event patterns, maintain budgets, avoid duplicate work, and record
outcomes. It does not need to become a distributed workflow engine.

A minimal event-driven loop is enough:

```text
event appended
  -> subscriptions matched
  -> work item recorded
  -> projection built
  -> run_agent_turn
  -> emitted events appended
  -> refs advanced
```

Retries, suppression, rate limits, and notification budgets should be facts in
the log, not hidden scheduler memory.

Work should be event-sourced too. A queue table can exist as an optimization,
but it must not become authority. The authoritative record is a stream of facts:

```text
runtime.work.pending
runtime.work.claimed
runtime.work.heartbeat
runtime.work.retry_scheduled
runtime.work.retry_fired
runtime.work.completed
runtime.work.failed
runtime.work.unhandled
```

After restart, pending work, claimed work, retries, and terminal outcomes should
be reconstructed from events plus lease policy. This keeps the scheduler
debuggable and makes recovery an append operation, not surgery on hidden state.

### Protocol

Zeta needs a stable frontend protocol before it can be a real kernel.

The first protocol can be JSONL:

```text
sigil step --workflow propose --jsonl "run the focused tests"
```

The next one can be a long-lived RPC process:

```text
sigil rpc
```

Frontends should receive structured events for assistant text, reasoning
summaries, tool calls, tool results, handoffs, prompt ids, ledger effects, and
errors. zsh can keep using handoff files as a compatibility layer, but files
should not be the primary kernel interface.

The durable version should be a daemon protocol, not just a subprocess mode. A
daemon gives all frontends the same long-lived authority point:

```text
zsh / Emacs / CLI / TUI / CI
        |
        v
JSON-RPC over a local socket
        |
        v
Zeta daemon
```

The protocol should expose a small set of stable methods:

- initialize and report capabilities
- create, inspect, run, detach, attach, cancel, and resume sessions
- append and list events by cursor, type prefix, session, and cause
- fetch objects, refs, derivations, and trace closures
- attach hosts and register or unregister host-owned tools
- stream live events for a session or event prefix

This lets JSONL remain a simple script-facing mode while RPC becomes the
kernel-facing contract for stateful clients.

### Session Agent And Dispatcher

There are two loops that should eventually converge.

The first is the local coding-session loop:

```text
frontend request
  -> session state
  -> context object
  -> model call
  -> tool loop
  -> session state
```

The second is the background event-dispatch loop:

```text
event appended
  -> dispatcher
  -> runtime agent
  -> tasks
  -> emitted events
```

These should not become separate kernels. The local coding session should be a
runtime-hosted agent triggered by events such as `session.turn.requested`, while
the session layer keeps owning coding-specific semantics: messages, contexts,
model outputs, tool results, session refs, and prompt construction.

The dispatcher should own orchestration: routing, lifecycle, retries,
concurrency, cancellation, backpressure, budgets, and work facts. The session
agent should own what a coding turn means.

This separation keeps the coding agent reproducible without forcing every
background agent to inherit coding-session concepts.

### Authored Agent Specs

Agent definitions should be userland artifacts, but the kernel ecosystem needs a
standard way to validate them before execution.

An authored agent spec should declare:

- which events it accepts
- which events it may emit
- which tools it may call
- whether it is one-shot or resumable
- what prompt template and resources it uses
- what structured return shape it promises

The runtime should not know about Markdown, prompt resources, or skills. A
separate loader can turn authored files into validated runtime registrations.
That keeps the kernel narrow while still making agents portable and auditable.

## Userland Responsibilities

Everything that is specific to an interaction surface belongs outside the
kernel.

The zsh frontend owns:

- punctuation glyphs
- prompt insertion
- shell history insertion
- foreground job control
- raw `+` command capture
- automatic resume after a matching handoff

The Emacs frontend should own:

- buffers and windows
- selected regions
- Magit diffs
- compilation buffers
- project roots
- buttons for staged shell commands or edits
- editor-native display of traces and approvals
- host-owned tools for live buffer reads, reviewable edit proposals, applying
  accepted hunks, and reporting unsaved user changes

A future CI or PR frontend should own:

- checkout strategy
- comments and review threads
- status checks
- branch and pull-request updates

A future TUI, if it ever exists, should own:

- layout
- keybindings
- scrollback
- themes
- terminal rendering

None of those should leak into the kernel as assumptions.

Userland can also provide hosts that are not frontends. A browser controller,
Slack connector, GitHub worker, or language-server bridge can attach as a tool
host without becoming part of the kernel. The kernel's job is to register,
route, journal, and revoke those capabilities.

## Durable Invariants

A microkernel is only useful if its invariants are stronger than its clients.
These rules are more important than any particular UI:

- Objects are immutable and content addressed.
- Refs move only by conditional compare-and-swap semantics.
- Events are append-only facts.
- Idempotency keys suppress duplicate external deliveries.
- Invalid requests are rejected before durable side effects.
- A turn has at most one terminal event.
- Terminal outcomes never transition back to non-terminal states.
- Causality links point to real prior events unless explicitly external.
- A session has at most one active mutating turn.
- Read-only inspection can run while a mutating turn is active.
- Host-owned tools are scoped to a host connection generation.
- Disconnecting a host deterministically fails pending calls owned by that
  generation.
- Repair tooling appends audit/recovery events and moves refs conditionally; it
  does not delete by default.

These are kernel rules. Frontends can have bugs, render stale views, or crash
mid-turn. They should not be able to corrupt the durable history.

## Why This Is Differentiated

Most coding agents have sessions, tool logs, traces, and some form of memory.
Zeta can be different by making the append-only event log and derivation graph
the primary substrate rather than secondary telemetry.

That produces a different kind of agent system:

- Frontend-neutral: zsh, Emacs, and daemons are peers.
- Auditable: approvals, commands, edits, and model inputs are first-class
  records.
- Replayable: prompts and traces can be reconstructed and rerun.
- Debuggable: failures can be localized to event context, prompt assembly,
  tool behavior, or model output.
- Governable: authority is represented as events and capability boundaries, not
  only as UI state.
- Long-lived: standing agents subscribe to facts instead of scraping transient
  frontend state.

The goal is not to build another terminal coding app. The goal is to build a
small local substrate where many agent-shaped applications can safely share
context, tools, and history.

That also clarifies the relationship between Sigil and a standalone Zeta
kernel. Sigil has the strong product interaction: punctuation workflows,
reviewed shell handoffs, command capture, trace UX, and ledger UX. A standalone
kernel has the stronger substrate shape: daemon protocol, event store,
content-addressed objects, remote hosts, session runtime, and dispatcher. The
long-term direction should combine those strengths rather than grow two
separate kernels.

## Path From Here

The implementation path should stay incremental.

1. Add a JSONL event stream for the existing ask, propose, and do workflows.
2. Build the Emacs frontend against that stream.
3. Refactor terminal rendering behind the same structured event protocol.
4. Add long-lived RPC once the event schema has been exercised by two
   frontends.
5. Move RPC behind a local daemon so frontends share one long-lived authority
   point.
6. Add host attach and host-owned tool registration for Emacs and future
   drivers.
7. Merge the session timeline and trace store behind a single event/object API.
8. Make local coding turns runnable as `session.turn.requested` events through
   the dispatcher/runtime stack.
9. Add subscriptions and a minimal scheduler.
10. Load authored agent specs into validated runtime registrations.
11. Run the first standing agents with strict budgets and staged effects.

The second frontend is the forcing function. Once zsh and Emacs can both drive
Zeta cleanly, the kernel boundary is real. Once the kernel boundary is real,
event-driven agents become a natural extension rather than a rewrite.

## Design Rule

The kernel test is simple:

If a frontend disappears, can Zeta still explain what happened?

If the answer is yes, the event log and trace graph are doing their job. If the
answer is no, too much state lives in userland.

Keep the kernel small. Keep history immutable. Move policy and presentation to
userland unless the system cannot remain auditable without centralizing it.
