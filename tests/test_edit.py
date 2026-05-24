from __future__ import annotations

import json
import os
import subprocess
import tempfile
from io import StringIO
from pathlib import Path

from click.testing import CliRunner

from _patch import patch, patch_dict
from sigil.cli import cli
from sigil.edit import edit_file, open_diff, validate_target


def fake_pi_and_editor(proposal: Path, replacement: str, calls: list[list[str]]):
    def run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        del kwargs
        calls.append(cmd)
        if cmd[0] == "pi":
            proposal.write_text(replacement, encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(cmd, 0)

    return run


def test_validate_target_rejects_binary_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "data.bin"
        path.write_bytes(b"abc\x00def")

        try:
            validate_target(path)
        except ValueError as error:
            assert "binary" in str(error)
        else:
            raise AssertionError("expected binary file rejection")


def test_edit_file_opens_diff_and_cancels_without_modifying_original() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        target = root / "example.py"
        target.write_text("value = 1\n", encoding="utf-8")
        state = root / "state"
        calls: list[list[str]] = []

        with patch_dict(
            os.environ, {"SIGIL_STATE_DIR": str(state), "SIGIL_SESSION_ID": "edit-test"}
        ):
            with patch("sigil.edit.start_qwen_for_pi", return_value=True):
                with patch(
                    "sigil.edit.make_proposal_path", return_value=root / "proposal.py"
                ):
                    with patch(
                        "sigil.edit.subprocess.run",
                        side_effect=fake_pi_and_editor(
                            root / "proposal.py", "value = 2\n", calls
                        ),
                    ):
                        with patch("sigil.edit.sys.stdin", StringIO("n\n")):
                            result = edit_file(target, "set value to two")

        assert not result.applied
        assert target.read_text(encoding="utf-8") == "value = 1\n"
        assert calls[0][0] == "pi"
        assert calls[0][calls[0].index("--tools") + 1] == "read,edit"
        assert calls[1] == [
            "nvim",
            "-d",
            str(target.resolve()),
            str(root / "proposal.py"),
        ]


def test_edit_file_yes_applies_reviewed_proposal() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        target = root / "example.py"
        target.write_text("value = 1\n", encoding="utf-8")
        state = root / "state"
        calls: list[list[str]] = []

        with patch_dict(
            os.environ, {"SIGIL_STATE_DIR": str(state), "SIGIL_SESSION_ID": "edit-test"}
        ):
            with patch("sigil.edit.start_qwen_for_pi", return_value=True):
                with patch(
                    "sigil.edit.make_proposal_path", return_value=root / "proposal.py"
                ):
                    with patch(
                        "sigil.edit.subprocess.run",
                        side_effect=fake_pi_and_editor(
                            root / "proposal.py", "value = 2\n", calls
                        ),
                    ):
                        result = edit_file(target, "set value to two", yes=True)

        assert result.applied
        assert target.read_text(encoding="utf-8") == "value = 2\n"
        events = [
            json.loads(line)
            for line in (state / "events.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        assert [event["type"] for event in events] == [
            "file_edit_proposed",
            "file_edit_applied",
        ]
        assert events[1]["capability"] == "write_boxed"


def test_edit_file_refuses_if_pi_modifies_source_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        target = root / "example.py"
        target.write_text("value = 1\n", encoding="utf-8")
        state = root / "state"

        def run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            del kwargs
            if cmd[0] == "pi":
                target.write_text("value = 99\n", encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with patch_dict(
            os.environ, {"SIGIL_STATE_DIR": str(state), "SIGIL_SESSION_ID": "edit-test"}
        ):
            with patch("sigil.edit.start_qwen_for_pi", return_value=True):
                with patch(
                    "sigil.edit.make_proposal_path", return_value=root / "proposal.py"
                ):
                    with patch("sigil.edit.subprocess.run", side_effect=run):
                        try:
                            edit_file(target, "set value to two")
                        except RuntimeError as error:
                            assert "modified the source file" in str(error)
                        else:
                            raise AssertionError("expected source modification refusal")


def test_open_diff_honors_editor_override() -> None:
    calls: list[list[str]] = []

    def run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        del kwargs
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        original = root / "a.py"
        proposed = root / "b.py"
        original.write_text("a\n", encoding="utf-8")
        proposed.write_text("b\n", encoding="utf-8")
        with patch("sigil.edit.subprocess.run", side_effect=run):
            assert open_diff(original, proposed, "nvim --clean") == 0

    assert calls == [["nvim", "--clean", "-d", str(original), str(proposed)]]


def test_edit_cli_json_reports_cancelled_result() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        target = root / "example.py"
        target.write_text("value = 1\n", encoding="utf-8")
        state = root / "state"
        calls: list[list[str]] = []

        with patch_dict(
            os.environ, {"SIGIL_STATE_DIR": str(state), "SIGIL_SESSION_ID": "edit-test"}
        ):
            with patch("sigil.edit.start_qwen_for_pi", return_value=True):
                with patch(
                    "sigil.edit.make_proposal_path", return_value=root / "proposal.py"
                ):
                    with patch(
                        "sigil.edit.subprocess.run",
                        side_effect=fake_pi_and_editor(
                            root / "proposal.py", "value = 2\n", calls
                        ),
                    ):
                        result = CliRunner().invoke(
                            cli,
                            ["edit", str(target), "set value to two", "--json"],
                            input="n\n",
                        )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["applied"] is False
        assert target.read_text(encoding="utf-8") == "value = 1\n"
