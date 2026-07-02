# Moving Runtime Commands From Commas To Zeta

Runtime state is owned by the `zeta` CLI. Commas keeps shell-session commands.

| Old command | New command |
| --- | --- |
| `commas trace log` | `zeta trace log` |
| `commas trace tools` | `zeta trace tools` |
| `commas trace grep` | `zeta trace grep` |
| `commas trace show` | `zeta trace show` |
| `commas trace tree` | `zeta trace tree` |
| `commas trace closure` | `zeta trace closure` |
| `commas trace refs` | `zeta trace refs` |
| `commas trace prompts` | `zeta trace prompts` |
| `commas trace diff` | `zeta trace diff` |
| `commas trace replay` | `zeta trace replay` |
| `commas events` | `zeta events` |
| `commas events trace` | `zeta events trace` |
| `commas events root` | `zeta events root` |
| `commas events descendants` | `zeta events descendants` |
| `commas events turn` | `zeta events turn` |
| `commas model list` | `zeta model list` |
| `commas model show` | `zeta model show` |

State-dir defaults changed for trace commands: `zeta trace` reads the project
`.zeta/` directory by default, like `zeta events` and `zeta runs`. Pass
`--state-dir` to inspect a different runtime state directory.

`commas model use` and `commas model clear` remain in Commas because they manage
the current shell session's model selection.
