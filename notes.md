# Sigil notes

The core is hardened and the delegation ledger is queryable end to end:
Stages 1–3 are landed (turn/effect records, the SQLite index + trace-graph
bridge, and the query surface — `sigil log`, `blame`, `log show`, `?` v2
with the model line, and the `query_log` ask tool). The trace explorer has
its plumbing and porcelain (Stages A–B: forward index, resolver,
`trace log|show|tree`). The bottom-up improvement walk is merged. What
remains: web tools (proposal below), explorer Stages C–D (diff/replay,
cross-session scope), ledger Stage 4 (durable/global/portable), and two
small unblocked fixes.

## Decisions in force

- **Trust model: local user, local trust.** `,,,` is YOLO mode — nothing
  staged, no filesystem boundary — documented in the README with OS
  sandbox pointers (bubblewrap, sandbox-exec) for anyone who wants an
  enforced boundary. A cwd workspace boundary for write/edit (direct
  inside, staged handoff outside) stays available as a post-alpha option:
  both execution paths and the per-call dispatch point exist, but bash
  cannot honestly participate (its touched paths are statically
  undecidable) and the boundary forces a `,,`/`,,,` semantics decision.
- **Staging is a property of the tool contract.** `ToolSpec.effects`
  declares what each tool does, plugins included; undeclared effects
  count as mutating, and a mutating tool without a staging implementation
  is refused in propose mode. The ledger's effect records map `kind`
  straight from this vocabulary.
- **Recording: commands and exit codes, always.** Always-on shell
  recording is in place; the capture window is gone.
- **`session clear`: continuity dies, ledger survives.** Clear removes
  the session dir (trace store, bridged turn objects, `turn/` refs);
  `ledger.sqlite3` and `events.jsonl` are global and untouched.
- **Prompts carry the date, never the time.** `Today is YYYY-MM-DD
  (Weekday).` in every workflow's system prompt; a finer stamp would
  defeat the content-addressed component dedup.
- **Prompt content lives in the workflow layer; the runtime assembles.**
  `STEP_SYSTEM_PROMPT` (`workflows/step.py`, shared by do/propose) and
  `ASK_SYSTEM_PROMPT` (`workflows/ask.py`) own the personas;
  `zeta/prompt/system.py` renders scaffolding only — date line, tool
  protocol, skills, descriptors — and invents no content
  (`system_prompt()` with no base is assembly-only). Mirrors the
  roadmap's definition-as-artifact boundary: content changes with the
  product, assembly with the runtime. Step-path prompt bytes are
  unchanged — the same text is now passed explicitly, so trace
  components keep deduplicating.
- **Test infra:** coverage is measured in CI report-only (86%); a
  fail-under gate waits until the number stabilizes. The two patching
  idioms (`_patch.py` vs raw `monkeypatch`) coexist deliberately —
  converging ~145 call sites is churn without payoff.

## Deliberate non-fixes

- `summarize.count_lines` duplicates `structural_trim.line_count`;
  neither module is a natural home for both, so the 3-line function
  stays twice rather than coupling display to compaction.

---

# Proposal: Sigil tool contracts and reviewable writes

Direction: tools are Sigil capabilities, not Zeta internals. Zeta is one
orchestrator over them.

## Boundary

- **`sigil.tools` owns executable capabilities:** implementations,
  CLI behavior, validation, effects, mutation semantics, JSON result
  shape, and eventually staging/review mechanics.
- **`sigil.zeta` owns model-facing exposure:** `ToolSpec` (or
  `ZetaToolSpec`), JSON Schema for model calls, descriptor rendering,
  prompt wording, and model-call validation.
- Zeta can adapt Sigil tools into model tools, but the executable
  contract must also be callable as a CLI.
- The invariant: Zeta never has a tool schema that the CLI cannot
  validate and run.

This likely means moving executable tool modules out of
`src/sigil/zeta/tools/` over time into `src/sigil/tools/`, while keeping
the model-facing `ToolSpec` model under `sigil.zeta`.

## Contract surfaces

Each tool should expose the same four surfaces:

```sh
sigil tool metadata write
sigil tool schema write
sigil tool validate write --stdin
sigil tool run write --stdin
```

`validate` and `run` read JSON params from stdin or a params file. A
generic JSON-param interface is the first stable layer because tools and
plugins are dynamic:

```sh
echo '{"path":"x.txt","content":"hi"}' | sigil tool validate write
echo '{"path":"x.txt","content":"hi"}' | sigil tool run write
```

Friendly per-tool porcelain can come later, but the source of truth is
the contract-backed JSON path.

## Enforcing CLI options

Use one shared tool contract so the CLI and Zeta schema cannot drift:

- The contract defines args/options, required fields, defaults,
  effects, interactivity, description, and result expectations.
- CLI parsing is generated from or checked against the contract.
- Zeta JSON Schema is generated from or checked against the same
  contract.
- Runtime validation uses the same contract before execution.

Before a staged-write flag exists, both of these should fail:

```sh
sigil tool run write --staged ...
```

and any model call with a `staged` field. Later, adding staged writes is
one contract change, not separate CLI and Zeta changes.

## CLI adapter first, not a rewrite

Current code already has the right internal split: `ToolSpec`,
`analyze`, `run`, `stage`, `run_tool`, and CLI-backed plugins. First
implementation should add a CLI adapter over the existing registry:

```sh
sigil tool list
sigil tool metadata read
sigil tool schema read
sigil tool analyze write --json-params '{"path":"x.txt","content":"hi"}'
sigil tool validate write --json-params '{"path":"x.txt","content":"hi"}'
sigil tool run write --json-params '{"path":"x.txt","content":"hi"}'
```

For now, no `--staged`: `run` means direct execution, equivalent to the
auto-approved `,,,` workflow. Zeta can continue to call tools
in-process for speed as long as both paths share the same adapter/core
behavior. A hard subprocess boundary can come later.

## Built-ins as plugin-compatible CLIs

Expose built-ins with the same protocol expected from external tools:

```sh
sigil tool serve write --metadata
sigil tool serve write --schema
sigil tool serve write --validate   # JSON params on stdin
sigil tool serve write              # run JSON params on stdin
```

Then a built-in can be registered elsewhere as:

```toml
[[tools]]
kind = "command"
command = ["sigil", "tool", "serve", "write"]
```

This keeps the command-tool protocol real and testable.

## Python-library tools

Support in-process tool registration alongside binary tools.

TOML examples:

```toml
[[tools]]
kind = "command"
command = ["my-tool"]

[[tools]]
kind = "python"
module = "my_package.sigil_tools"
object = "TOOLS"
```

Installed packages can also expose entry points:

```toml
[project.entry-points."sigil.tools"]
my_package = "my_package.sigil_tools:sigil_tools"
```

The loaded object can be a list of contracts or a factory:

```python
TOOLS = [FETCH_ISSUE]

def sigil_tools():
    return [FETCH_ISSUE]
```

Python tools are trusted in-process code. Command tools run
out-of-process with timeout/stderr capture. Zeta should not care about
origin; it sees registered contracts.

## Reviewable writes outside Git

The write/edit mutation primitive should eventually own staging. That
keeps behavior consistent for CLI use, Zeta, plugins, and non-Git
directories.

Future invariant:

```text
No staged write mutates the real workspace.
Only staged apply mutates the real workspace.
```

Use three trees for proposal review:

- `base`: snapshot before agent edits
- `proposal`: agent-edited tree
- `accepted`: what will be applied to the real workspace

Diff generation does not require a Git repo:

```sh
git diff --no-index --color=always base/ proposal/
```

Pipe to `delta` when installed; otherwise fall back to colored diff or
plain unified diff.

## Review flow for non-Git dirs

The review flow should not require the real project to be a Git repo.
It should present the diff between `base` and `proposal`, let users
accept or reject changes into `accepted`, then apply only `accepted` to
the real workspace.

The useful unit is the proposal batch, not each write call. Let the
model finish a coherent proposal batch, then review the whole patch
once.

---

# Plan: move concrete tool implementations out of Zeta

Decision: keep the model-facing tool protocol in `sigil.zeta`, but move
the concrete built-in tool implementations to `sigil.tools`.

## Observations

- `src/sigil/zeta/tools/` currently mixes two concerns:
  - Zeta/runtime concerns: `ToolSpec`, `ToolImpl`, effect metadata,
    argument validation, registry state, model-facing metadata.
  - Sigil capability implementations: `bash`, `read`, `write`, `edit`,
    `grep`, `ls`, `query_log`, and CLI plugin loading.
- The implementations touch Sigil-owned surfaces: shell execution,
  filesystem reads/writes, handoff protocol, ledger, state, display
  formatting, and user config.
- The registry and protocol are still naturally Zeta-owned because they
  describe what the model can call and how calls are validated/dispatched.
- Tests currently import implementations from `sigil.zeta.tools`, so the
  move needs test updates at the same time.

## Target boundary

- Keep in `sigil.zeta.tools`:
  - `base.py` with `ToolSpec`, `ToolImpl`, effect kinds, diagnostics,
    and common result helpers that are part of the model-call protocol.
  - the registry/dispatcher in `__init__.py`: built-in registration,
    plugin registration, schema validation, argument validation, and
    direct/handoff dispatch.
- Move to `sigil.tools`:
  - concrete built-ins: `bash.py`, `read.py`, `write.py`, `edit.py`,
    `grep.py`, `ls.py`, `query_log.py`.
  - command-backed plugin implementation if it remains a Sigil feature
    rather than generic Zeta infrastructure.
- The direction of dependency should be:
  - `sigil.tools.*` imports protocol helpers from `sigil.zeta.tools.base`.
  - `sigil.zeta.tools` imports concrete tools from `sigil.tools` only at
    registry assembly time.
  - `sigil.zeta` runtime code continues to talk to the registry, not to
    individual implementations.

## Step-by-step implementation

1. Add/prepare `src/sigil/tools/` by moving the concrete tool modules
   there. Keep file contents as unchanged as possible, adjusting only
   relative imports.
2. Update `sigil.zeta.tools.__init__` so it imports built-ins from
   `sigil.tools` and continues to expose the same registry functions.
3. Update tests that import individual built-ins to use `sigil.tools.*`.
   Keep tests that exercise registry behavior on `sigil.zeta.tools`.
4. Run focused tests first:

```sh
uv run pytest tests/test_zeta_tools.py tests/test_zeta_agent.py tests/test_zeta_trace.py
```

5. Run the full suite:

```sh
uv run pytest
```

6. Because this plan updates `notes.md`, run pre-commit after code and
   docs are settled:

```sh
uv run pre-commit run --all-files
```

## Risks to watch

- Relative imports in moved modules, especially `query_log`, which
  lazily imports `display`, `ledger`, and `state`.
- Plugin loader placement: if command-backed plugins are part of the
  registry contract, leave `plugins.py` in Zeta; if they are Sigil
  capability discovery, move it with the concrete tools. My current
  preference is to move it to `sigil.tools.plugins` because it reads
  `~/.zeta/tools.toml` and constructs executable tool implementations,
  while the registry only consumes the loaded implementations.
- Public import compatibility is not required unless Remi asks for it.

## Future staged write shape

Potential commands:

```sh
sigil tool run write --staged ...
sigil staged diff
sigil staged review
sigil staged apply
sigil staged discard
```

But `--staged` should be an enforced tool/runtime mode, not merely a
prompt convention. In `,,`, the runner should force mutating tools into
staged/proposal mode by construction; prompts can describe that mode but
must not be the safety mechanism.

---

# Next: explorer Stage C — implementation plan (in worktree
# `trace-explorer-stage-c`)

`trace diff` and `trace replay`, made concrete against the landed
Stage A/B code and `docs/zeta-prompt-trace.md` (which promises both).

Implemented, merged (3dfe676 + af247e4), and graduated live: replaying
the real fd81e241 prompt against the local endpoint reported
`payload verified` — the rebuilt request hashes to the recorded
payload — and `tree --down` shows the `SigilModelReplay:v1` answers
next to the original. The live run exposed one rendering gap, fixed in
af247e4: tool-call-only answers now render as `→ bash` instead of
nothing. A worked walkthrough with the real transcript lives in
`docs/demos/trace-replay.md` (linked from the README). One caveat
observed on the real store: when many components of the same kind
change, kind-ordered diff pairing is positional — exact for the
same-objective regression-hunt case the roadmap targets, approximate
for prompts far apart in a conversation.

## Observations

- The doc's reconstruction claim holds in code: a prompt object's links
  are the components in message order; message components carry
  `data["message"]`; the tool descriptors ride in the
  `tool_descriptor_set` component's `data["tools"]`; `tool_choice`
  ("auto") and the body constants (temperature, stream options) live in
  `chat_completion_request_body`; `max_tokens` and `selected_model` are
  in the prompt's `SigilPromptBuilder:v1` derivation params. So the
  exact request payload is rebuildable and `data["payload_sha256"]`
  verifies the rebuild.
- The original answer is one forward query away:
  `derivations_for_input(prompt_id)` filtered to
  `SigilModelResponse:v1` yields the assistant_message object(s),
  ordered by `created_at` (latest wins when retries exist).
- Content addressing makes the diff set algebra: identical component
  id = unchanged; ids only in A = removed; only in B = added; a
  removed/added pair of the same kind is a change worth a text diff of
  the two `data["message"]` contents.
- Replays must be traced like everything else: a new
  `assistant_message` object linked to the prompt plus a
  `SigilModelReplay:v1` derivation — `trace tree --down` from the
  prompt then shows original and replay side by side.

## Decisions (mine, flag if wrong)

1. **Reconstruction lives in `zeta/prompt/builder.py`** —
   `reconstructed_prompt_request(store, prompt_id)` returning messages,
   tools, max_tokens, selected_model, and a `payload_verified` bool;
   exported through `zeta.prompt`. The CLI consumes it; replay never
   re-renders components by hand.
2. **`trace diff A B`**: component-level by id; removed/added pairs of
   the same kind render as changed with a unified text diff of their
   message contents; `--stat` keeps the one-line-per-component view and
   suppresses text diffs. Non-prompt arguments are a ClickException.
3. **`trace replay ID [--model PROFILE] [--diff]`**: model = the named
   profile (via `resolve_model_profile`), else the session's active
   selection, else env defaults; the request reuses the original
   max_tokens. Prints the hash-verification status, the original
   answer, the replay answer (or a unified diff with `--diff`), and the
   new object's short id. The replay is recorded fail-open like other
   trace writes.
4. **Plain text, no rich** — Stage B's convention; tests monkeypatch
   `chat_completion_messages`, no network.

## Work items (each: tests → impl → docs → pre-commit)

1. Builder reconstruction + payload verification (round-trip test
   against a real `PreparedPrompt`; tampered component → not verified).
2. `cli/trace.py`: `trace diff` (+ `--stat`).
3. `cli/trace.py`: `trace replay` (+ `--model`, `--diff`), recording the
   replay derivation.
4. README trace section + one-line help; `docs/zeta-prompt-trace.md`
   gains the "exists now" sentence for diff/replay.

---

# Proposal: web tools (web_search, web_fetch)

Give zeta eyes beyond the filesystem: `web_fetch` retrieves one URL as
text; `web_search` queries a search backend and returns ranked results
(title, URL, snippet) for `web_fetch` to follow.

## Observations

- The tool architecture absorbs this cleanly: one module per tool in
  `zeta/tools/` exporting `SCHEMA`, `SPEC`, `analyze`, `run`; one
  registration line in `BUILTIN_TOOL_IMPLS`. Validation, descriptors,
  the propose-mode contract, and registry plumbing are all generic.
- Both tools are read-only in the effects vocabulary (`read`/`search` ∈
  `READ_ONLY_EFFECT_KINDS`), so they run unstaged in every workflow —
  including ask — with no staging implementation needed. `mutates()`
  returns False; the contract machinery needs no change.
- The `Resource` literal in `tools/base.py` is `path|process|session` —
  no network member. Nothing validates it beyond the type hint
  (`protocols.py` never mentions resource), so adding `"url"` is a
  one-line honest extension; effect targets become the URL/query.
  Ledger tie-in for free: once effects land in `sigil.effect.v1`, "what
  it fetched" joins "what it saw".
- HTTP precedent is stdlib: `model.py` uses `urllib.request`, and the
  dependency list (click, jinja2, jsonschema, rich) is deliberately
  minimal. Both tools can be stdlib-only.
- There is no provider-side search to lean on: the model boundary is a
  bare OpenAI-compatible chat endpoint (llama.cpp on localhost by
  default). Search must be an HTTP call sigil makes itself, against
  some backend.
- Conventions to follow: result shape `{ok, content: [{type: "text",
  text}], metadata}`, ~12k char cap with `truncated`/`max_chars`
  metadata (grep), binary rejection (read), per-tool one-liners in
  `display/summarize.py` (dispatches on tool name), indicative
  `test_zeta_tool_*` tests in `test_zeta_tools.py` with monkeypatch —
  no network in tests.

## Contract decisions

1. **Builtin, not plugin.** General-purpose, wants the truncation
   conventions, summarize entries, and tests; the plugin path is for
   user-specific tooling.
2. **Stdlib HTTP, stdlib HTML.** `urllib.request` with a hard timeout
   (~15s), bounded read (cap bytes before decoding), http/https schemes
   only. Hosted providers are plain JSON over HTTPS — no SDK
   dependency. The floor for unproxied fetches: HTML→text via a small
   `html.parser` extractor (drop script/style, collapse whitespace);
   non-HTML text passes through; binary content-type is an error.
3. **One provider seam backs both tools.** Not a per-tool backend: a
   configured *web provider* exposes `search(query, objective, limit)`
   and optionally `extract(url)`; chosen by config/env, never by the
   model. Tool schemas stay provider-neutral (`web_search`: `query`,
   optional `objective` + `limit`; keyword-only backends ignore
   `objective`). web_fetch routes through the provider's extract when
   it has one, the urllib floor otherwise — so fetch always works,
   even unconfigured. Unconfigured web_search returns an error_result
   that says exactly what to set.
   - **Parallel (proposed v1 provider).** Search API: objective +
     queries → LLM-ready compressed excerpts in one round trip.
     Extract API: URL → markdown, handles JS-rendered pages and PDFs.
     They map onto web_search/web_fetch one-to-one. `PARALLEL_API_KEY`;
     ~$5/1k searches, free tier ~16k requests. The decisive argument
     for sigil: the default model is small and local — the multi-hop
     browse loop (search → pick → fetch → extract → repeat) is what it
     is worst at, and every hop is a model step; dense excerpts
     collapse the loop. SearXNG-scrape + naive extraction pushes
     quality onto the weakest component of the system.
   - **SearXNG (keyless, self-hosted, later or alongside).**
     `SIGIL_SEARXNG_URL`, JSON API, search only (fetch uses the urllib
     floor). Keeps a no-third-party option alive for the local-first
     posture.
4. **Network egress is a documented posture change.** Today `,` with a
   local model means nothing leaves the machine. Web tools break that:
   the agent can make outbound requests shaped by your prompt and files
   (prompt-injection exfiltration is the classic failure), and a hosted
   provider additionally sees every query and model-written objective —
   sharper than SearXNG, which is a box you run. Same answer as
   recording: stated contract, README section, opt-out — not silence.

## Work items (each step: tests → impl → docs → pre-commit)

1. `tools/base.py`: add `"url"` to `Resource`.
2. Provider seam: `zeta/tools/web.py` (or similar) — provider
   selection from config/env, the Parallel provider (search + extract,
   urllib JSON calls), and the urllib/`html.parser` fetch floor; tests
   with monkeypatched openers, no network.
3. `web_fetch`: `zeta/tools/web_fetch.py` (SCHEMA/SPEC/analyze/run,
   effects `("read",)`, target = URL); provider extract when
   configured, floor otherwise; tests (success, provider routing,
   redirect → final_url metadata, timeout, non-http scheme, binary
   content-type, truncation); register in `BUILTIN_TOOL_IMPLS`;
   `summarize.py` one-liner; README tool list.
4. `web_search`: `zeta/tools/web_search.py` over the seam; tests with
   a fake provider response (excerpts render as numbered
   title/URL/excerpt text, limit honored, unconfigured → instructive
   error, provider HTTP failure → error_result); register; summarize;
   README.
5. Enablement: add both to `ASK_TOOLS` (pending open question 2) and
   document the egress contract in the README.

## Open questions for Remi

1. v1 provider: Parallel only (proposal — covers both tools, free
   tier for the alpha), SearXNG only (no third party, no key), or
   both from the start? Exa/Tavily/Brave are same-shaped providers
   addable behind the seam whenever.
2. Default-on in ask (`,`), or opt-in via `--tools`/config? Proposal:
   default-on with the README contract plus a `SIGIL_WEB=0`-style
   opt-out — discoverability beats purity here, and the trust model is
   already local-user-local-trust.
3. web_fetch address policy: allow any http/https target (local trust,
   proposal), or refuse loopback/private ranges to blunt
   injection-driven probing of local services?
4. When web_search is unconfigured, is the tool still advertised to the
   model (proposal: yes, error teaches the user to configure it) or
   hidden from the descriptor list (no wasted model step)?

---

# Include reasoning in session transcript (done)

Landed as eae7f78 (thinking on by default, `[[models]]` effort config),
bf5c583 (reasoning as plain italic text, dim user-panel scaffolding),
6b11d93 (cwd-relative paths in tool summaries). Verified live against
llama.cpp + Qwen3.6.

The model captures `reasoning_content` from the stream
(`ChatStreamAccumulator.reasoning_content`), but
`assistant_message_event()` in `zeta/agent.py` drops it — only `content`
and `tool_calls` land in the event. The transcript renderer
(`transcript_assistant_block`) never sees it.

**Plan:** carry `reasoning_content` through the event and render it in
`session transcript`.

- `assistant_message_event()`: when the assistant response has
  `reasoning_content`, store it as `event["reasoning"]`.
- `transcript_assistant_block()`: if the event has reasoning, render it
  before the main content in a separate color and italic (Remi). The
  display layer themes through named ANSI colors that the terminal's
  Rose Pine theme maps onto the palette (magenta = sigil, cyan = you,
  yellow = aborted), so reasoning takes the unused `blue` (Rose Pine
  foam). Rendered as plain `Text(reasoning, style="italic blue")`, no
  Panel (Remi): panels denote messages, plain lines denote process —
  reasoning sits with tool calls, not with answers. The pager in
  `session transcript` makes it navigable.
- Live loop: do not render reasoning inline. `render_transcript` is
  consumed only by `session transcript` (`cli/session.py`), so the live
  loop is untouched by construction; the `ThinkingStatus` timer is
  enough.

This gives users who want to inspect the model's reasoning a scrollable
record without polluting the interactive experience.

**Round-trip fix (found live):** the first cut only changed the event
and the renderer; `sigil session transcript` still showed nothing
because `current_timeline()` projects events back from trace objects
and the projection rebuilt assistant events from `content`/`tool_calls`
only. Reasoning now follows the same dedup path as content: the
assistant object's `message` (which already stores `reasoning_content`)
is the single copy, `stored_event_payload` drops the inline `reasoning`
from the run event, and both projection paths
(`assistant_event_from_object` via `chat_message_event`, and
`rehydrated_assistant_event`) restore it as `event["reasoning"]`. The
model-facing conversion (`event_chat_message`) never carries it, so
prior-turn reasoning is not resent to the model.

**Thinking on by default (Remi):** the transcript pipeline was correct
but starved — `chat_completion_request_body` hardcoded
`chat_template_kwargs: {"enable_thinking": false}` into every request,
so the model (llama.cpp + Qwen3.6, which emits `reasoning_content` in
both streaming and non-streaming — verified by probe) never produced
reasoning to record. Decision: thinking is on by default and
configurable per `[[models]]` profile with the Responses API
reasoning-effort vocabulary — `thinking = "none" | "minimal" | "low" |
"medium" | "high"`; omitted means the model's own default. `"none"`
maps to `chat_template_kwargs: {enable_thinking: false}`, an effort
level is sent as `reasoning_effort`. The value
rides `ModelSelection` → `AgentConfig` → request body, and joins
`max_tokens`/`selected_model` in the prompt builder derivation params
so replay reconstruction stays exact; a prompt recorded without the
param predates the change and rebuilds with thinking disabled, keeping
`payload_verified` true on existing stores.

**Objective label removed (Remi):** `zeta_context_message` no longer
prefixes the user objective with `Objective:`; the message is now the
objective followed by the `cwd:` section. `agent_prompt` in
`workflows/step.py` still says `Objective: {objective}` inside the step
instruction — left alone, that file is mid-refactor (fold ask into
step).

---

# Proposal: fold ask into step

Make `ask.py` a thin wrapper like `do.py`/`propose.py` (35 lines each vs
ask's 576). The turn-loop duplication is a refactor; the rest is three
product decisions.

## Observations

- Where ask.py's 576 lines go: entry preprocessing (~60 —
  `ask_requested` event, skill expansion, `prepend_recent_turns`),
  the `run_tool_ask` turn loop (~120 — a near-duplicate of
  `run_agent_step`'s orchestration), `AskEventRecorder` (~45),
  fallback machinery (~190 — `fallback_*`,
  `run_fallback_answer_with_status`, `StreamDeltaTracker`),
  `record_answer` (~90 — the `answer` event, `--json` printing, the
  final-render dance).
- The orchestration skeleton is identical in both loops: server check
  → renderer → ledger → user event → `run_agent_turn` → replay →
  abort/finish. Variation points are already clean: both recorders
  subclass `TurnEventRecorder`; the outcome mapping converges for free
  (ask's read-only tools never produce effects, so step's `EXECUTED if
  ledger.effect_ids else ANSWERED` yields ANSWERED for ask).
- Behavior divergence on no-final-text: step prints "stopped without a
  final answer", records FAILED, exits 1; ask answers anyway via a
  one-shot `chat_text` over a hand-built evidence digest and exits 0.
  This exists because small local models stall — arguably every
  workflow deserves the recovery, not just ask.
- Inconsistency found: ask records the raw `ASK_SYSTEM_PROMPT` in its
  user event (`ask.py:161`) while step records the assembled prompt
  via `system_prompt(...)` (`step.py:114`). Folding fixes it for free.
- The `answer` event and `last-tools.jsonl` predate the ledger; their
  consumers are `sigil events` rendering (`cli/events.py:126`) and the
  session-dir cleanup list. Post ledger Stages 1–3 the turn record
  already answers "what did ask answer".
- `--json` threads through renderer, recorder, thinking status, and
  output; step has no JSON mode today.

## Options

1. **Extract the shared loop only (no behavior change).** One core in
   `step.py` with a recorder hook, outcome mapping, and a
   no-final-text policy; ask keeps fallback, `--json`, and
   `record_answer`. Kills the 120-line duplicate; ask.py lands ~350
   lines. A day-ish; 451 existing tests pin both paths.
2. **Converge behavior, then fold (the route to a 35-line ask.py).**
   Move the remaining features into step or retire them, per the open
   questions below. 2–3 sessions; touches the `events` vocabulary.

Proposal: 2, staged — extract the loop first (option 1 is its first
commit), then land each product decision separately.

## Closed (Remi, 2026-06-11)

1. **Fallback answer: delete.** No promotion to step; a stalled turn
   reports failure honestly (step's behavior: message + exit 1 +
   FAILED outcome).
2. **`--json`: delete.** Do/propose never had it (`step` has no
   such flag); ask loses it rather than step gaining it.
3. **`answer` event + `last-tools.jsonl`: retire.** The turn record is
   the audit; `sigil events` keeps rendering old logs. Remove
   `last-tools.jsonl` from `SESSION_FILES`.

Consequences accepted (alpha, no backcompat): ask turns record through
the step path — user event carries `workflow: "ask"` and the assembled
system prompt (fixing the raw-vs-assembled inconsistency); tool and
assistant events are workflow-tagged; ledger workflow stays `ask`.
`step` gains a verbatim-prompt
parameter so ask's prepend-context prompt skips the step instruction
scaffolding.

---

# Roadmap: delegation ledger

The trace of what you delegated becomes the product. `?` grows from a
one-bit status into the query surface over your entire delegation
history — what ran, under which contract, what it touched, what it cost,
what it saw. The successor to shell history.

Anti-goal: `?` stays instant and model-free. The ledger is plain data;
the NL layer sits on top and cites it, never replaces it.

Stages 1–3 are landed: records from every workflow chokepoint; the
global `ledger.sqlite3` index + `sigil log reindex`; the trace-graph
bridge (`turn/<id>` refs, one id namespace with `trace show`); the
query surface (`sigil log` with filters, `blame`, `log show`, `?` v2
with last/staged/today lines) and the `query_log` ask tool with cited
turn ids. Both graduation checks hold: rotation loses no
turn/effect/cost answer, and `, what did I delegate yesterday?`
answers with checkable citations.

## Stage 4 — Durable, global, portable

1. Cross-session by default: `sigil log` queries the machine-wide
   ledger; session scoping becomes a filter, not the universe (today
   everything is fragmented per `SIGIL_SESSION_ID`).
2. `sigil log export --since DATE` → portable bundle: the exported turn
   objects plus their graph closure (`graph_closure` exists) — prompts,
   components, tool results, effects in one self-contained set. Requires
   the Stage 2 bridge; makes every explorer query work on an imported
   bundle for free. The hinge to the trace-portability bet — the ledger
   is the natural unit of exchange, not raw transcripts.
3. Privacy policy as config, not accident: what is retained verbatim
   (objectives? answers?) vs hash-only; a `redact` operation that holds
   under the content-addressed model (replace blob, keep hash +
   tombstone).

Graduation: a bundle exported from one machine answers blame/show/saw
queries on another, with redaction honored.

---

# Roadmap: trace explorer

The ledger answers *what happened* — turns, effects, cost — and hands you
prompt ids. This roadmap makes the trace store answer *why* and *what it
saw* from those ids.

Stages A–B are landed: the forward index (`derivation_inputs`,
`derivations_for_input`), the resolver (ref → exact id → unique prefix,
shared with `log show`/`blame`), recency-ordered multi-kind `objects()`,
and the porcelain (`trace log|show|tree`, plain text, shared one-line
renderers in `display/summarize.py`). Three commands take you from
"what happened" to the exact bytes the model saw:
`sigil log` → `log show <turn>` → `trace show <prompt-prefix>`.

Structural facts to build on:

- Objects deliberately carry no timestamp (content-addressed, deduped);
  derivations carry `created_at` and order every listing.
- Content addressing makes diff almost free: identical component id =
  unchanged; only changed components need a text diff.
- Prompt objects store the payload content hash plus linked components;
  the exact request is reconstructible from the component closure, which
  is what replay and diff consume.

## Stage C — Diff and replay

The two commands the design doc already promises. These prove the
object-graph design publicly — they're the demo.

1. `trace diff <a> <b>` (prompts): component-level first — added /
   removed / replaced components by kind, matched by id (identical id =
   skip); text diff only inside changed components. `--stat` for the
   one-line-per-component view.
2. `trace replay <id>` — reconstruct the stored request from its
   component closure and resend it through the model boundary (honoring
   the session's active model profile, or `--model`), recording the new
   `assistant_message` with a `SigilModelReplay:v1` derivation so
   replays are themselves traced. Print old vs new answer; `--diff` to
   diff them.
3. Natural follow-up once both exist: `trace diff` between a prompt and
   its replay's prompt is the regression-hunting workflow (same
   objective, different model/context).

Graduation: a model-behavior question gets answered by replaying a
stored prompt against a different profile and diffing — no manual prompt
reconstruction.

## Stage D — Scope: cross-session and search

1. `--session ID` (and `--all-sessions` where it makes sense) on the
   trace group. The store path becomes an explicit parameter
   (`default_store(session_id=...)`), not ambient state. Read-only opens
   of other sessions' stores.
2. `trace grep PATTERN [--kind K]` — SQLite LIKE scan over `data_json`
   first; upgrade to FTS5 only if real usage demands it, decided
   together with the shared-index question, not separately.

Graduation: "which session was I in when I asked about X last week" is
answerable from the CLI without opening sqlite3 by hand.

---

# Working note: Q2 2026 Board meeting Google Doc

Observation: Remi asked whether I can read the Google Doc titled "Q2 2026 Board meeting." This is a read-only Google Drive/Docs connector task; no local code changes or Google Doc edits are needed.

Plan:
1. Use Google Drive search/recent-document discovery to find the exact Google Doc by title.
2. Read the document through the Google Docs connector once the file identity is confirmed.
3. Report whether I can access it, and summarize or quote only if Remi asks for that next.

Update plan after Remi asked to improve the flow:
1. Edit the live Google Doc "2026 Q2 .txt Board Memo" directly through the Google Docs connector.
2. Preserve the existing argument and facts, but change the reading order so the enterprise-pilot momentum appears right after the executive summary.
3. Tighten the tool-calling market explanation so it supports the board memo rather than reading as a standalone category essay.
4. Separate litigation detail from the board asks into a clearer executive-session section.
5. Verify each section-sized edit with connector readback before continuing.

Update plan after Remi asked to add what is missing:
1. Add a short "What changed since March" section after the executive summary to summarize the state transition.
2. Add "Q3 success criteria" before Board Asks so the board has a concrete scoreboard.
3. Add a "Risks" section before Board Asks so the downside case is explicit rather than distributed across the memo.
4. Rewrite Board Asks so each item is answerable and action-oriented.
5. Update the top outline and verify the final document structure through connector readback.

## Review fixes for the registry refactor (2026-06-11)

Findings from the code review of the working tree, fix plan agreed with Remi
(allowed-tools filtering stays out of the registry; deduplicate at the
prompt/runtime layers instead):

1. Keep `enabled_tool_names` only in `prompt/system.py` (sorted, prompt-cache
   stable); `builder.py` and `components.py` import it from there.
2. Keep `model_tool_descriptors`/`tool_descriptor_name` only in
   `prompt/system.py`; `agent.py` imports `model_tool_descriptors`.
3. Move the order-preserving `enabled_tool_tuple` from `workflows/step.py`
   to `zeta/agent.py`; `agent_allowed_tools` delegates to it so the step and
   agent paths share one filtering contract. Caller order is load-bearing:
   tests/test_workflows.py:2222 pins ASK_TOOLS order in the ledger contract.
4. `handle_tool_call`: replace the `list_tool_names()` membership test with
   `tool_registry.get(name) is None`.
5. Trim vestigial generality from `ToolRegistry.register` (`replace`,
   `origin`, isinstance check) and drop the `_origins` dict; `tools_list`
   states `origin: builtin` directly. Re-add hooks when plugins return.

Follow-up (done): `ToolRegistry.tools_list` had no production caller left
after the analyze-surface removal — deleted; its test now pins the
registered-builtins invariant via `list_tool_names`. Second pass, also done:
`tool_metadata` deleted (tests use a local accessor over
`get(name).spec.metadata()`); `model_tool_descriptors` removed from the
registry — the prompt layer builds descriptors from specs directly, which
also deleted the `tool_descriptor_name` parse-back helper; `ExecutionMode`
is defined once in `tools/registry.py` and imported by agent/step; renamed
`enabled_tool_tuple` to `registered_tools` and the test alias `zeta_tools`
to `tool_registry`.

## Proposal: own zsh completely (option 5 — no porting)

What it would take to make the zsh binding flawless: fix the `+` widget's
job-control limitation, harden tmux/multi-session behavior, and tighten
binding latency. Grounded in the current `bindings/sigil.zsh`, `cli/run.py`,
`session.py`, and measurements on this machine.

### Observations

- **`+` job control.** The accept-line widget *executes* `sigil run --shell`
  inside zle (`__sigil_accept_line_with_plus_capture`). Anything run inside a
  widget is outside the shell's job table: no Ctrl-Z, no `jobs` entry, signal
  handling is the ad-hoc `zle -I` / `reset-prompt` dance. The README documents
  this as a limitation rather than fixing it.
- **`+` multiline gap.** The capture regex `'^\+[[:space:]]+(.+)$'` cannot
  match a multiline buffer (`.` does not cross newlines), so a multiline
  `+` buffer falls through to plain zsh and dies on `command not found: +` —
  contradicting the README's "multiline buffers intact" claim.
- **tmux session bleed.** `SIGIL_SESSION_ID` is exported once per shell and
  inherited through the environment. The tmux server captures its environment
  at server start, and every new pane/window inherits it — so all panes share
  one session id. Consequences: `recent-turns.jsonl` interleaves commands from
  unrelated panes, `--continue` continuity crosses panes, and a `,,` handoff
  staged in pane A is "resolved" by pane B's next command
  (`latest_unresolved_shell_handoff` reads the shared timeline). Same bleed
  for nested terminals that re-source the binding with the variable set.
- **Glyph prompts go through the zsh parser.** `,`/`,,`/`,,,`/`?` are
  aliases over functions, so the natural-language text is parsed as shell
  grammar before the function sees it. `, what's the deal` leaves an
  unbalanced quote and drops the user into `quote>`; `(` is a parse error;
  `!` can fire history expansion; `#` is stripped under
  `interactive_comments`. `noglob` only papers over the globbing slice of
  this class. Only `+` is currently exempt, because only `+` is captured
  raw by the accept-line widget.
- **Latency, measured.** Three independent costs:
  1. `precmd` runs `sigil handoff shell-turn` synchronously before every
     prompt draw: 35–45ms warm (venv entry point, this machine), ~300ms+
     cold. Every command pays it.
  2. The accept-line widget runs `$(__sigil_plus_capture_command "$BUFFER")`
     — a fork via command substitution on **every Enter press**, including
     empty lines and ordinary commands.
  3. Source time forks twice: `$(command -v sigil)` and `$(uuidgen)`.
- **Concurrency floor is already in place.** `ledger.sqlite3` and the trace
  store both open with WAL + `busy_timeout=5000`. Per-session files become
  single-writer once the session-bleed fix lands.
- **Test gap.** `test_shell_bindings.py` covers the binding well, but only
  through scripted non-interactive `zsh -c` with a fake CLI. Nothing
  exercises zle: the `+` widget, job control, history recall, or prompt
  latency are untested today. Interactive behavior is exactly the surface
  "own one shell" promises.

### Plan

Ordered so the harness pins current behavior before the riskiest change.

**1. Interactive test harness (the enabling investment).**
Drive a real interactive `zsh -i` under a pty (pexpect or stdlib `pty`),
binding sourced, temp HOME, fake `sigil` on PATH — the interactive sibling
of the existing scripted tests. First tests pin today's contract: `+`
dispatch, glyph aliases, history filtering. This is most of the cost of
option 5 and it is reusable for every future binding change.

**2. Latency (smallest blast radius, immediately felt).**
- Replace the synchronous per-command Python call with a pure-zsh spool
  append: `precmd` writes one `${(qq)}`-quoted record (time, command,
  status, cwd) to a per-session spool file with `print -r` — zero forks —
  and every sigil CLI entry point ingests the spool before reading recent
  turns. Ordering is preserved and there is no race: the reader does the
  ingestion, so a `,,` issued immediately after a failure still sees it.
  Backgrounding with `&!` is rejected for exactly that race.
  This also front-runs roadmap Phase 3: the binding becomes a dumb
  emitter; the spool is the proto-`sigil emit`.
- Inline the `+` test in the widget as a pattern match on `$BUFFER` before
  any command substitution; non-`+` lines take zero forks.
- Source time: `__sigil_bin=${commands[sigil]:-sigil}` (no fork) and
  session id from `zmodload zsh/datetime` + `EPOCHREALTIME` + `$$` instead
  of `uuidgen`.
- Targets: ordinary Enter = 0 forks; per-command prompt overhead < 1ms;
  binding source < 5ms; `+` dispatch = 1 fork (sigil run itself).

**3. tmux/multi-session.**
- Tie the session id to the pty, not the environment: export
  `SIGIL_SESSION_TTY` next to the id; on source, if the id is inherited but
  the recorded tty differs from `$TTY`, regenerate both. Subshells and
  `exec zsh` on the same pty keep continuity; every tmux pane, ssh login,
  and new terminal window gets a fresh session. No tmux configuration
  required of the user.
- `sigil doctor` check: flag an inherited session id whose tty does not
  match the current one.
- Pty harness test: two ptys from one exported environment must end up with
  distinct session ids; a same-pty subshell keeps its id.

**4. `+` job control (biggest behavior change, lands on the harness).**
- The widget stops executing. It rewrites the buffer to
  `__sigil_run_plus_capture_command ${(q)command}` and calls
  `zle .accept-line`. The command then runs as a normal foreground job:
  Ctrl-Z suspends `sigil run` and its child shell (one process group),
  `jobs`/`fg`/`bg` work, Ctrl-C is ordinary INT delivery, `$?` is set
  naturally, and preexec/precmd fire like any other command.
- History: `print -s` the original `+ ...` line in the widget so up-arrow
  recalls what the user typed; extend the zshaddhistory filter to drop the
  rewritten `__sigil_*` form. The rewritten line already matches the
  `__sigil_*` recording exclusion, so no double record — pin with a test.
- Fix the multiline capture while in there: prefix test
  `[[ $BUFFER == '+'[[:space:]]* ]]` plus parameter stripping instead of
  the single-line regex, passing the whole remaining buffer through.
- Pty tests: `+ sleep 100` then Ctrl-Z shows a suspended job, `fg`
  resumes, Ctrl-C interrupts; `+ false` leaves `$?` = 1; multiline `+`
  pipelines round-trip.

### Open questions for Remi

1. Spool ingestion point: every CLI entry (`,`/`,,`/`?`/`step`) ingests on
   start — acceptable, or should `?` stay pure-read and tolerate spool lag?
   Proposal: ingest everywhere; it is one small append-file read.
2. With buffer rewrite, Ctrl-Z suspends the `sigil run` wrapper together
   with the user command — `fg` resumes both. Acceptable semantics, or
   should suspension be documented as suspending the capture wrapper too?
   Proposal: accept; it matches what `tee`-style wrappers do.
3. Session-per-pty means `exec ssh`/reattach edge cases inherit whichever
   pty they land on. Any continuity case you care about beyond tmux panes,
   nested shells, and new windows?

## Operational maturity follow-up (2026-06-12)

Request: fix root-user test assumptions and loosen the `rich>=15` floor.

Observations:

- `pyproject.toml` currently pins the runtime dependency as `rich>=15.0`.
  The display code imports stable Rich primitives (`Console`, `Live`,
  `Markdown`, `Panel`, etc.), so the floor can likely move lower.
- `test_doctor_reports_expected_checks` patches `state_dir` to a temporary
  directory and then assumes `check_state_writable` returns `ok`. That is a
  test of the filesystem probe, not of doctor aggregation, and it can behave
  differently when tests run with root-style permissions. The aggregation
  test should patch `check_state_writable` directly.

Plan:

1. Add/update the doctor aggregation test so it does not depend on real
   filesystem writability.
2. Loosen the Rich dependency floor in `pyproject.toml`, then refresh
   `uv.lock` with `uv lock`.
3. Run the focused install tests, then the full suite. Since this updates
   dependency metadata and notes, run pre-commit before finishing.
