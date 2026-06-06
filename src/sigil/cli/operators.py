"""Internal glyph dispatch shared by shell-facing routes and tests."""

from __future__ import annotations

import sys

import click

from ._shared import confirm_piped_input, print_json_line, question_with_stdin
from ._shared import should_confirm_piped_input, should_run_agent_operator
from ..routes.ask import (
    ZETA_ANSWER_TOOLS,
    ask,
    discussion_turns,
)
from ..routes.operators import OperatorInvocation, create_invocation
from ..routes.zeta_step import run_agent_step
from ..status import current_status, format_status


def run_operator(
    glyph: str,
    prompt_parts: tuple[str, ...],
    json_output: bool,
) -> int:
    """Parse a semantic operator invocation."""
    stdin_is_tty = sys.stdin.isatty()
    stdin_text = "" if stdin_is_tty else sys.stdin.read()
    prompt = " ".join(prompt_parts)
    mode = "interactive" if stdin_is_tty else "pipeline"
    try:
        invocation = create_invocation(
            glyph,
            prompt=prompt,
            stdin=stdin_text,
            mode=mode,
        )
    except ValueError as exc:
        raise click.BadParameter(str(exc), param_hint="glyph") from exc

    if json_output:
        print_json_line(invocation.to_dict())
        return 0

    if should_run_agent_operator(invocation):
        return dispatch_agent_operator(invocation, prompt, stdin_text)

    if invocation.name == "status":
        return dispatch_status_operator()

    if should_confirm_piped_input(invocation):
        if not confirm_piped_input(stdin_text):
            print("sigil glyph: piped input declined", file=sys.stderr)
            raise click.exceptions.Exit(2)

    return dispatch_readonly_operator(invocation, json_output=json_output)


def dispatch_status_operator() -> int:
    """Run the status glyph through the read-only status renderer."""
    status = current_status()
    print(format_status(status))
    if status.state != "clean":
        return 1
    return 0


def dispatch_agent_operator(
    invocation: OperatorInvocation,
    prompt: str,
    stdin_text: str,
) -> int:
    """Run a `,,`/`,,,` invocation through the Zeta agent step route."""
    if should_confirm_piped_input(invocation):
        if not confirm_piped_input(stdin_text):
            print("sigil glyph: piped input declined", file=sys.stderr)
            raise click.exceptions.Exit(2)
    try:
        status = run_agent_step(
            prompt,
            stdin_text=stdin_text,
            glyph=invocation.glyph,
        )
    except RuntimeError as exc:
        print(f"sigil glyph: {exc}", file=sys.stderr)
        return 1
    if status:
        raise click.exceptions.Exit(status)
    return 0


def dispatch_readonly_operator(
    invocation: OperatorInvocation,
    *,
    json_output: bool = False,
) -> int:
    """Run the single-comma glyph through the read-only answer route."""
    question = invocation.prompt
    stdin_text = invocation.stdin
    if stdin_text:
        question = question_with_stdin(question, stdin_text)
    if not question:
        question = "Inspect and summarize the current shell context."
    turns = discussion_turns()
    append_transcript = bool(turns)
    if append_transcript:
        return ask(
            question,
            glyph=",",
            tools=ZETA_ANSWER_TOOLS,
            append_transcript=True,
            history=turns,
            json_output=json_output,
        )
    return ask(
        question,
        glyph=",",
        tools=ZETA_ANSWER_TOOLS,
        append_transcript=False,
        json_output=json_output,
    )
