"""Registry for built-in Zeta tools."""

from __future__ import annotations

from typing import Any, Literal

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from sigil.tools import bash, edit, grep, ls, query_log, read, write

from .base import ToolImpl, error_result

__all__ = ["ExecutionMode", "ToolRegistry", "registry"]

ExecutionMode = Literal["handoff", "direct"]


class ToolRegistry:
    """Registry for Zeta tools."""

    def __init__(self, *, register_builtins: bool = True) -> None:
        self._tools: dict[str, ToolImpl] = {}
        if register_builtins:
            self.register("bash", ToolImpl(bash.SPEC, bash.run, bash.stage))
            self.register("edit", ToolImpl(edit.SPEC, edit.run, edit.stage))
            self.register("grep", ToolImpl(grep.SPEC, grep.run))
            self.register("ls", ToolImpl(ls.SPEC, ls.run))
            self.register("query_log", ToolImpl(query_log.SPEC, query_log.run))
            self.register("read", ToolImpl(read.SPEC, read.run))
            self.register("write", ToolImpl(write.SPEC, write.run, write.stage))

    def register(self, name: str, tool: ToolImpl) -> None:
        """Register a tool implementation under a model-visible name."""
        if tool.spec.name != name:
            raise ValueError(
                f"tool spec name {tool.spec.name!r} does not match {name!r}"
            )
        if name in self._tools:
            raise ValueError(f"tool {name!r} is already registered")
        self._tools[name] = tool

    def get(self, name: str) -> ToolImpl | None:
        """Get a registered tool implementation by name."""
        return self._tools.get(name)

    def list_tool_names(self) -> list[str]:
        """List registered tool names."""
        return sorted(self._tools)

    def validate_tool_args(self, name: str, params: dict[str, Any]) -> list[str]:
        """Validate params against the tool's JSON Schema."""
        tool = self.get(name)
        if tool is None:
            return [f"unknown tool: {name}"]
        try:
            validator = Draft202012Validator(tool.spec.schema)
        except SchemaError as exc:
            return [f"invalid schema for tool {name}: {exc.message}"]
        errors = sorted(validator.iter_errors(params), key=_validation_error_sort_key)
        return [_format_validation_error(error) for error in errors]

    def run_tool(
        self,
        name: str,
        params: dict[str, Any],
        *,
        execution_mode: ExecutionMode = "handoff",
    ) -> dict[str, Any]:
        """Run one tool call under the staging contract its spec declares.

        Read-only tools always run. Mutating tools run in direct mode; in
        handoff mode they stage their work for review, and a mutating tool
        without a staging implementation is refused.
        """
        tool = self.get(name)
        if tool is None:
            return error_result("unknown-tool", f"unknown tool: {name}")
        if execution_mode == "direct" or not tool.spec.mutates():
            return tool.run(params)
        if tool.stage is None:
            declared = ", ".join(tool.spec.effects) or "undeclared"
            return error_result(
                "staging-unsupported",
                f"tool {name} has effects ({declared}) that cannot be staged "
                "for review; rerun in the do workflow (,,,)",
            )
        return tool.stage(params)


registry = ToolRegistry()


def _validation_error_sort_key(error: ValidationError) -> tuple[str, str]:
    return (_json_path(error.absolute_path), error.message)


def _format_validation_error(error: ValidationError) -> str:
    return f"{_json_path(error.absolute_path)}: {error.message}"


def _json_path(parts: Any) -> str:
    path = "$"
    for part in parts:
        if isinstance(part, int):
            path += f"[{part}]"
        else:
            path += f".{part}"
    return path
