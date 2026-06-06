from __future__ import annotations

import os
import tempfile
from pathlib import Path

from click.testing import CliRunner

from sigil.cli import cli
from sigil.session import record_turn
from sigil.status import current_status, format_status
from sigil.state import append_event


def test_status_clean_when_no_live_state() -> None:
    with isolated_sigil_state():
        status = current_status()

    assert status.state == "clean"
    assert format_status(status) == "clean"


def test_status_reports_last_failure() -> None:
    with isolated_sigil_state():
        record_turn("uv run pytest", 1, os.getcwd(), stderr_snippet="failed")
        status = current_status()

    assert status.reason == "last command failed"
    assert status.actions == (", suggest a fix",)
    assert "uv run pytest" in format_status(status)


def test_status_ignores_stale_failure_after_successful_turn() -> None:
    with isolated_sigil_state():
        record_turn("uv run pytest", 1, os.getcwd(), stderr_snippet="failed")
        record_turn("git status --short", 0, os.getcwd())
        status = current_status()

    assert status.state == "clean"


def test_status_reports_failed_sigil_execution() -> None:
    with isolated_sigil_state(session_id="status-session"):
        append_event(
            {
                "type": "operator_command_executed",
                "operator": {"glyph": ",,"},
                "status": 2,
                "command": "uv run pytest",
            }
        )
        status = current_status()

    assert status.reason == "last Sigil action failed"
    assert status.actions == ("sigil events",)


def test_status_cli_is_public_surface() -> None:
    with isolated_sigil_state():
        result = CliRunner().invoke(cli, ["status"])

    assert result.exit_code == 0
    assert result.output == "clean\n"


class isolated_sigil_state:
    def __init__(self, session_id: str = "status-test") -> None:
        self.session_id = session_id
        self.tmp: tempfile.TemporaryDirectory[str] | None = None
        self.old_state_dir: str | None = None
        self.old_session_id: str | None = None

    def __enter__(self) -> Path:
        self.tmp = tempfile.TemporaryDirectory()
        self.old_state_dir = os.environ.get("SIGIL_STATE_DIR")
        self.old_session_id = os.environ.get("SIGIL_SESSION_ID")
        os.environ["SIGIL_STATE_DIR"] = self.tmp.name
        os.environ["SIGIL_SESSION_ID"] = self.session_id
        return Path(self.tmp.name)

    def __exit__(self, *args: object) -> None:
        if self.old_state_dir is None:
            os.environ.pop("SIGIL_STATE_DIR", None)
        else:
            os.environ["SIGIL_STATE_DIR"] = self.old_state_dir
        if self.old_session_id is None:
            os.environ.pop("SIGIL_SESSION_ID", None)
        else:
            os.environ["SIGIL_SESSION_ID"] = self.old_session_id
        if self.tmp is not None:
            self.tmp.cleanup()
