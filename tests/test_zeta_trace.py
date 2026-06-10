"""Trace store and run-timeline tests."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from _zeta_helpers import (
    BatchSpyStore,
)
from click.testing import CliRunner

from sigil.cli import cli as sigil_cli
from sigil.zeta import prompt as zeta_prompt
from sigil.zeta import timeline as zeta_timeline
from sigil.zeta import trace as zeta_trace


def test_zeta_trace_object_ids_ignore_dict_key_order() -> None:
    first = zeta_trace.Object(
        kind="example",
        schema="v1",
        data={"b": 1, "a": {"z": 2, "y": [{"b": 3, "a": 4}]}},
    )
    second = zeta_trace.Object(
        kind="example",
        schema="v1",
        data={"a": {"y": [{"a": 4, "b": 3}], "z": 2}, "b": 1},
    )

    assert zeta_trace.object_id(first) == zeta_trace.object_id(second)


def test_zeta_trace_object_ids_change_for_schema_data_and_links() -> None:
    base = zeta_trace.object_id(
        zeta_trace.Object(kind="example", schema="v1", data={"value": 1})
    )

    assert base != zeta_trace.object_id(
        zeta_trace.Object(kind="example", schema="v2", data={"value": 1})
    )
    assert base != zeta_trace.object_id(
        zeta_trace.Object(kind="example", schema="v1", data={"value": 2})
    )
    assert zeta_trace.object_id(
        zeta_trace.Object(
            kind="example",
            schema="v1",
            data={"value": 1},
            links=("left", "right"),
        )
    ) != zeta_trace.object_id(
        zeta_trace.Object(
            kind="example",
            schema="v1",
            data={"value": 1},
            links=("right", "left"),
        )
    )


def test_zeta_trace_sqlite_persists_objects_refs_derivations_and_closure(
    tmp_path: Path,
) -> None:
    path = tmp_path / "trace.sqlite3"
    store = zeta_trace.SqliteStore(path)
    parent_id = store.put_object(
        zeta_trace.Object(kind="context", schema="v1", data={"text": "parent"})
    )
    child_id = store.put_object(
        zeta_trace.Object(
            kind="prompt",
            schema="v1",
            data={"text": "child"},
            links=(parent_id,),
        )
    )
    store.set_ref("prompt/current", child_id)
    store.record_derivation(
        zeta_trace.Derivation(
            producer="test:v1",
            output_id=child_id,
            input_ids=(parent_id,),
            params={"mode": "unit"},
        )
    )
    store.close()

    reopened = zeta_trace.SqliteStore(path)
    assert reopened.get_object(parent_id) == zeta_trace.Object(
        kind="context", schema="v1", data={"text": "parent"}
    )
    assert reopened.get_ref("prompt/current") == child_id
    assert reopened.derivations_for_output(child_id)[0].producer == "test:v1"
    assert set(reopened.graph_closure([child_id])) == {parent_id, child_id}
    assert reopened.stats().object_count == 2
    reopened.close()


def test_zeta_default_store_reuses_one_store_per_path() -> None:
    first = zeta_trace.default_store()
    second = zeta_trace.default_store()

    assert first is second


def test_zeta_default_store_follows_the_session_path(
    monkeypatch,
    tmp_path: Path,
) -> None:
    first = zeta_trace.default_store()
    monkeypatch.setenv("SIGIL_STATE_DIR", str(tmp_path / "other-state"))

    second = zeta_trace.default_store()

    assert second is not first
    assert second.path != first.path


def test_zeta_close_default_stores_closes_connections_and_reopens() -> None:
    store = zeta_trace.default_store()

    zeta_trace.close_default_stores()

    with pytest.raises(sqlite3.ProgrammingError):
        store.connection.execute("SELECT 1")
    reopened = zeta_trace.default_store()
    assert reopened is not store
    assert reopened.get_ref("run/none/head") is None


def test_sigil_zeta_trace_cli_smoke_with_in_memory_store(monkeypatch) -> None:
    store = zeta_trace.InMemoryStore()
    parent_id = store.put_object(
        zeta_trace.Object(kind="context", schema="v1", data={"text": "parent"})
    )
    prompt_id = store.put_object(
        zeta_trace.Object(
            kind="prompt",
            schema="zeta.prompt.v1",
            data={"payload": {"messages": []}},
            links=(parent_id,),
        )
    )
    store.record_derivation(
        zeta_trace.Derivation(
            producer="unit:test",
            output_id=prompt_id,
            input_ids=(parent_id,),
        )
    )
    store.set_ref("prompt/current", prompt_id)
    monkeypatch.setattr("sigil.cli.zeta.default_store", lambda: store)

    runner = CliRunner()
    show = runner.invoke(sigil_cli, ["zeta", "trace", "show", prompt_id])
    closure = runner.invoke(sigil_cli, ["zeta", "trace", "closure", prompt_id])
    refs = runner.invoke(sigil_cli, ["zeta", "trace", "refs"])
    prompts = runner.invoke(sigil_cli, ["zeta", "trace", "prompts"])

    assert show.exit_code == 0
    assert json.loads(show.output)["derivations"][0]["producer"] == "unit:test"
    assert closure.exit_code == 0
    assert json.loads(closure.output)["objects"][0]["id"] == parent_id
    assert refs.exit_code == 0
    assert json.loads(refs.output)["refs"]["prompt/current"] == prompt_id
    assert prompts.exit_code == 0
    assert json.loads(prompts.output)["prompts"][0]["id"] == prompt_id


def test_sigil_zeta_trace_cli_smoke_with_sqlite_store(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = zeta_trace.SqliteStore(tmp_path / "trace.sqlite3")
    prompt_id = store.put_object(
        zeta_trace.Object(kind="prompt", schema="zeta.prompt.v1", data={})
    )
    store.record_derivation(
        zeta_trace.Derivation(producer="unit:test", output_id=prompt_id)
    )
    monkeypatch.setattr("sigil.cli.zeta.default_store", lambda: store)

    result = CliRunner().invoke(sigil_cli, ["zeta", "trace", "prompts"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["stats"]["object_count"] == 1
    assert data["prompts"][0]["id"] == prompt_id
    store.close()


def test_zeta_chat_messages_keeps_full_history_and_current_events() -> None:
    transcript = [{"role": "user", "content": f"prior-{index}"} for index in range(25)]
    current_events = [
        {"type": "assistant_message", "content": f"current-{index}"}
        for index in range(25)
    ]

    messages = zeta_prompt.component_messages(
        zeta_prompt.prompt_components(
            "inspect",
            transcript,
            allowed_tools=(),
            current_events=current_events,
            include_non_message_components=False,
        )
    )
    contents = [str(message.get("content") or "") for message in messages]

    assert "prior-0" in contents
    assert "prior-24" in contents
    assert "Objective:\ninspect" in contents[26]
    assert "current-0" in contents
    assert "current-24" in contents


def test_zeta_prompt_components_keep_only_the_timeline_tail() -> None:
    over_limit = zeta_prompt.TIMELINE_TAIL_LIMIT + 10
    transcript = [
        {"role": "user", "content": f"prior-{index}"} for index in range(over_limit)
    ]

    messages = zeta_prompt.component_messages(
        zeta_prompt.prompt_components(
            "inspect",
            transcript,
            allowed_tools=(),
            include_non_message_components=False,
        )
    )
    contents = [str(message.get("content") or "") for message in messages]

    assert "prior-9" not in contents
    assert "prior-10" in contents
    assert f"prior-{over_limit - 1}" in contents


def test_zeta_timeline_record_and_project(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SIGIL_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("SIGIL_SESSION_ID", "zeta-test")

    zeta_timeline.record_event({"type": "tool_call", "name": "read"})

    events = zeta_timeline.current_timeline()
    assert events[0]["type"] == "tool_call"
    assert events[0]["name"] == "read"
    refs = zeta_trace.default_store().refs()
    assert refs[zeta_timeline.run_head_ref("zeta-test")]
    assert refs[zeta_timeline.event_head_ref("zeta-test")]


def test_zeta_timeline_projects_from_ref_and_object(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SIGIL_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("SIGIL_SESSION_ID", "zeta-test")

    zeta_timeline.record_event({"type": "user_message", "content": "first"})
    store = zeta_trace.default_store()
    first_head = store.get_ref(zeta_timeline.run_head_ref("zeta-test"))
    assert first_head is not None
    store.set_ref("run/custom/head", first_head)

    zeta_timeline.record_event({"type": "assistant_message", "content": "second"})

    assert [
        event["content"] for event in zeta_timeline.timeline_from_ref("run/custom/head")
    ] == ["first"]
    assert [
        event["content"]
        for event in zeta_timeline.timeline_from_ref(
            zeta_timeline.run_head_ref("zeta-test")
        )
    ] == ["first", "second"]
    assert [
        event["content"]
        for event in zeta_timeline.timeline_from_object(first_head, store=store)
    ] == ["first"]
    assert zeta_timeline.timeline_from_ref("run/missing/head") == []


def test_zeta_timeline_last_event_time_tracks_the_newest_event(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SIGIL_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("SIGIL_SESSION_ID", "zeta-test")

    assert zeta_timeline.last_event_time() is None

    first = zeta_timeline.record_event({"type": "user_message", "content": "hi"})
    assert zeta_timeline.last_event_time() == first["time"]

    second = zeta_timeline.record_event({"type": "assistant_message", "content": "yo"})
    assert zeta_timeline.last_event_time() == second["time"]


def test_zeta_timeline_projects_deep_event_chains() -> None:
    store = zeta_trace.InMemoryStore()
    previous = ""
    for index in range(1500):
        previous = store.put_object(
            zeta_trace.Object(
                kind="run_event",
                schema="zeta.run_event.v1",
                data={
                    "event": {"type": "user_message", "content": f"event-{index}"},
                    "previous_event_object_id": previous,
                },
                links=(previous,) if previous else (),
            )
        )

    events = zeta_timeline.timeline_from_object(previous, store=store)

    assert len(events) == 1500
    assert events[0]["content"] == "event-0"
    assert events[-1]["content"] == "event-1499"


def test_zeta_inmemory_store_dedupes_repeated_derivations() -> None:
    store = zeta_trace.InMemoryStore()
    derivation = zeta_trace.Derivation(
        producer="Producer:v1",
        output_id="sha256:out",
        input_ids=("sha256:in",),
    )

    first = store.record_derivation(derivation)
    second = store.record_derivation(derivation)

    assert first == second
    assert len(store.derivations_for_output("sha256:out")) == 1


def test_zeta_orphan_tool_result_rendering_strips_trace_fields() -> None:
    event = {
        "type": "tool_result",
        "tool_call_id": "call-orphan",
        "name": "read",
        "result": {"ok": True, "content": [{"type": "text", "text": "data"}]},
        "tool_result_object_id": "sha256:result",
        "tool_call_object_id": "sha256:call",
        "model_telemetry": {"usage": {"prompt_tokens": 10}},
        "prompt_trace": {"prompt_object_id": "sha256:prompt"},
    }

    messages = zeta_timeline.chat_messages([event])

    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    content = str(messages[0]["content"])
    assert "data" in content
    assert "sha256:" not in content
    assert "model_telemetry" not in content
    assert "prompt_trace" not in content


def test_zeta_chat_messages_repairs_truncated_tool_call_arguments() -> None:
    event = {
        "type": "assistant_message",
        "content": "",
        "tool_calls": [
            {
                "id": "call-0",
                "type": "function",
                "function": {
                    "name": "write",
                    "arguments": '{"path": "doc.md", "content": "cut mid stri',
                },
            }
        ],
    }

    messages = zeta_timeline.chat_messages([event])

    assert len(messages) == 1
    call = messages[0]["tool_calls"][0]
    arguments = json.loads(call["function"]["arguments"])
    assert arguments["truncated_arguments"].startswith('{"path": "doc.md"')
    assert call["id"] == "call-0"
    assert call["function"]["name"] == "write"


def test_zeta_chat_messages_keeps_valid_tool_call_arguments() -> None:
    event = {
        "type": "assistant_message",
        "content": "",
        "tool_calls": [
            {
                "id": "call-0",
                "type": "function",
                "function": {"name": "read", "arguments": '{"path": "doc.md"}'},
            }
        ],
    }

    messages = zeta_timeline.chat_messages([event])

    assert messages[0]["tool_calls"][0]["function"]["arguments"] == (
        '{"path": "doc.md"}'
    )


def test_zeta_sqlite_store_batch_defers_commit(tmp_path: Path) -> None:
    store = zeta_trace.SqliteStore(tmp_path / "trace.sqlite3")
    reader = zeta_trace.SqliteStore(tmp_path / "trace.sqlite3")

    with store.batch():
        object_id = store.put_object(
            zeta_trace.Object(kind="value", schema="v1", data={"n": 1})
        )
        assert reader.get_object(object_id) is None

    assert reader.get_object(object_id) is not None
    store.close()
    reader.close()


def test_zeta_record_event_writes_in_a_single_batch(monkeypatch) -> None:
    store = BatchSpyStore()
    monkeypatch.setattr(zeta_timeline, "default_store", lambda: store)

    zeta_timeline.record_event({"type": "user_message", "content": "hello"})

    assert store.batches == 1


def test_zeta_trace_sqlite_answers_forward_derivation_queries(
    tmp_path: Path,
) -> None:
    store = zeta_trace.SqliteStore(tmp_path / "trace.sqlite3")
    first_input = store.put_object(
        zeta_trace.Object(kind="component", schema="v1", data={"text": "a"})
    )
    second_input = store.put_object(
        zeta_trace.Object(kind="component", schema="v1", data={"text": "b"})
    )
    output = store.put_object(
        zeta_trace.Object(kind="prompt", schema="v1", data={"text": "out"})
    )
    store.record_derivation(
        zeta_trace.Derivation(
            producer="test:v1",
            output_id=output,
            input_ids=(first_input, second_input),
        )
    )

    (derivation,) = store.derivations_for_input(first_input)

    assert derivation.output_id == output
    assert derivation.input_ids == (first_input, second_input)
    assert store.derivations_for_input(output) == []
    store.close()


def test_zeta_inmemory_store_answers_forward_derivation_queries() -> None:
    store = zeta_trace.InMemoryStore()
    store.record_derivation(
        zeta_trace.Derivation(
            producer="test:v1",
            output_id="sha256:out",
            input_ids=("sha256:in",),
        )
    )

    (derivation,) = store.derivations_for_input("sha256:in")

    assert derivation.output_id == "sha256:out"
    assert store.derivations_for_input("sha256:out") == []


def test_zeta_trace_dedupes_forward_rows_for_repeated_derivations(
    tmp_path: Path,
) -> None:
    store = zeta_trace.SqliteStore(tmp_path / "trace.sqlite3")
    derivation = zeta_trace.Derivation(
        producer="test:v1",
        output_id="sha256:out",
        input_ids=("sha256:in", "sha256:in"),
    )

    store.record_derivation(derivation)
    store.record_derivation(derivation)

    assert len(store.derivations_for_input("sha256:in")) == 1
    store.close()


def test_zeta_trace_backfills_derivation_inputs_on_open(tmp_path: Path) -> None:
    path = tmp_path / "trace.sqlite3"
    store = zeta_trace.SqliteStore(path)
    derivation = zeta_trace.Derivation(
        producer="legacy:v1",
        output_id="sha256:out",
        input_ids=("sha256:in",),
    )
    store.connection.execute(
        """
        INSERT INTO derivations
          (id, producer, output_id, input_ids_json, params_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            zeta_trace.derivation_id(derivation),
            derivation.producer,
            derivation.output_id,
            json.dumps(list(derivation.input_ids)),
            "{}",
            1.0,
        ),
    )
    store.connection.commit()
    assert store.derivations_for_input("sha256:in") == []
    store.close()

    reopened = zeta_trace.SqliteStore(path)

    (recovered,) = reopened.derivations_for_input("sha256:in")
    assert recovered.producer == "legacy:v1"
    assert recovered.output_id == "sha256:out"
    reopened.close()


def test_zeta_trace_resolves_refs_full_ids_and_prefixes(tmp_path: Path) -> None:
    store = zeta_trace.SqliteStore(tmp_path / "trace.sqlite3")
    object_id = store.put_object(
        zeta_trace.Object(kind="prompt", schema="v1", data={"text": "target"})
    )
    store.set_ref("prompt/current", object_id)
    digest = object_id.removeprefix("sha256:")

    assert zeta_trace.resolve_object_id(store, "prompt/current") == object_id
    assert zeta_trace.resolve_object_id(store, object_id) == object_id
    assert zeta_trace.resolve_object_id(store, object_id[:15]) == object_id
    assert zeta_trace.resolve_object_id(store, digest[:8]) == object_id
    store.close()


def test_zeta_trace_resolver_prefers_refs_over_prefixes() -> None:
    store = zeta_trace.InMemoryStore()
    obj = zeta_trace.Object(kind="prompt", schema="v1", data={"text": "x"})
    store._objects["sha256:aaaa1111"] = obj
    store._objects["sha256:bbbb2222"] = obj
    store.set_ref("aaaa", "sha256:bbbb2222")

    assert zeta_trace.resolve_object_id(store, "aaaa") == "sha256:bbbb2222"


def test_zeta_trace_resolver_rejects_ambiguous_prefixes() -> None:
    store = zeta_trace.InMemoryStore()
    obj = zeta_trace.Object(kind="prompt", schema="v1", data={"text": "x"})
    store._objects["sha256:aaaa1111"] = obj
    store._objects["sha256:aaaa2222"] = obj

    with pytest.raises(zeta_trace.AmbiguousIdError) as excinfo:
        zeta_trace.resolve_object_id(store, "aaaa")

    assert set(excinfo.value.candidates) == {"sha256:aaaa1111", "sha256:aaaa2222"}


def test_zeta_trace_resolver_raises_for_unknown_tokens() -> None:
    store = zeta_trace.InMemoryStore()

    with pytest.raises(zeta_trace.UnknownIdError):
        zeta_trace.resolve_object_id(store, "missing")
    with pytest.raises(zeta_trace.UnknownIdError):
        zeta_trace.resolve_object_id(store, "")


def test_zeta_trace_prefix_matching_treats_like_wildcards_literally(
    tmp_path: Path,
) -> None:
    store = zeta_trace.SqliteStore(tmp_path / "trace.sqlite3")
    store.put_object(zeta_trace.Object(kind="prompt", schema="v1", data={"n": 1}))

    assert store.object_ids_with_prefix("sha256:%") == []
    assert store.object_ids_with_prefix("sha256:_") == []
    store.close()


def test_zeta_trace_lists_objects_by_derivation_recency(tmp_path: Path) -> None:
    store = zeta_trace.SqliteStore(tmp_path / "trace.sqlite3")
    old = store.put_object(
        zeta_trace.Object(kind="prompt", schema="v1", data={"text": "old"})
    )
    new = store.put_object(
        zeta_trace.Object(kind="prompt", schema="v1", data={"text": "new"})
    )
    underived = store.put_object(
        zeta_trace.Object(kind="component", schema="v1", data={"text": "loose"})
    )
    for output_id, created_at in ((old, 1.0), (new, 2.0)):
        derivation = zeta_trace.Derivation(producer="test:v1", output_id=output_id)
        store.connection.execute(
            """
            INSERT INTO derivations
              (id, producer, output_id, input_ids_json, params_json, created_at)
            VALUES (?, ?, ?, '[]', '{}', ?)
            """,
            (zeta_trace.derivation_id(derivation), "test:v1", output_id, created_at),
        )
    store.connection.commit()

    listed = [object_id for object_id, _ in store.objects()]

    assert listed == [new, old, underived]
    assert [object_id for object_id, _ in store.objects(kind="prompt")] == [new, old]
    assert [object_id for object_id, _ in store.objects(limit=1)] == [new]
    assert store.prompt_object_ids() == [new, old]
    store.close()


def test_zeta_inmemory_store_lists_objects_newest_first() -> None:
    store = zeta_trace.InMemoryStore()
    first = store.put_object(
        zeta_trace.Object(kind="prompt", schema="v1", data={"n": 1})
    )
    second = store.put_object(
        zeta_trace.Object(kind="component", schema="v1", data={"n": 2})
    )
    third = store.put_object(
        zeta_trace.Object(kind="prompt", schema="v1", data={"n": 3})
    )

    assert [object_id for object_id, _ in store.objects()] == [third, second, first]
    assert [object_id for object_id, _ in store.objects(kind="prompt", limit=1)] == [
        third
    ]
    assert store.prompt_object_ids() == [third, first]


def test_sigil_zeta_trace_cli_resolves_refs_and_prefixes(monkeypatch) -> None:
    store = zeta_trace.InMemoryStore()
    prompt_id = store.put_object(
        zeta_trace.Object(kind="prompt", schema="zeta.prompt.v1", data={"n": 1})
    )
    store.set_ref("prompt/current", prompt_id)
    digest_prefix = prompt_id.removeprefix("sha256:")[:8]
    monkeypatch.setattr("sigil.cli.zeta.default_store", lambda: store)

    runner = CliRunner()
    by_ref = runner.invoke(sigil_cli, ["zeta", "trace", "show", "prompt/current"])
    by_prefix = runner.invoke(sigil_cli, ["zeta", "trace", "show", digest_prefix])
    closure = runner.invoke(sigil_cli, ["zeta", "trace", "closure", digest_prefix])

    assert by_ref.exit_code == 0
    assert json.loads(by_ref.output)["id"] == prompt_id
    assert by_prefix.exit_code == 0
    assert json.loads(by_prefix.output)["id"] == prompt_id
    assert closure.exit_code == 0


def test_sigil_zeta_trace_cli_reports_ambiguous_and_unknown_ids(
    monkeypatch,
) -> None:
    store = zeta_trace.InMemoryStore()
    obj = zeta_trace.Object(kind="prompt", schema="v1", data={"n": 1})
    store._objects["sha256:aaaa1111"] = obj
    store._objects["sha256:aaaa2222"] = obj
    monkeypatch.setattr("sigil.cli.zeta.default_store", lambda: store)

    runner = CliRunner()
    ambiguous = runner.invoke(sigil_cli, ["zeta", "trace", "show", "aaaa"])
    unknown = runner.invoke(sigil_cli, ["zeta", "trace", "show", "ffff"])

    assert ambiguous.exit_code != 0
    assert "sha256:aaaa1111" in ambiguous.output
    assert "sha256:aaaa2222" in ambiguous.output
    assert unknown.exit_code != 0
    assert "ffff" in unknown.output
