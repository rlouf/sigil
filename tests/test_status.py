from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from _zeta_helpers import write_models_config
from click.testing import CliRunner

from sigil.cli import cli
from sigil.session import record_turn
from sigil.status import current_status, format_status
from sigil.zeta.models import set_active_model_profile


def test_status_clean_when_no_live_state() -> None:
    status = current_status()

    assert status.state == "clean"
    assert format_status(status).splitlines()[0] == "clean"


def test_status_clean_shows_model_line(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ZETA_MODEL_NAME", raising=False)
    monkeypatch.delenv("ZETA_MODEL_URL", raising=False)

    status = current_status()

    assert status.model == {
        "profile": "default",
        "model": "local-model",
        "url": "http://127.0.0.1:8080/v1/chat/completions",
        "source": "env",
    }
    assert format_status(status) == (
        "clean\n"
        "model: default -> local-model @ "
        "http://127.0.0.1:8080/v1/chat/completions (env)"
    )


def test_status_model_line_reports_session_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    write_models_config(
        home,
        """
[[models]]
name = "fast"
model = "fast-model"
url = "http://127.0.0.1:8081/v1/chat/completions"
""",
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("SIGIL_SESSION_ID", "status-model")
    set_active_model_profile("fast")

    status = current_status()

    assert status.model["profile"] == "fast"
    assert status.model["source"] == "session"
    assert (
        "model: fast -> fast-model @ http://127.0.0.1:8081/v1/chat/completions "
        "(session)" in format_status(status)
    )


def test_status_reports_last_failure() -> None:
    record_turn("uv run pytest", 1, os.getcwd(), stderr_snippet="failed")
    status = current_status()

    assert status.reason == "last command failed"
    assert status.actions == (", suggest a fix",)
    assert "uv run pytest" in format_status(status)


def test_status_attention_keeps_model_line() -> None:
    record_turn("uv run pytest", 1, os.getcwd(), stderr_snippet="failed")
    status = current_status()
    rendered = format_status(status)

    assert rendered.startswith("attention:")
    assert "\nmodel: " in rendered


def test_status_ignores_stale_failure_after_successful_turn() -> None:
    record_turn("uv run pytest", 1, os.getcwd(), stderr_snippet="failed")
    record_turn("git status --short", 0, os.getcwd())
    status = current_status()

    assert status.state == "clean"


def test_status_cli_is_public_surface() -> None:
    result = CliRunner().invoke(cli, ["status"])

    assert result.exit_code == 0
    assert result.output.splitlines()[0] == "clean"
    assert "model: " in result.output


def test_status_cli_json_includes_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ZETA_MODEL_NAME", raising=False)
    monkeypatch.delenv("ZETA_MODEL_URL", raising=False)

    result = CliRunner().invoke(cli, ["status", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["model"] == {
        "profile": "default",
        "model": "local-model",
        "url": "http://127.0.0.1:8080/v1/chat/completions",
        "source": "env",
    }
