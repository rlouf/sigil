"""Internal transcript commands for shell bindings."""

from __future__ import annotations

import json
import sys

import click

from ._base import cli
from ._shared import pretty_print_json, read_json_stdin
from .. import handoff


@cli.group("transcript", hidden=True)
def cmd_transcript() -> None:
    """Record and reconcile Sigil shell transcript events."""


@cmd_transcript.command("shell-turn")
def transcript_shell_turn() -> int:
    """Record one shell command executed after a Zeta handoff."""
    try:
        turn = read_json_stdin(sys.stdin)
    except (json.JSONDecodeError, ValueError) as exc:
        raise click.BadParameter(str(exc), param_hint="stdin") from exc
    pretty_print_json(handoff.append_shell_turn(turn))
    return 0
