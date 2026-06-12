# The Agent Substrate

This document describes the evolution of Zeta into an event-driven runtime,
and the extraction of the machinery underneath Sigil and Zeta into a
standalone substrate that any application can emit events into and any agent
can act on.

The shell was the first instrumented application. The user typing a prompt
was the first event type. This document generalizes both.

## Thesis

The more you interact with your machine, the more an agent can know about
what you did — provided the interactions are recorded as structured,
provenance-bearing events rather than opaque logs or screenshots.

Sigil already records shell activity into a session timeline. The prompt
trace substrate already stores every model interaction as a content-addressed
object graph with derivations and freshness. Together these form the seed of
something more general: a local, append-only nervous system for one machine,
where applications are senses, agents are reflexes, and the human is the
cortex with veto power.

Three properties separate this from telemetry, and all three must be
preserved as invariants:

1. **Local-first.** Events never leave the machine. The deal with the user
   is total recall, but only theirs.
2. **Provenance.** Every agent belief, artifact, and action is a derivation
   traceable back to the exact events that justified it.
3. **Staged effects.** Agents observe freely but act through mediated,
   reviewable channels. The existing handoff model — proposals staged into
   the user's prompt buffer — is the template, not a transitional crutch.

## Architecture Overview

Three layers, with a hard API boundary between the first and the rest:

```text
┌──────────────────────────────────────────────────────────┐
│ Frontends: sigil (shell), editor plugins, web explorer,  │
│ notification surfaces, future `sigil sh`                 │
├──────────────────────────────────────────────────────────┤
│ Runtime (zeta): agent scheduler, prompt builder,         │
│ compaction, model transport, tools, skills               │
├──────────────────────────────────────────────────────────┤
│ Substrate ("the kernel"): event log, object store, refs, │
│ derivations, freshness, subscriptions, capabilities      │
└──────────────────────────────────────────────────────────┘
```

The substrate has no opinion about models, prompts, or shells. It stores
events and objects, answers queries about them, and enforces capability
grants on effects. Everything that knows what an LLM is lives above it.

The bottom two layers exist today as the `zeta` workspace, and the agent
definition format exists as `dotagents` — a standalone project (Rust core,
Python bindings) already executing production agents in `daemons`. Where
this document and that code overlap, the document describes the shipped
design.

The operating-system analogy is load-bearing and worth keeping in view when
making design decisions:

| Substrate concept   | OS analog                  |
| ------------------- | -------------------------- |
| Event log           | Interrupts + journald      |
| Object store        | Filesystem (content-addressed) |
| Refs                | Mutable namespace          |
| Derivations         | Process accounting         |
| Freshness           | Cache invalidation         |
| Capabilities        | Permissions                |
| Agent definitions   | Programs on disk           |
| Agents              | Processes                  |
| Model endpoints     | Device drivers             |
| Tools               | Userland programs          |
| Sigil               | The shell                  |

## The Substrate

### Primitives

The substrate is the union of two things that already exist — the session
timeline and the prompt trace store — unified behind one API and one storage
layer.

**Events** are append-only, schema-tagged records: a command ran, a command
failed, a file changed, a timer fired, the user typed a prompt, an agent
proposed something, the user accepted or rejected it. Events are themselves
content-addressed objects, so the event log is a view over the object store
rather than a second database. An append carries an optional idempotency
key — a duplicate write returns the originally persisted event, not a new
one — and an optional `caused_by` link to the event that triggered it, so
causality is recorded for events themselves, not only for objects. Cursors
are the stable incremental read mechanism.

**Objects** are immutable, content-addressed records with a kind, a schema,
JSON data, and ordered links — exactly as in the prompt trace today.

**Refs** are the only mutable state: named pointers to object ids
(`session/current-task-state`, `agent/<id>/last-run`). A ref moves only
through a conditional compare-and-swap — `move_ref(name, expected_old,
new)` either observes `expected_old` and moves, or fails without mutation.
A failed CAS is normal concurrency, not corruption.

**Derivations** record how any object was produced: producer, immutable
object inputs, resolved refs, parameters. They are what make every artifact
answerable to the question "why does this exist." Object inputs and
resolved refs are distinct on purpose: an immutable input never goes stale;
only a ref moving can. A derivation is a semantic build record — it
deliberately carries no latency, retries, or worker identity; those are
operational facts and belong in the event log.

**Freshness** reports whether a derived object's resolved refs still point
where they pointed at derivation time. It is only meaningful for refs a
maintenance policy declares as kept current; an unmaintained ref reports
unknown, because the store cannot know whether it is current. Reports are
per-ref, so a consumer sees which input went stale, not merely that one
did. Built for compaction, freshness generalizes into the substrate's
reactivity primitive: *react when a ref goes stale* is the declarative form
of most ambient behavior.

**Subscriptions** register a consumer against an event pattern. Matching
starts as exact event-type subscription; schema and predicate patterns are
the growth path, and definition-level `when` clauses compile down to them
rather than being a primitive of their own.

**Capabilities** are grants attached to consumers: which effect classes
(read, propose, execute, write) they may produce, scoped by resource
patterns. The existing per-tool `analyze()` effect classification is the
seed; the substrate makes grants first-class objects so that policy itself
has provenance.

### Minimal API surface

The kernel boundary should be small enough to memorize:

```text
append_event(kind, schema, data, idempotency_key?, caused_by?) -> event id
put_object(kind, schema, data, links)                          -> object id
get_object(id)                                                 -> object
resolve_ref(name) / move_ref(name, expected_old, new)
record_derivation(producer, output, input_ids, resolved_refs, params)
check_freshness(object_id, policy)          -> freshness report
subscribe(pattern, consumer)                -> subscription id
grant / revoke / check_capability(consumer, effect, resource)
```

Everything else — prompt construction, compaction strategies, model
transport, tool execution, display — is userland and must go through this
surface. The discipline matters: a kernel extracted around a single client
fossilizes that client's assumptions. Two genuinely different consumers —
the interactive session loop and the event-dispatched agent host — already
exercise this surface; that is what hardened the signatures above.

### Storage and lifecycle

SQLite remains the right store: one substrate database per scope (session
today; likely one durable per-user store plus ephemeral session views as the
design matures). An in-memory backend exposes the same logical semantics —
tests and ephemeral scopes run against the same contract — and operations
specified as atomic are atomic in every backend. Content addressing gives
deduplication and integrity for free. Three unglamorous necessities come
with it:

- **Garbage collection.** Unreferenced objects accumulate; a `gc` walking
  from refs and pinned roots, in the git mold.
- **Redaction and forgetting.** Secrets are already redacted before storage.
  Forgetting must be a supported operation, not a violation of the model:
  deletion of an object tombstones its id so derivations remain honest about
  what existed.
- **Repair, not surgery.** Recovery tooling never deletes by default: it
  reports planned mutations before applying them, appends audit events, and
  moves refs conditionally. Destructive repair is explicit opt-in.

## Emitters

The contract is deliberately asymmetric: trivial to observe, governed to act.

Emitting should be an afternoon's work for any application: a small SDK (or
just a CLI — `sigil emit <kind> <json>`) wrapping `append_event`. Editor
plugins, build systems, git hooks, browsers, calendars, file watchers, and
timers are all emitters. The shell binding becomes the reference emitter
rather than a privileged one.

Event soup is the failure mode that kills systems like this. Mitigations,
in order of importance:

1. **Schemas are mandatory.** Every event declares a schema id; unknown
   schemas are stored but not routed to agents until described.
2. **A small core taxonomy**, curated in-repo: `command.ran`,
   `command.failed`, `file.changed`, `timer.fired`, `prompt.submitted`,
   `proposal.staged`, `proposal.resolved`, `agent.acted`. Third-party
   schemas namespace under their emitter.
3. **Distillation over accumulation.** Raw events are noise; the compaction
   layer turns streams into task-states and beliefs, freshness expires them,
   and provenance keeps every distilled belief auditable. The substrate's
   value is not that messages move but that observations become accountable
   memory.

## Agents

### Anatomy

The agent definition is its own artifact, independent of any runtime — a
program, in the table's terms, that the runtime executes but does not
define. Concretely, a Markdown file: frontmatter declares what the agent
may consume, emit, and use; the body *is* the prompt, a template rendered
against the triggering event.

```md
---
name: build-medic
description: Diagnose command failures and stage a fix.
accepts:
  - command.failed
returns:
  - proposal.staged
tools:
  - read
---
A command failed in {{ event.payload.cwd }}:

    {{ event.payload.command }} → exit {{ event.payload.exit_status }}

Diagnose the failure and stage a fix as a proposal.
```

A definition is validated at load against the host's registered
vocabularies, in both directions: `accepts` and `returns` must name known
event schemas, `tools` must name tools the host can provide, and timer
`schedules` must be a subset of `accepts`. From `returns` the loader
derives a JSON Schema constraining what the agent may emit — output is
structured by declaration, not convention. Unknown frontmatter keys are
preserved as extensions, which is how host-specific fields ride without
forking the format: notification policy, declared write paths with a
commit policy, and budgets are extension keys today, and graduate to
kernel-checked fields (`can`, `budget`) as capabilities become
first-class. Predicate guards (`when = "cwd under ~/work"`) are the other
unbuilt delta; they compile down to subscription patterns.

The format is one project with a Rust core and Python bindings, so every
frontend and runtime loads the same definition. Definitions are themselves
objects in the substrate, so the configuration of the system has the same
provenance as its behavior.

The same boundary governs prompts everywhere: prompt content — persona,
policy, workflow instructions — belongs to the definition, which is to say
to userland; the runtime owns assembly only — the tool protocol, tool
descriptors, transcript splicing, compaction. The test for any line of
prompt text: if it changes when the product changes, it lives in a
definition; if it changes when the runtime changes, it lives in the prompt
builder. A runtime with a default persona is the kernel hardcoding what its
programs say.

### Authoring tiers

1. **Declarative** — the definition above; no code. This tier is shipped
   and cross-language.
2. **Natural language** — the user tells Sigil what they want
   (`,watch "warn me if anything writes to the prod config"`) and an agent
   authors the definition, staged for review like any other proposal. The
   agent that writes agents — targeting a format that already exists, not
   one invented for the purpose.
3. **Code** — the existing plugin contract, for the rare case that needs it.

### Replay as test harness

Months of recorded events make a dry-run harness nearly free, and it should
be the default authoring experience: run a candidate definition against the
stored event history and show every occasion it would have fired and what it
would have proposed. No cloud automation platform can offer this; here it
falls out of the substrate.

### Capability progression

New agents are born propose-only. Direct effects are granted, per resource
pattern, by the user — ideally informed by the agent's track record in the
review queue. Grants and revocations are events, so trust itself has a
history.

### Execution model

A long-lived daemon (`zetad`, the second userland citizen the kernel needs)
owns the loop:

```text
event appended
  -> match subscriptions
  -> work item recorded as a fact, keyed (triggering event, agent)
  -> claim appended conditionally at the expected stream version
  -> run_agent_turn with substrate-backed context
  -> analyze() effects locally before any execution
  -> capability check
  -> direct effects execute; everything else is staged as a proposal
  -> leases, retries, and outcomes appended as facts
```

Work is event-sourced, not queued: a work item is a fact derived from the
ledger, claims are conditional appends, leases ride on claim and heartbeat
events, and retries transition by facts. An event no agent accepts is
recorded as unhandled rather than dropped. After a crash, pending, claimed,
and terminal work are rebuilt by replaying work events plus lease policy —
projections may cache status for inspection, but the appended event is
always the authority. Budgets and concurrency are enforced at claim time.

The existing headless `run_agent_turn` already has the right shape — pure
over config, no session mutation — and becomes the daemon's worker. The CLI
remains a thin client that appends a `prompt.submitted` event and renders
the response; interactive and ambient use share one code path.

## Userland: Authoring, Monitoring, Exploring

The substrate makes each of the three necessary surfaces a thin view rather
than a product of its own.

**Monitoring** is `ps`/`journalctl` over the ledger:

- `sigil agents` — what is subscribed, what fired, what it did, what it
  cost. Tokens and wall-time are the CPU-seconds of this system; budgets
  are enforced per agent so a misbehaving one degrades instead of consuming
  the machine.
- A review queue of pending proposals, each expandable into full provenance.
- Quality telemetry for free: rejection rates per agent surface drift; an
  agent firing far above its baseline is an anomaly worth a notification.
- Attention is the resource this system exists to refund, so notification
  budgets are first-class per-agent settings, not an afterthought.
- Pause and kill are signals; agent lifecycle changes are events.

**Exploration** is a browser over the object graph. The one interaction
that matters most is the **why button**: select any artifact — a summary, a
proposed command, a belief inside a task-state — and walk its derivations
back to the raw events that justified it. Around that core: a timeline view,
structural diffs between any two objects (two prompts, two task-states, an
agent before and after a model swap), local semantic search over the store,
pinning, and `gc`. TUI first; a local web UI as graphs grow.

## What This Enables

Use cases, roughly ordered by expected impact on a working day. Each is a
corollary of the substrate rather than a feature needing new machinery.

**Zero cold-start context.** A standing agent keeps a compacted task-state
continuously fresh as events arrive; freshness recomputes only what went
stale. When the user finally asks something, the model already knows the
situation. The latency of understanding drops to zero.

**Recovery from interruption.** The timeline already knows where the user
was; a standing "where you were" object — goal, last action, next intended
step — turns returning from a meeting into ten seconds instead of twenty
minutes.

**The shell that debugs itself.** A non-zero exit is an event. An agent
investigates in the background using the existing failure-context machinery,
and a diagnosis plus staged fix are waiting in the prompt buffer before the
user has re-read the stack trace. Failure itself is the prompt.

**Watchpoints and the pre-exec guardian.** Natural-language tripwires
compiled into checks over the event stream; and a millisecond local-model
pass over `analyze()` effects plus recent context before destructive
commands run ("that `rm -rf` path is your active project, not the build
directory"). Cheap local inference makes per-command checks affordable in a
way API calls never were.

**Automation that proposes itself.** The timeline is provenance of actual
habits. When the same five-command sequence recurs, an agent drafts the
script or skill and offers it; `skills` is the landing spot. The noticing is
delegated; the deciding stays human.

**A babysitter for long-running work.** Build, training, and download
output streams are events. An agent notifies on genuine anomalies rather
than completion, retries failure classes it recognizes, and compresses hours
of logs into a paragraph in which every claim links to the log objects
behind it.

**The day, written down by itself.** Standup notes and "where did Tuesday
go," distilled from the ledger on a timer event, with each statement
traceable to real events rather than reconstructed from memory.

**Tool-call memoization.** A derivation is producer + inputs → output —
the same structure build systems use for caching. Same tool, same arguments,
refs still fresh: reuse the stored result. Nix-style caching for agent work.

**Prompt bisect and personal evals.** Stored prompts are exact payloads
with derivations, so a session can be replayed against a different model or
system prompt and diffed structurally. Regression-test a new local model
against one's own traces — the real workload — entirely offline.

**Session forking.** Content addressing makes branching free: fork a
session at any point, run two approaches or two models, diff the resulting
graphs, keep the winner. Shared history deduplicates automatically.

**Executable runbooks.** A debugged incident is a portable artifact:
exactly what was checked, in what order, with what output — and freshness
reports which parts do not hold in the reader's environment. Postmortems
with verifiable provenance; onboarding as "replay how I actually fixed it."

**Auditable delegation.** Ambient agents handling cert expiry, disk
pressure, and failing backups, where every autonomous action is a
hash-addressed, traversable, tamper-evident record. The morning review of
"what did my agents do overnight" is what makes unattended operation
acceptable.

The compounding effect is the point: every emitter added and every
interaction recorded makes every agent more useful, and the accumulated
understanding belongs to the user as local objects, not to a vendor.

## What Needs to Be Built

Sequenced so each phase ships something usable and each later phase has two
real consumers of the layer below it.

**Phase 1 — Unify and extract the substrate.**
Merge the session timeline and the prompt trace store behind the kernel API
above; route all existing reads and writes in Zeta and Sigil through it.
Add subscriptions and capability records to the schema. No behavior change;
this phase is done when `grep -r sqlite3 src/` matches only the substrate.

**Phase 2 — The daemon.**
A long-lived `zetad` owning subscriptions, budgets, and the event-sourced
work loop; the CLI becomes a client that emits `prompt.submitted` and
renders. The dispatch machinery exists; this phase is the durable host
process around it.

**Phase 3 — Emitters.**
The `emit` CLI and a minimal SDK; the core event taxonomy; conversion of the
zsh binding into the reference emitter. One non-shell emitter (a file
watcher or git hook) to prove the contract.

**Phase 4 — Agent definitions and capabilities.**
The definition format is shipped; this phase adds the propose-only default,
capability grants as objects, budget enforcement, and the review queue. The
first shipped standing agents:
the failure medic and the task-state maintainer, because they exercise
observation, compaction, and proposal end to end.

**Phase 5 — Replay harness.**
Dry-run definitions against stored history; surface "would have fired" results
in authoring. Doubles as the regression harness for prompt and model
changes.

**Phase 6 — Monitoring and exploration surfaces.**
`sigil agents`, notification budgets, anomaly heuristics; the artifact
explorer with the why button, diffs, search, pinning, and `gc`.

**Phase 7 — Natural-language authoring.**
The agent that writes agents, staging definitions for review. Deliberately
last: it is leverage on top of every prior phase and meaningless before
them.

## Non-Goals (for this document)

- **Network distribution.** Remote execution, session sync across machines,
  and any cloud component are out of scope here. The substrate's content
  addressing was chosen partly because it will extend to replication
  cleanly, but nothing in this document depends on a network.
- **Hosted models.** The design assumes a local OpenAI-compatible endpoint
  throughout; per-event inference is only economical locally.
- **A plugin marketplace.** Schemas and agent definitions are designed to be
  shareable files; distribution mechanisms come later, if ever.

## Open Questions

- **Retention.** What `gc` keeps by default, how long raw events live
  versus their distillations, and what "forget this" tombstones.
- **Schema governance.** How third-party schemas are described well enough
  for agents to consume them without a central registry.
- **Daemon lifecycle.** launchd/systemd integration, and what happens to
  subscriptions when the daemon was down while events accrued. (Crash
  recovery itself is settled: replay of work and turn events plus lease
  policy.)
- **The attention model.** Per-agent notification budgets are necessary
  but not obviously sufficient; a global "interruption budget" across all
  agents may be the right primitive.

## Summary

Sigil was the wedge; Zeta was the runtime; the substrate underneath them is
the product. Extracting it and making the user prompt one event type among
many turns a shell assistant into a local, provenance-bearing nervous
system: applications emit, agents subscribe and act through staged and
capability-checked effects, and every artifact answers "why do you exist"
with a graph traversal. The userland that follows — authoring by replay,
monitoring as a ledger query, exploration as a why button — falls out of
the kernel rather than being built beside it. That is the test of the
abstraction, and so far it keeps passing.
