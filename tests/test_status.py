from __future__ import annotations

import os

from click.testing import CliRunner

from sigil.cli import cli
from sigil.session import record_turn
from sigil.status import current_status, format_status


def test_status_clean_when_no_live_state() -> None:
    status = current_status()

    assert status.state == "clean"
    assert format_status(status) == "clean"


def test_status_reports_last_failure() -> None:
    record_turn("uv run pytest", 1, os.getcwd(), stderr_snippet="failed")
    status = current_status()

    assert status.reason == "last command failed"
    assert status.actions == (", suggest a fix",)
    assert "uv run pytest" in format_status(status)


def test_status_ignores_stale_failure_after_successful_turn() -> None:
    record_turn("uv run pytest", 1, os.getcwd(), stderr_snippet="failed")
    record_turn("git status --short", 0, os.getcwd())
    status = current_status()

    assert status.state == "clean"


def test_status_cli_is_public_surface() -> None:
    result = CliRunner().invoke(cli, ["status"])

    assert result.exit_code == 0
    assert result.output == "clean\n"
