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

## Path From Here

The implementation path should stay incremental.

1. Add a JSONL event stream for the existing ask, propose, and do workflows.
2. Build the Emacs frontend against that stream.
3. Refactor terminal rendering behind the same structured event protocol.
4. Add long-lived RPC once the event schema has been exercised by two
   frontends.
5. Merge the session timeline and trace store behind a single event/object API.
6. Add subscriptions and a minimal scheduler.
7. Run the first standing agents with strict budgets and staged effects.

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
