"""Command-line boundary between shell bindings and the Sigil runtime.

The CLI is intentionally boring: shell integrations should call these commands
instead of reimplementing model calls, selectors, rendering, or state handling.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from .ansi import MUTED, RESET
from .commands import generate, previous as previous_command_state, select
from .edit import edit_file, result_to_json
from .failure import record_failure, select_fix, select_previous_fix
from .install import (
    SUPPORTED_SHELLS,
    checks_exit_code,
    checks_summary,
    checks_to_json,
    doctor_checks,
    install_shell,
)
from .pi_stream import stream_events
from .question import ask
from .security import inherited_label, make_security, normalize_security, record_id
from .session import (
    clear_current_session,
    current_session_snapshot,
    event_lineage,
    known_sessions,
    session_paths,
    session_summary,
)
from .state import append_event, read_json


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
def cli() -> None:
    """Punctuation-native LLM interaction for the shell.

    \b
    Examples:
      sigil command --select "find large files"
      sigil command --previous --select
      sigil question --json "what changed in this repo?"
      sigil question --follow-up "summarize that as a command"
      sigil install zsh
      sigil doctor
      sigil summary
      sigil events lineage
      sigil session show --json

    \b
    Docs and issues:
      https://github.com/rlouf/sigil
    """


@cli.command("command")
@click.argument("prompt", required=False)
@click.option("--previous", "previous_command", is_flag=True)
@click.option("--select", "select_candidate", is_flag=True)
@click.option("--json", "json_output", is_flag=True)
def cmd_command(
    prompt: str | None,
    previous_command: bool,
    select_candidate: bool,
    json_output: bool,
) -> int:
    """Generate command candidates and optionally run the selector UI."""
    if previous_command:
        prompt, candidates, security = previous_command_state()
        continued = append_event(
            {"type": "command_continued", "prompt": prompt, **security}
        )
        security = {**security, "inputs": [continued["id"]]}
        print(
            f"{MUTED}❯ sigil ,, · inherited: {inherited_label(security)}{RESET}",
            file=sys.stderr,
        )
        if json_output:
            print(
                json.dumps(
                    {"prompt": prompt, "commands": candidates, **security},
                    ensure_ascii=False,
                )
            )
            return 0
        command = (
            select(prompt, candidates, security)
            if select_candidate
            else candidates[0]["command"]
        )
        if command:
            append_event({"type": "command_selected", "command": command, **security})
            print(command)
        return 0
    if prompt is None:
        raise click.UsageError("PROMPT is required unless --previous is set.")

    candidates = generate(prompt)
    source = normalize_security(read_json("last-command.json") or {})
    security = make_security(
        glyph=",",
        integrity="local_model",
        capability="propose",
        taint=["model"],
        inputs=[record_id(source)],
        input_records=[source],
        fresh_human=True,
    )
    if json_output:
        print(
            json.dumps({"prompt": prompt, "commands": candidates}, ensure_ascii=False)
        )
        return 0
    if select_candidate:
        command = select(prompt, candidates, security)
        if command:
            append_event({"type": "command_selected", "command": command, **security})
            print(command)
        return 0
    for item in candidates:
        print(item["command"])
    return 0


@cli.command("question")
@click.argument("question")
@click.option("--follow-up", is_flag=True)
@click.option("--json", "json_output", is_flag=True)
def cmd_question(question: str, follow_up: bool, json_output: bool) -> int:
    """Answer a fresh shell question and reset the session transcript."""
    return ask(question, follow_up=follow_up, json_output=json_output)


@cli.command("edit")
@click.argument("file", type=click.Path(path_type=Path, dir_okay=False))
@click.argument("instruction")
@click.option("--yes", is_flag=True, help="Apply the reviewed proposal without asking.")
@click.option(
    "--editor",
    help="Diff editor command. Defaults to SIGIL_EDITOR, VISUAL, EDITOR, then nvim.",
)
@click.option("--json", "json_output", is_flag=True)
def cmd_edit(
    file: Path,
    instruction: str,
    yes: bool,
    editor: str | None,
    json_output: bool,
) -> int:
    """Propose a reviewed single-file edit using Pi and a diff editor."""
    try:
        result = edit_file(file, instruction, editor=editor, yes=yes)
    except FileNotFoundError as error:
        click.echo(f"sigil: file not found: {error.filename or file}", err=True)
        return 1
    except ValueError as error:
        click.echo(f"sigil: {error}", err=True)
        return 1
    except RuntimeError as error:
        click.echo(f"sigil: {error}", err=True)
        return 1

    if json_output:
        print(result_to_json(result))
        return 0 if result.applied else 1
    if result.applied:
        print(f"applied reviewed proposal to {result.path}")
        return 0
    print(f"left original unchanged; proposal remains at {result.proposal_path}")
    return 1


def run_install_shell(
    shell: str,
    install_dir: Path | None,
    rc_path: Path | None,
    json_output: bool,
) -> int:
    """Install or update a Sigil shell binding."""
    result = install_shell(shell, install_dir=install_dir, rc_path=rc_path)
    if json_output:
        print_json(
            {
                "shell": result.shell,
                "binding_path": result.binding_path,
                "rc_path": result.rc_path,
                "source_path": result.source_path,
                "wrote_rc": result.wrote_rc,
            }
        )
        return 0

    print(f"installed Sigil {shell} binding at {result.binding_path}")
    if result.wrote_rc:
        print(f"updated {result.rc_path}")
    else:
        print(f"{result.rc_path} already sources Sigil")
    print(f"restart your shell or run: source {result.rc_path}")
    return 0


@cli.command("install")
@click.argument("shell", type=click.Choice(SUPPORTED_SHELLS))
@click.option(
    "--install-dir",
    type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
    help="Directory where the shell binding should be installed.",
)
@click.option(
    "--rc",
    "rc_path",
    type=click.Path(path_type=Path, dir_okay=False),
    help="Shell rc file to update.",
)
@click.option("--json", "json_output", is_flag=True)
def cmd_install_shell(
    shell: str,
    install_dir: Path | None,
    rc_path: Path | None,
    json_output: bool,
) -> int:
    """Install or update a Sigil shell binding."""
    return run_install_shell(shell, install_dir, rc_path, json_output)


@cli.command("install-shell", hidden=True)
@click.argument("shell", type=click.Choice(SUPPORTED_SHELLS))
@click.option(
    "--install-dir",
    type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
    help="Directory where the shell binding should be installed.",
)
@click.option(
    "--rc",
    "rc_path",
    type=click.Path(path_type=Path, dir_okay=False),
    help="Shell rc file to update.",
)
@click.option("--json", "json_output", is_flag=True)
def cmd_install_shell_alias(
    shell: str,
    install_dir: Path | None,
    rc_path: Path | None,
    json_output: bool,
) -> int:
    """Compatibility alias for `sigil install`."""
    return run_install_shell(shell, install_dir, rc_path, json_output)


@cli.command("doctor")
@click.option(
    "--shell",
    "shell_name",
    type=click.Choice(("auto", *SUPPORTED_SHELLS)),
    default="auto",
    show_default=True,
    help="Shell binding to diagnose.",
)
@click.option("--json", "json_output", is_flag=True)
def cmd_doctor(shell_name: str, json_output: bool) -> int:
    """Check whether Sigil is installed and ready to use."""
    checks = doctor_checks(shell=shell_name)
    if json_output:
        print(checks_to_json(checks))
        return checks_exit_code(checks)

    for check in checks:
        line = f"{check.status:4} {check.name} - {check.detail}"
        print(line)
        if check.hint and check.status != "ok":
            print(f"     hint: {check.hint}")
    summary = checks_summary(checks)
    print(f"{summary['ok']} ok, {summary['warn']} warnings, {summary['fail']} failures")
    return checks_exit_code(checks)


@cli.command("render-pi-stream", hidden=True)
@click.option("--json", "json_output", is_flag=True)
def cmd_render_pi_stream(json_output: bool) -> int:
    """Render Pi's JSON event stream for the question pipeline."""
    return stream_events(json_output=json_output)


def print_json(value: object) -> None:
    """Print inspection data in a stable machine-readable shape."""
    print(json.dumps(value, ensure_ascii=False, indent=2))


@cli.group("events")
def cmd_events() -> None:
    """Inspect Sigil's read-only event log."""


@cmd_events.command("lineage")
@click.argument("event_id", required=False)
@click.option("--json", "json_output", is_flag=True)
def cmd_events_lineage(event_id: str | None, json_output: bool) -> int:
    """Show the provenance chain for an event."""
    lineage = event_lineage(event_id)
    if json_output:
        print_json(lineage)
        return 0 if lineage["nodes"] else 1

    if not lineage["nodes"]:
        print(
            "no events recorded" if event_id is None else f"event not found: {event_id}"
        )
        return 1
    for node in lineage["nodes"]:
        event = node["event"]
        indent = "  " * int(node["depth"])
        event_type = event.get("type", "event")
        glyph = event.get("glyph", "?")
        integrity = event.get("integrity", "unknown")
        capability = event.get("capability", "none")
        taint = ",".join(event.get("taint", [])) or "none"
        inputs = ",".join(event.get("inputs", [])) or "-"
        print(
            f"{indent}{node['id']} {event_type} "
            f"{glyph} {integrity}/{capability} taint={taint} inputs={inputs}"
        )
    for missing in lineage["missing_inputs"]:
        print(f"missing input: {missing}")
    return 0


@cli.command("summary")
@click.option("--json", "json_output", is_flag=True)
@click.option("--limit", type=int, default=8, show_default=True)
def cmd_summary(json_output: bool, limit: int) -> int:
    """Summarize the current session without mutating state."""
    summary = session_summary(limit=max(0, limit))
    if json_output:
        print_json(summary)
        return 0

    continuity = summary["continuity"]
    print(f"session {summary['session_id']}")
    print(summary["path"])
    print(
        "continuity "
        f"command={continuity['has_command']} "
        f"failure={continuity['has_failure']} "
        f"fix={continuity['has_fix']} "
        f"questions={continuity['question_turns']} "
        f"tools={continuity['tool_events']}"
    )
    if summary["recent_events"]:
        print("recent events")
    for event in summary["recent_events"]:
        taint = ",".join(event["taint"]) or "none"
        inputs = ",".join(event["inputs"]) or "-"
        print(
            f"  {event['id']} {event['type']} {event['glyph']} "
            f"{event['integrity']}/{event['capability']} "
            f"taint={taint} inputs={inputs}"
        )
    return 0


@cli.command("session")
@click.argument(
    "session_command",
    required=False,
    default="show",
    type=click.Choice(["show", "path", "list", "clear"]),
)
@click.option("--json", "json_output", is_flag=True)
def cmd_session(session_command: str, json_output: bool) -> int:
    """Inspect or clear the current shell session state."""
    if session_command == "path":
        paths = session_paths()
        if json_output:
            print_json(paths)
        else:
            print(paths["session"])
        return 0
    if session_command == "list":
        sessions = known_sessions()
        if json_output:
            print_json(sessions)
        else:
            for session in sessions:
                print(f"{session['session_id']}\t{session['path']}")
        return 0
    if session_command == "clear":
        removed = clear_current_session()
        if json_output:
            print_json({"removed": removed})
        else:
            if removed:
                for path in removed:
                    print(f"removed {path}")
            else:
                print("session already clear")
        return 0

    snapshot = current_session_snapshot()
    if json_output:
        print_json(snapshot)
    else:
        print(f"session {snapshot['session_id']}")
        print(snapshot["path"])
        for name, value in snapshot["files"].items():
            if value is None:
                continue
            if isinstance(value, list):
                print(f"{name}: {len(value)} entries")
            elif isinstance(value, dict):
                print(f"{name}: {len(value)} keys")
            else:
                print(f"{name}: present")
    return 0


@cli.command("record-failure", hidden=True)
@click.option("--status", type=int, required=True)
@click.option("--cwd")
@click.option("--stdout-snippet", default="")
@click.option("--stderr-snippet", default="")
@click.argument("command")
def cmd_record_failure(
    command: str,
    status: int,
    cwd: str | None,
    stdout_snippet: str,
    stderr_snippet: str,
) -> int:
    """Record a failed shell command for later repair."""
    record_failure(command, status, cwd, stdout_snippet, stderr_snippet)
    return 0


@cli.command("fix")
@click.option("--previous", is_flag=True)
def cmd_fix(previous: bool) -> int:
    """Suggest fixes for the last recorded failed shell command."""
    command = select_previous_fix() if previous else select_fix()
    if command:
        append_event({"type": "fix_selected", "command": command})
        print(command)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Parse the shell-agnostic Sigil CLI surface."""
    try:
        result = cli.main(args=argv, prog_name="sigil", standalone_mode=False)
    except click.ClickException as error:
        error.show()
        return error.exit_code
    except click.Abort:
        click.echo("Aborted!", err=True)
        return 1
    except FileNotFoundError as error:
        program = error.filename or "required executable"
        click.echo(f"sigil: missing executable: {program}", err=True)
        click.echo("Install it or make sure it is on PATH, then retry.", err=True)
        return 127
    except PermissionError as error:
        target = error.filename or "requested path"
        click.echo(f"sigil: permission denied: {target}", err=True)
        click.echo(
            "Check the path permissions or set SIGIL_STATE_DIR to a writable directory.",
            err=True,
        )
        return 1
    return int(result or 0)


if __name__ == "__main__":
    raise SystemExit(main())
