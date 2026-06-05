"""Registry for built-in Zeta tools."""

from __future__ import annotations

from typing import Any, Iterable

from . import bash, edit, grep, ls, read, write
from .base import ToolImpl, ToolSpec, diagnostic, error_result
from .schema import validate_tool_args as validate_args_against_schema

TOOL_IMPLS: dict[str, ToolImpl] = {
    bash.SPEC.name: ToolImpl(bash.SPEC, bash.analyze, bash.run),
    edit.SPEC.name: ToolImpl(edit.SPEC, edit.analyze, edit.run),
    grep.SPEC.name: ToolImpl(grep.SPEC, grep.analyze, grep.run),
    ls.SPEC.name: ToolImpl(ls.SPEC, ls.analyze, ls.run),
    read.SPEC.name: ToolImpl(read.SPEC, read.analyze, read.run),
    write.SPEC.name: ToolImpl(write.SPEC, write.analyze, write.run),
}

TOOL_SPECS: dict[str, ToolSpec] = {name: tool.spec for name, tool in TOOL_IMPLS.items()}


def tool_metadata(name: str) -> dict[str, Any]:
    spec = TOOL_SPECS.get(name)
    if spec is None:
        raise KeyError(name)
    return spec.metadata()


def allowed_tool_names(allowed_tools: Iterable[str] | None = None) -> list[str]:
    allowed = set(allowed_tools) if allowed_tools is not None else None
    return [name for name in sorted(TOOL_SPECS) if allowed is None or name in allowed]


def tools_list(allowed_tools: Iterable[str] | None = None) -> dict[str, Any]:
    tools = []
    for name in allowed_tool_names(allowed_tools):
        meta = tool_metadata(name)
        meta["command"] = ["zeta", "tool", name]
        meta["origin"] = "builtin"
        tools.append(meta)
    return {"tools": tools}


def model_tool_descriptors(
    allowed_tools: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """Return provider-facing tool descriptors for the model prompt."""
    descriptors = []
    for name in allowed_tool_names(allowed_tools):
        spec = TOOL_SPECS[name]
        descriptors.append(
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.schema,
                },
            }
        )
    return descriptors


def validate_tool_args(name: str, params: dict[str, Any]) -> list[str]:
    """Validate params against the built-in subset of JSON Schema."""
    return validate_args_against_schema(TOOL_SPECS, name, params)


def analyze_tool(name: str, params: dict[str, Any]) -> dict[str, Any]:
    tool = TOOL_IMPLS.get(name)
    if tool is None:
        return {
            "valid": False,
            "resolved": False,
            "effects": [],
            "diagnostics": [
                diagnostic("unknown-tool", f"unknown tool: {name}", severity="error")
            ],
        }
    return tool.analyze(params)


def run_tool(name: str, params: dict[str, Any]) -> dict[str, Any]:
    tool = TOOL_IMPLS.get(name)
    if tool is None:
        return error_result("unknown-tool", f"unknown tool: {name}")
    return tool.run(params)
