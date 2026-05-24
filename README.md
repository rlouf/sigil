# Sigil

Punctuation-native LLM interaction for the shell.

![15-second Sigil terminal demo](docs/demo.gif)

Status: this is currently a "works on my machine" repo. If you are interested
in an easier-to-install version, please open an issue.

The Python package is named `sigil-sh` because `sigil` was not available as a
distribution name. The installed command is still `sigil`, and this repository
uses `sigil` everywhere else.

Sigil is structured as a shell-agnostic core with thin shell bindings. The zsh
layer owns prompt interception and buffer insertion; the Python CLI owns model
calls, selection UI, Pi streaming, rendering, and persistent state.

## Grammar

```text
,   generate shell command candidates
,,  reopen the previous command selector
^   suggest fixes for the last failed command
^^  reopen previous fix candidates
?   answer a question with Pi using read + web search
??  continue the previous question discussion
```

Sigil records every glyph invocation with trust metadata. This is the core trust
lattice:

```text
integrity:  human > local_model > local_file > web > unknown
capability: none < propose < read < write_boxed < exec_boxed
taint:      model, web, legacy
```

The current grammar maps to:

```text
,   human prompt -> local model proposal   local_model / propose / model-tainted
,,  command continuation                   inherits prior command taint
?   read + web question                    web / read / web-tainted / provisional
??  question continuation                  inherits prior question taint / provisional
```

This matters because Sigil crosses the shell boundary by inserting text into the
prompt. Model-authored command suggestions are proposals, not executed actions.
Web-tainted question answers are read-only and provisional, and cannot become an
executable insertion path through `??`.

Current no-execute guarantees:

```text
no ?! parser route
no auto-run from web-tainted state
no promotion mutation
no bang unless sandbox exists
```

The full trust model is documented in
[docs/security-lattice.md](docs/security-lattice.md).

## Install

Current rough install for early users:

```sh
uv tool install git+https://github.com/rlouf/sigil
curl -fsSL https://raw.githubusercontent.com/rlouf/sigil/main/shell/zsh/install.zsh | zsh
# or
curl -fsSL https://raw.githubusercontent.com/rlouf/sigil/main/shell/bash/install.bash | bash
```

Manual install, if you want to inspect each step before sourcing shell code:

```sh
uv tool install git+https://github.com/rlouf/sigil

mkdir -p ~/.sigil/shell/zsh
curl -fsSL https://raw.githubusercontent.com/rlouf/sigil/main/shell/zsh/sigil.zsh \
  -o ~/.sigil/shell/zsh/sigil.zsh
printf '\n# Sigil\nsource "$HOME/.sigil/shell/zsh/sigil.zsh"\n' >> ~/.zshrc
```

For Bash, replace the last three lines with:

```sh
mkdir -p ~/.sigil/shell/bash
curl -fsSL https://raw.githubusercontent.com/rlouf/sigil/main/shell/bash/sigil.bash \
  -o ~/.sigil/shell/bash/sigil.bash
printf '\n# Sigil\nsource "$HOME/.sigil/shell/bash/sigil.bash"\n' >> ~/.bashrc
```

The installer downloads the zsh binding to `~/.sigil/shell/zsh/sigil.zsh` and
adds an idempotent source block to `~/.zshrc`. It also warns if `sigil`, `fzf`,
`glow`, `pi`, or the local model endpoint are not available.

The Bash installer downloads the binding to `~/.sigil/shell/bash/sigil.bash`
and adds an idempotent source block to `~/.bashrc`. It performs the same checks.

After install, verify the local pieces:

```sh
command -v sigil fzf glow pi
python3 -c 'import socket; socket.create_connection(("127.0.0.1", 8080), timeout=1).close()'
```

The endpoint check is expected to fail unless your local OpenAI-compatible model
server is already running. Sigil will also check this before command generation.

## Layout

```text
shell/bash/install.bash  Bash binding installer
shell/bash/sigil.bash    Bash binding
shell/zsh/install.zsh  zsh binding installer
shell/zsh/sigil.zsh    zsh binding
src/sigil/             Python core runtime
```

Core commands:

```sh
sigil command --select "find wav files"
sigil command --previous --select
sigil fix
sigil fix --previous
sigil question "what is tldraw?"
sigil question --follow-up "how would that work in practice?"
sigil session show
sigil session path
sigil session list
sigil session clear
```

The zsh binding calls those commands and inserts selected commands back into the
prompt with `print -z`.

## State

Sigil writes state under:

```text
~/.sigil/
```

Current files:

```text
events.jsonl                                 append-only global event log
sessions/<session-id>/last-command.json      latest command candidates for `,,`
sessions/<session-id>/last-failure.json      latest failed shell command
sessions/<session-id>/last-fix.json          latest fix candidates for `^^`
sessions/<session-id>/last-question.jsonl    question transcript; reset by `?`
sessions/<session-id>/last-tools.jsonl       latest Pi tool trace
```

Events and session JSONL entries include these trust fields:

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

Legacy state that predates those fields is treated as low-trust:
`integrity=unknown`, `capability=none`, and `taint=["legacy"]`.

The event log is the durable substrate for future `@.`, `@@`, and `!!`
behavior. Shell globals are intentionally not used for session continuity.

## zsh

Source the zsh entrypoint from `.zshrc`:

```zsh
source "$HOME/.sigil/shell/zsh/sigil.zsh"
```

## Bash

Source the Bash entrypoint from `.bashrc`:

```bash
source "$HOME/.sigil/shell/bash/sigil.bash"
```

Bash supports the same glyph functions:

```bash
, find wav files
,,
? what is tldraw?
?? how would that work in practice?
^
^^
```

Because Bash has no zsh-style `print -z` buffer stack, direct `,` and `^`
commands print the selected proposal and add it to history. To get the zsh-like
"replace the current prompt buffer, but do not execute it" flow, type a Sigil
glyph expression at the prompt and press `Ctrl-X ,`.

## Requirements

- `python3`
- `curl`-compatible local llama.cpp/OpenAI endpoint for command generation
- `fzf` for command selection
- `glow` for Markdown rendering
- `pi` for question answering

`pi` is the .txt agent CLI used by the `?` and `??` routes. It is not installed
by Sigil. Install and configure it separately, then verify `pi --help` works.
Sigil invokes it as `pi --json --tools read,web_search ...`, then renders the
event stream through `sigil render-pi-stream` so tool calls, answer text, and
trust metadata are recorded in Sigil state. `pi` must be on `PATH`, and for the
current local setup it should be able to start or reach the same Qwen endpoint
used by Sigil.

Environment knobs:

```sh
QWEN_URL=http://127.0.0.1:8080/v1/chat/completions
QWEN_MODEL=qwen3.6-27b-q8-local
QWEN_MODEL_PATH=/path/to/model.gguf
```

By convention this repo expects the helper script
`~/.config/pi/run-qwen36-q8.sh` to start a llama.cpp-compatible server on
`127.0.0.1:8080`. You can also run `llama-server` yourself with the same alias
and port.
