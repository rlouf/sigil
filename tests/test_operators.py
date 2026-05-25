from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from sigil.cli import cli
from sigil.operators import create_invocation, parse_operator_token


@pytest.mark.parametrize(
    ("token", "base", "depth"),
    [
        ("?", "?", 1),
        ("??", "?", 2),
        ("^^^", "^", 3),
        (",,", ",", 2),
    ],
)
def test_parse_operator_token_repetition(
    token: str,
    base: str,
    depth: int,
) -> None:
    assert parse_operator_token(token) == (base, depth)


@pytest.mark.parametrize("token", ["", "?^", "?:", "abc", ":"])
def test_parse_operator_token_rejects_invalid_tokens(token: str) -> None:
    with pytest.raises(ValueError):
        parse_operator_token(token)


def test_create_invocation_names_operator() -> None:
    invocation = create_invocation(
        "??",
        prompt="review risky changes",
        stdin="diff",
        mode="pipeline",
    )
    assert invocation.base == "?"
    assert invocation.depth == 2
    assert invocation.name == "inspect"
    assert invocation.prompt == "review risky changes"
    assert invocation.stdin == "diff"
    assert invocation.mode == "pipeline"


def test_op_cli_json_reports_parsed_invocation() -> None:
    result = CliRunner().invoke(
        cli,
        ["op", "--json", "??", "review", "risky", "changes"],
        input="diff --git a/file b/file\n",
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload == {
        "glyph": "??",
        "base": "?",
        "depth": 2,
        "name": "inspect",
        "prompt": "review risky changes",
        "stdin": "diff --git a/file b/file\n",
        "mode": "pipeline",
    }


def test_op_cli_rejects_mixed_glyphs() -> None:
    result = CliRunner().invoke(cli, ["op", "?^"])
    assert result.exit_code == 2
    assert "operator token must repeat one glyph" in result.output


def test_op_cli_rejects_transform_until_colon_operator_exists() -> None:
    result = CliRunner().invoke(cli, ["op", ":json"])
    assert result.exit_code == 2
    assert "unsupported operator: :" in result.output
