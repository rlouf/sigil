# Make TUIs Obsolete

Sigil should not become an agent dashboard. The goal is to make the shell feel
like it has the missing agent verbs: propose, execute one bounded action, ask,
recover, inspect session state, and audit history.

The product constraint is strict:

- No persistent agent screen.
- No inbox.
- No dashboard.
- No hidden agent place.
- State appears only through the shell buffer, command output, `sigil session`,
  `sigil events`, and future audit commands.

## Target Experience

A complete flow should feel inevitable:

```sh
uv run pytest
, fix
,, run focused test
sigil ask "explain the risk"
git commit -m "..."
sigil events
```

The user should not think "I need an agent TUI." They should think "my shell
already has the agent affordances I need."

## Ladder 1: Explicit State

Goal: Sigil exposes live state without opening a dashboard or adding ambient
shell capture.

`sigil session` and `sigil events` are the explanation paths. They should stay
cheap: no model call, no network, no doctor checks, no mutation.

Initial attention reasons:

- active act
- pending staged command
- latest failed shell turn
- latest failed Sigil action

Definition of done: after any Sigil route, the user can inspect what happened
with `sigil session` or `sigil events`.

## Ladder 2: Recovery Loop

Goal: failed command to useful next action in one gesture.

Make these work reliably:

```sh
, fix
, why failed
```

They should consume:

- latest explicitly recorded command
- exit status
- cwd
- bounded stderr/stdout
- recent explicit Sigil turns
- relevant git status
- recent answer context

Add secret hygiene before capturing command output:

- skip leading-space commands
- redact common token and environment patterns
- bound captured output aggressively

Definition of done: after `uv run pytest` fails, `, fix` produces a focused next
command or concise explanation without extra user context.

## Ladder 3: `sigil why`

Goal: inline audit context for the last meaningful Sigil output.

```sh
sigil why
```

It should explain:

- what command, answer, or action it refers to
- what context was used
- model route used
- why this action was selected

This is not a verbose trace dump. It should be a readable explanation over
existing events.

Definition of done: after `,`, `,,`, `sigil ask`, or `,,,`, `sigil why` explains the
last meaningful Sigil output.

## Ladder 4: First-Run Clarity

Goal: setup failures are actionable.

Improve `sigil doctor` so every failure includes the exact next command when
there is a safe obvious fix. Warnings should stay warnings, but they should
still tell users what to do next.

Definition of done: a new user can run `sigil doctor` and fix setup without
reading docs first.

## Execution Order

1. Session/event inspection over dashboard state.
2. Capture bounded stdout and stderr for explicit `sigil run` turns.
3. Improve `, fix` and failure-context prompting.
4. Add `sigil why`.
5. Polish first-run and doctor output with exact fix commands.
6. Record a killer demo flow and use it as regression material.

## TODO

### Explicit State

- [x] Keep `sigil session` and `sigil events` cheap: never call the model or network.

### Recovery Loop

- [x] Extend recent turn records with bounded stdout and stderr snippets when
      the shell provides them.
- [x] Keep leading-space commands out of captured turn state.
- [x] Add redaction for common token, key, password, and bearer patterns.
- [x] Preserve prompt responsiveness while recording richer turn state.
- [x] Update failure-context prompts to prefer recent turn output when present.
- [x] Add fixtures for common failures: pytest, missing command, git, network,
      and permission errors.
- [x] Attach the last failure to `,` and `sigil ask` whenever it is the latest shell
      turn, regardless of how the prompt is phrased.
- [x] Make `, why failed` explain the last failure without asking for more
      context.
- [x] Capture bounded stdout and stderr for explicit `sigil run` turns.
- [x] Add a deterministic demo for `, fix` and `, why failed`.

### `sigil why`

- [ ] Add a `sigil why [EVENT_ID] [--json]` command.
- [ ] Default to the latest meaningful Sigil event in the current session.
- [ ] Explain the selected output, context inputs, route, and model source.
- [ ] Keep human output short and non-trace-like.
- [ ] Add tests for `,`, `,,`, `sigil ask`, and `,,,` audit context.

### First-Run Clarity

- [ ] Add exact fix commands or next steps to `doctor` failures.
- [ ] Keep warnings non-fatal, but make their remediation explicit.
- [ ] Add JSON fields for remediation commands.
- [ ] Add tests for missing `zeta`, missing `glow`, unreachable model endpoint,
      missing model name, and unwritable state directory.

### Demo And Regression

- [ ] Create a deterministic demo for:
      `uv run pytest` -> `, fix` -> `,, run focused test` -> `sigil ask
      "explain the risk"` -> `sigil events`.
- [ ] Use the demo fixtures as regression tests where practical.
- [ ] Update README examples around the final flow.
- [ ] Re-rate the CLI against the 10/10 criteria after the demo passes.
