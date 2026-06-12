"""Delegation ledger index, append-path, and reindex tests."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

import pytest
from click.testing import CliRunner

from sigil import ledger as sigil_ledger
from sigil.cli import cli as sigil_cli
from sigil.protocols import (
    EFFECT_KIND_COMMAND,
    EFFECT_KIND_FILE_WRITE,
    TURN_OUTCOME_EXECUTED,
    TURN_OUTCOME_FAILED,
    effect_record,
    turn_contract,
    turn_record,
)
from sigil.session import clear_current_session, read_event_log
from sigil.state import append_event, session_dir, state_dir


def sample_turn_record(turn_id: str = "turn-1", **overrides: Any) -> dict[str, Any]:
    record = turn_record(
        turn_id,
        workflow="run",
        objective="ls",
        contract=turn_contract("run", (), staged=False),
        outcome=TURN_OUTCOME_EXECUTED,
    )
    record.update(overrides)
    return record


def sample_effect_record(
    effect_id: str = "effect-1",
    turn_id: str = "turn-1",
    **overrides: Any,
) -> dict[str, Any]:
    record = effect_record(
        effect_id,
        turn_id=turn_id,
        kind=EFFECT_KIND_COMMAND,
        staged=False,
        command="ls",
        exit_status=0,
    )
    record.update(overrides)
    return record


def test_ledger_append_turn_record_writes_log_and_index() -> None:
    payload = sigil_ledger.append_turn_record(sample_turn_record())

    (event,) = read_event_log()
    assert event == payload
    assert sigil_ledger.default_ledger_index().turn("turn-1") == payload


def test_ledger_append_effect_record_writes_log_and_index() -> None:
    payload = sigil_ledger.append_effect_record(sample_effect_record())

    (event,) = read_event_log()
    assert event == payload
    index = sigil_ledger.default_ledger_index()
    assert index.effects_for_turn("turn-1") == [payload]


def test_ledger_index_upserts_converge_on_one_row_per_id() -> None:
    index = sigil_ledger.default_ledger_index()
    first = append_event(sample_turn_record())
    index.index_record(first)
    index.index_record(first)
    replaced = dict(first)
    replaced["outcome"] = TURN_OUTCOME_FAILED
    index.index_record(replaced)

    (row,) = index.turns()
    assert row["outcome"] == TURN_OUTCOME_FAILED


def test_ledger_index_ignores_non_ledger_events() -> None:
    index = sigil_ledger.default_ledger_index()

    assert index.index_record({"type": "user_message", "content": "hi"}) is False
    assert index.turns() == []


def test_ledger_turns_lists_newest_first_and_honors_limit() -> None:
    index = sigil_ledger.default_ledger_index()
    index.index_record(append_event(sample_turn_record("turn-old", time=100.0)))
    index.index_record(append_event(sample_turn_record("turn-new", time=200.0)))

    listed = index.turns()
    assert [row["turn_id"] for row in listed] == ["turn-new", "turn-old"]
    assert [row["turn_id"] for row in index.turns(limit=1)] == ["turn-new"]


def test_ledger_effects_touching_filters_by_exact_path() -> None:
    index = sigil_ledger.default_ledger_index()
    touched = append_event(
        sample_effect_record(
            "effect-1",
            kind=EFFECT_KIND_FILE_WRITE,
            path="a.txt",
        )
    )
    index.index_record(touched)
    index.index_record(
        append_event(
            sample_effect_record(
                "effect-2",
                kind=EFFECT_KIND_FILE_WRITE,
                path="b.txt",
            )
        )
    )

    assert index.effects_touching("a.txt") == [touched]
    assert index.effects_touching("missing.txt") == []


def test_ledger_default_index_is_cached_and_reopens_after_close() -> None:
    first = sigil_ledger.default_ledger_index()

    assert sigil_ledger.default_ledger_index() is first

    sigil_ledger.close_ledger_indexes()
    with pytest.raises(sqlite3.ProgrammingError):
        first.connection.execute("SELECT 1")
    assert sigil_ledger.default_ledger_index() is not first


def test_ledger_append_survives_index_failure(monkeypatch) -> None:
    def broken_index() -> sigil_ledger.LedgerIndex:
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(sigil_ledger, "_WARNED_FAILURES", set())
    monkeypatch.setattr(sigil_ledger, "default_ledger_index", broken_index)

    payload = sigil_ledger.append_turn_record(sample_turn_record())

    (event,) = read_event_log()
    assert event == payload


def test_ledger_reindex_reads_both_log_generations() -> None:
    append_event(sample_turn_record("turn-old", time=100.0))
    append_event(sample_effect_record("effect-old", turn_id="turn-old"))
    log_path = state_dir() / "events.jsonl"
    log_path.replace(log_path.with_name("events.jsonl.1"))
    append_event(sample_turn_record("turn-new", time=200.0))
    append_event({"type": "user_message", "content": "not a ledger record"})

    counts = sigil_ledger.reindex()

    assert counts == (2, 1)
    index = sigil_ledger.default_ledger_index()
    assert [row["turn_id"] for row in index.turns()] == ["turn-new", "turn-old"]
    assert index.effects_for_turn("turn-old")[0]["effect_id"] == "effect-old"


def test_ledger_reindex_is_idempotent() -> None:
    append_event(sample_turn_record())
    append_event(sample_effect_record())

    first = sigil_ledger.reindex()
    second = sigil_ledger.reindex()

    assert first == second == (1, 1)
    index = sigil_ledger.default_ledger_index()
    assert len(index.turns()) == 1
    assert len(index.effects_for_turn("turn-1")) == 1


def test_ledger_query_turns_filters_workflow_outcome_and_since() -> None:
    index = sigil_ledger.default_ledger_index()
    index.index_record(
        append_event(sample_turn_record("turn-ask", workflow="ask", time=100.0))
    )
    index.index_record(
        append_event(
            sample_turn_record(
                "turn-broken",
                workflow="do",
                outcome=TURN_OUTCOME_FAILED,
                time=200.0,
            )
        )
    )
    index.index_record(
        append_event(sample_turn_record("turn-run", workflow="run", time=300.0))
    )

    assert [row["turn_id"] for row in index.query_turns(workflow="ask")] == ["turn-ask"]
    assert [row["turn_id"] for row in index.query_turns(failed=True)] == ["turn-broken"]
    assert [row["turn_id"] for row in index.query_turns(since=250.0)] == ["turn-run"]
    assert [row["turn_id"] for row in index.query_turns(limit=2)] == [
        "turn-run",
        "turn-broken",
    ]


def test_ledger_query_turns_scopes_by_session_and_touched_path() -> None:
    index = sigil_ledger.default_ledger_index()
    index.index_record(
        append_event(sample_turn_record("turn-here", time=100.0)) | {"session": "here"}
    )
    index.index_record(
        append_event(sample_turn_record("turn-there", time=200.0))
        | {"session": "there"}
    )
    index.index_record(
        append_event(
            sample_effect_record(
                "effect-write",
                turn_id="turn-here",
                kind=EFFECT_KIND_FILE_WRITE,
                path="notes.txt",
            )
        )
    )

    assert [row["turn_id"] for row in index.query_turns(session="there")] == [
        "turn-there"
    ]
    assert [row["turn_id"] for row in index.query_turns(touched=("notes.txt",))] == [
        "turn-here"
    ]
    assert index.query_turns(touched=("missing.txt",)) == []


def test_ledger_turn_ids_with_prefix_lists_matches_sorted() -> None:
    index = sigil_ledger.default_ledger_index()
    index.index_record(append_event(sample_turn_record("aaaa-1111")))
    index.index_record(append_event(sample_turn_record("aaaa-2222")))
    index.index_record(append_event(sample_turn_record("bbbb-3333")))

    assert index.turn_ids_with_prefix("aaaa") == ["aaaa-1111", "aaaa-2222"]
    assert index.turn_ids_with_prefix("bbbb-3333") == ["bbbb-3333"]
    assert index.turn_ids_with_prefix("cccc") == []


def test_ledger_pending_staged_command_clears_on_resolution(monkeypatch) -> None:
    monkeypatch.setenv("SIGIL_SESSION_ID", "pending-test")
    index = sigil_ledger.default_ledger_index()
    index.index_record(
        append_event(
            sample_effect_record(
                "effect-staged",
                staged=True,
                tool_call_id="call-1",
                command="uv run pytest",
            )
        )
    )

    pending = index.pending_staged_command("pending-test")
    assert pending is not None
    assert pending["command"] == "uv run pytest"
    assert index.pending_staged_command("other-session") is None

    index.index_record(
        append_event(
            sample_effect_record(
                "effect-resolved",
                kind="handoff",
                tool_call_id="call-1",
                resolved_outcome="executed",
            )
        )
    )

    assert index.pending_staged_command("pending-test") is None


def test_ledger_cost_since_sums_session_turns(monkeypatch) -> None:
    monkeypatch.setenv("SIGIL_SESSION_ID", "cost-test")
    index = sigil_ledger.default_ledger_index()
    index.index_record(
        append_event(
            sample_turn_record(
                "turn-early",
                time=100.0,
                cost={"input_tokens": 10, "output_tokens": 5, "model_calls": 1},
            )
        )
    )
    index.index_record(
        append_event(
            sample_turn_record(
                "turn-late",
                time=300.0,
                cost={"input_tokens": 100, "output_tokens": 50, "model_calls": 2},
            )
        )
    )

    today = index.cost_since("cost-test", 200.0)
    assert today == {
        "input_tokens": 100,
        "output_tokens": 50,
        "model_calls": 2,
        "turns": 1,
    }
    everything = index.cost_since("cost-test", 0.0)
    assert everything["turns"] == 2
    assert everything["input_tokens"] == 110


def seed_log_cli_index(monkeypatch) -> None:
    monkeypatch.setenv("SIGIL_SESSION_ID", "log-cli")
    index = sigil_ledger.default_ledger_index()
    index.index_record(
        append_event(
            sample_turn_record(
                "turn-do-1111",
                workflow="do",
                objective="refactor the staging path",
                time=100.0,
                cost={"input_tokens": 1000, "output_tokens": 200, "model_calls": 3},
            )
        )
    )
    index.index_record(
        append_event(
            sample_turn_record(
                "turn-ask-222",
                workflow="ask",
                objective="why did the test fail?",
                outcome=TURN_OUTCOME_FAILED,
                time=200.0,
            )
        )
    )
    index.index_record(
        append_event(
            sample_turn_record(
                "turn-elsewhere",
                workflow="run",
                objective="ls",
                time=300.0,
            )
        )
        | {"session": "elsewhere"}
    )


def test_sigil_log_lists_every_session_newest_first(monkeypatch) -> None:
    seed_log_cli_index(monkeypatch)

    result = CliRunner().invoke(sigil_cli, ["log"])

    assert result.exit_code == 0
    lines = result.output.splitlines()
    assert len(lines) == 3
    assert lines[0].startswith("turn-els")
    assert "elsewhere" in lines[0]
    assert lines[1].startswith("turn-ask")
    assert "log-cli" in lines[1]
    assert "why did the test fail?" in lines[1]
    assert lines[2].startswith("turn-do-")


def test_sigil_log_filters_workflow_failed_and_sessions(monkeypatch) -> None:
    seed_log_cli_index(monkeypatch)
    runner = CliRunner()

    by_workflow = runner.invoke(sigil_cli, ["log", "--workflow", "do"])
    by_failed = runner.invoke(sigil_cli, ["log", "--failed"])
    elsewhere = runner.invoke(sigil_cli, ["log", "--session", "elsewhere"])
    legacy_flag = runner.invoke(sigil_cli, ["log", "--all-sessions"])

    assert by_workflow.exit_code == 0
    assert len(by_workflow.output.splitlines()) == 1
    assert "refactor the staging path" in by_workflow.output
    assert by_failed.exit_code == 0
    assert len(by_failed.output.splitlines()) == 1
    assert "why did the test fail?" in by_failed.output
    assert len(elsewhere.output.splitlines()) == 1
    assert "ls" in elsewhere.output
    assert "elsewhere" not in by_workflow.output
    assert legacy_flag.exit_code != 0


def test_sigil_log_session_filter_omits_the_session_column(monkeypatch) -> None:
    seed_log_cli_index(monkeypatch)

    result = CliRunner().invoke(sigil_cli, ["log", "--session", "log-cli"])

    assert result.exit_code == 0
    lines = result.output.splitlines()
    assert len(lines) == 2
    assert all("log-cli" not in line for line in lines)


def test_sigil_log_renders_cost_and_json(monkeypatch) -> None:
    seed_log_cli_index(monkeypatch)
    runner = CliRunner()

    with_cost = runner.invoke(sigil_cli, ["log", "--cost"])
    as_json = runner.invoke(sigil_cli, ["log", "--json"])

    assert with_cost.exit_code == 0
    assert "1200 tok" in with_cost.output
    assert "3 calls" in with_cost.output
    assert as_json.exit_code == 0
    payload = json.loads(as_json.output)
    assert [turn["turn_id"] for turn in payload["turns"]] == [
        "turn-elsewhere",
        "turn-ask-222",
        "turn-do-1111",
    ]


def test_sigil_log_touched_filter_finds_writing_turn(monkeypatch) -> None:
    seed_log_cli_index(monkeypatch)
    index = sigil_ledger.default_ledger_index()
    index.index_record(
        append_event(
            sample_effect_record(
                "effect-write",
                turn_id="turn-do-1111",
                kind=EFFECT_KIND_FILE_WRITE,
                path="/tmp/notes.txt",
            )
        )
    )

    result = CliRunner().invoke(sigil_cli, ["log", "--touched", "/tmp/notes.txt"])

    assert result.exit_code == 0
    assert len(result.output.splitlines()) == 1
    assert result.output.startswith("turn-do-")


def test_sigil_log_empty_ledger_prints_friendly_line(monkeypatch) -> None:
    monkeypatch.setenv("SIGIL_SESSION_ID", "empty-session")

    result = CliRunner().invoke(sigil_cli, ["log"])

    assert result.exit_code == 0
    assert "no turns recorded" in result.output


def seed_show_and_blame_index(monkeypatch) -> None:
    monkeypatch.setenv("SIGIL_SESSION_ID", "show-cli")
    index = sigil_ledger.default_ledger_index()
    record = turn_record(
        "turn-do-1111",
        workflow="do",
        objective="refactor the staging path",
        contract=turn_contract("do", ("read", "edit", "bash"), staged=False),
        outcome=TURN_OUTCOME_EXECUTED,
        agent={"model": "qwen2.5-coder", "url": "http://127.0.0.1:8080/v1"},
        cost={
            "input_tokens": 1000,
            "output_tokens": 200,
            "model_calls": 3,
            "wall_ms": 4200,
        },
        prompt_object_ids=["sha256:" + "70da571d" + "0" * 56],
        effect_ids=["effect-edit"],
    )
    index.index_record(append_event({**record, "time": 100.0}))
    index.index_record(
        append_event(
            sample_effect_record(
                "effect-edit",
                turn_id="turn-do-1111",
                kind="file_edit",
                path="/tmp/notes.txt",
                before_hash="sha256:" + "aa" * 32,
                after_hash="sha256:" + "bb" * 32,
                time=100.0,
            )
        )
    )
    index.index_record(append_event(sample_turn_record("turn-other-22", time=200.0)))


def test_sigil_log_show_renders_the_full_record(monkeypatch) -> None:
    seed_show_and_blame_index(monkeypatch)

    result = CliRunner().invoke(sigil_cli, ["log", "show", "turn-do"])

    assert result.exit_code == 0
    assert "turn     turn-do-1111" in result.output
    assert "workflow do" in result.output
    assert "outcome  executed" in result.output
    assert "refactor the staging path" in result.output
    assert "read, edit, bash" in result.output
    assert "qwen2.5-coder" in result.output
    assert "1200 tok" in result.output
    assert "3 calls" in result.output
    assert "file_edit" in result.output
    assert "/tmp/notes.txt" in result.output
    assert "70da571d" in result.output


def test_sigil_log_show_reports_ambiguous_and_unknown_ids(monkeypatch) -> None:
    seed_show_and_blame_index(monkeypatch)
    runner = CliRunner()

    ambiguous = runner.invoke(sigil_cli, ["log", "show", "turn-"])
    unknown = runner.invoke(sigil_cli, ["log", "show", "nope"])

    assert ambiguous.exit_code != 0
    assert "turn-do-1111" in ambiguous.output
    assert "turn-other-22" in ambiguous.output
    assert unknown.exit_code != 0
    assert "nope" in unknown.output


def test_sigil_log_show_json_emits_record_and_effects(monkeypatch) -> None:
    seed_show_and_blame_index(monkeypatch)

    result = CliRunner().invoke(sigil_cli, ["log", "show", "--json", "turn-do-1111"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["turn"]["turn_id"] == "turn-do-1111"
    assert payload["effects"][0]["effect_id"] == "effect-edit"


def test_sigil_blame_lists_turns_touching_a_file(monkeypatch) -> None:
    seed_show_and_blame_index(monkeypatch)

    result = CliRunner().invoke(sigil_cli, ["blame", "/tmp/notes.txt"])

    assert result.exit_code == 0
    assert "file_edit" in result.output
    assert "do" in result.output
    assert "executed" in result.output
    assert "turn-do-" in result.output
    assert "refactor the staging path" in result.output
    assert "70da571d" in result.output


def test_sigil_blame_reports_untouched_files(monkeypatch) -> None:
    seed_show_and_blame_index(monkeypatch)

    result = CliRunner().invoke(sigil_cli, ["blame", "/tmp/other.txt"])

    assert result.exit_code == 0
    assert "no recorded writes" in result.output


def test_ledger_cli_log_reindex_reports_counts() -> None:
    append_event(sample_turn_record())
    append_event(sample_effect_record())

    result = CliRunner().invoke(sigil_cli, ["log", "reindex"])

    assert result.exit_code == 0
    assert "1 turn record(s)" in result.output
    assert "1 effect record(s)" in result.output
    assert sigil_ledger.default_ledger_index().turn("turn-1") is not None


def test_ledger_survives_session_clear() -> None:
    sigil_ledger.append_turn_record(sample_turn_record())
    root = session_dir()
    root.mkdir(parents=True, exist_ok=True)
    (root / "recent-turns.jsonl").write_text("", encoding="utf-8")

    clear_current_session()

    assert not root.exists()
    assert (state_dir() / "ledger.sqlite3").exists()
    assert (state_dir() / "events.jsonl").exists()
    assert sigil_ledger.default_ledger_index().turn("turn-1") is not None
