# Glyph Reference

Sigil's shell glyphs are optional shortcuts installed by `sigil install zsh` or
`sigil install bash`. They are current user-facing shell APIs.

```text
,    recommend one command or patch action
,,   generate and run one command, or preview and confirm one patch
,,,  run one confirmed Pi edit action

?    ask a fresh read/web question
??   follow up on the previous question in the same shell session
???  ask for a more exhaustive read-only answer
```

## Comma Routes

Use `,` when you want a proposal:

```sh
, run the relevant tests
, summarize what command I should run next
git diff --name-only | , choose a focused test command
```

`comma` prints one proposal. If the proposal is a command, the zsh binding puts
it in the editable prompt buffer and records it in history; the Bash binding
records it in history so you can recall, edit, and run it yourself.

Use `,,` when you want Sigil to take one action:

```sh
,, run the relevant formatter
,, check whether this branch builds
```

Command proposals run through your shell. Patch proposals are stored, shown as a
preview, and applied only after confirmation.

Use `,,,` for one bounded Pi edit action:

```sh
,,, fix the failing parser test
sigil act show
sigil act abort
```

The act state is durable in the current shell session. Each invocation runs at
most one accepted Pi edit pass.

## Question Routes

Use `?` for a fresh answer:

```sh
? why does git say this branch diverged?
git diff | ? review risky changes
```

Use `??` to continue the previous question transcript from the same terminal:

```sh
?? what is the safest next command?
```

Use `???` when you want a more exhaustive read-only answer:

```sh
??? explain the release options and their risks
```

Question routes do not execute commands, apply patches, or expose Bash. If an
answer recommends a command, it is plain answer text.

## Piped Input

Piped input is previewed before it can influence a comma route. Question routes
attach piped input without an extra confirmation because they have no execute
path:

```sh
git diff | ? review this change
git diff --name-only | , pick the most relevant tests
```

If you decline the preview, Sigil exits without using the input.
