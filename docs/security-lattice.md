# Sigil Trust Model

Sigil records where an answer or action came from and what it was allowed to
do. This metadata is visible through `sigil events`, `sigil events lineage`,
and `sigil session show --json`.

## Trust Fields

User-facing event records can include:

```json
{
  "glyph": "?",
  "inputs": ["event-id"],
  "integrity": "web",
  "capability": "read",
  "taint": ["web"],
  "provisional": true
}
```

Fields:

- `glyph`: route that produced the record, such as `,`, `,,`, `,,,`, `?`, or
  `??`.
- `inputs`: previous event ids used as context.
- `integrity`: origin label, ordered as `human > local_model > local_file > web
  > unknown`.
- `capability`: maximum effect class, ordered as `none < propose < read <
  write_boxed < exec_boxed`.
- `taint`: accumulated source labels, currently most often `model`, `web`, or
  `legacy`.
- `provisional`: whether the record should be treated as provisional context
  rather than stable authority.

## Route Mapping

```text
,    local model proposal
     integrity=local_model
     capability=propose
     taint=["model"]

,,   local model command execution or patch preview/application
     proposal event: capability=propose
     command execution event: capability=exec_boxed
     patch application event: capability=write_boxed
     taint=["model"]

,,,  confirmed Pi edit action
     act creation events: capability=propose
     confirmed Pi execution events: capability=exec_boxed
     taint=["model"]

?    read/web question
     integrity=web
     capability=read
     taint=["web"]
     provisional=true

??   read/web follow-up
     inherits prior question transcript inputs
     capability=read
     taint includes "web"
     provisional=true

???  exhaustive read/web question
     capability=read
     taint includes "web"
     provisional=true
```

Question routes never expose Bash to Pi. Triple-comma act steps may hand off a
proposed Bash command, but they do not execute it through Pi. In zsh the shell
binding inserts the handed-off command into the editable prompt buffer; Bash
stores it in history. Execution and file writes happen through comma routes, Pi
edit/write tools, or through the user pressing Enter on an edited handoff
command.

## Practical Examples

List recent events:

```sh
sigil events
```

Example table:

```text
time      id        action       trust                   session   summary
12:00:01  e3b0c442  ? question   web/read                9aa2f6e1  what changed?
12:01:10  2f7d6a8c  , recommend  local_model/propose     9aa2f6e1  run the tests
12:01:18  b1c4a901  ,, executed  local_model/exec_boxed  9aa2f6e1  uv run pytest -> 0
```

Inspect provenance:

```sh
sigil events lineage b1c4a901
```

JSON lineage includes the selected event, any input events, and missing input
ids if an event references records that are no longer present:

```json
{
  "event_id": "b1c4a901-...",
  "nodes": [
    {
      "id": "b1c4a901-...",
      "depth": 0,
      "event": {
        "type": "operator_command_executed",
        "glyph": ",,",
        "integrity": "local_model",
        "capability": "exec_boxed",
        "taint": ["model"]
      }
    }
  ],
  "missing_inputs": []
}
```

## Legacy State

Older state records may not contain trust fields. When Sigil reads those
records, it treats them conservatively:

```text
integrity=unknown
capability=none
taint=["legacy"]
provisional=false
inputs=[]
```

That lets old records remain inspectable without treating them as trusted
current context.

## User Rules

- `,` recommends; it does not execute.
- `,,` can execute a generated command, or preview and confirm a generated
  patch.
- `,,,` executes at most one confirmed Pi edit action per invocation.
- `?`, `??`, and `???` are read/web question routes with no Bash tool.
- `??` continues the same-session question transcript; it does not switch to a
  command route.
- `sigil patch apply --yes` is the explicit command for applying the latest
  stored patch preview later.
