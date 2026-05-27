# Shell Workflow

Sigil keeps the shell as the main interface. Use the long-form CLI verbs when
you want explicit commands, and use glyphs when you want fast interactive
handoffs.

## Common Workflows

Generate commands:

```sh
sigil command "find large files"
sigil command --select "show modified Python files"
, run the relevant tests
```

Ask questions:

```sh
sigil ask "what changed in this repo?"
sigil ask --follow-up "what should I test?"
? why did that command fail?
?? what should I try first?
```

Work from stdin:

```sh
git diff | sigil ask "review risky changes"
git diff --name-only | sigil command "choose a focused test command"
git diff | ? explain the riskiest part
```

Run one generated action:

```sh
,, run the formatter for files I changed
```

Let Pi take one bounded edit action:

```sh
,,, fix the failing parser test
sigil act show
```

## Review Points

The shell remains the review boundary:

- `,` proposes and does not execute.
- `,,` executes one command proposal.
- `,,,` asks before one Pi edit action, blocks Pi Bash calls as handoffs, and
  then returns control to the shell.
- `?`, `??`, and `???` answer questions with read/web tools only.

## Session Continuity

Installed shell bindings set `SIGIL_SESSION_ID` once when the shell starts.
That keeps question transcripts, failure context, and act state scoped to one
terminal window by default.

Useful inspection commands:

```sh
sigil session show
sigil session path
sigil events
sigil events lineage
```

Use `sigil session clear` to remove the current session's continuity files.
