"""Small JSON-Schema subset used to validate built-in tool calls."""

from __future__ import annotations

from typing import Any

from .base import ToolSpec


def validate_tool_args(
    specs: dict[str, ToolSpec],
    name: str,
    params: dict[str, Any],
) -> list[str]:
    spec = specs.get(name)
    if spec is None:
        return [f"unknown tool: {name}"]
    return validate_schema(spec.schema, params, path="$")


def validate_schema(schema: dict[str, Any], value: Any, *, path: str) -> list[str]:
    expected_type = schema.get("type")
    if expected_type == "object":
        if not isinstance(value, dict):
            return [f"{path}: expected object"]
        return validate_object(schema, value, path=path)
    if expected_type == "array":
        return validate_array(schema, value, path=path)
    return validate_scalar(expected_type, schema, value, path=path)


def validate_array(schema: dict[str, Any], value: Any, *, path: str) -> list[str]:
    if not isinstance(value, list):
        return [f"{path}: expected array"]
    item_schema = schema.get("items")
    if not isinstance(item_schema, dict):
        return []
    errors: list[str] = []
    for index, item in enumerate(value):
        errors.extend(validate_schema(item_schema, item, path=f"{path}[{index}]"))
    return errors


def validate_scalar(
    expected_type: Any,
    schema: dict[str, Any],
    value: Any,
    *,
    path: str,
) -> list[str]:
    if expected_type == "string":
        return [] if isinstance(value, str) else [f"{path}: expected string"]
    if expected_type == "integer":
        return validate_integer(schema, value, path=path)
    if expected_type == "boolean":
        return [] if isinstance(value, bool) else [f"{path}: expected boolean"]
    return []


def validate_integer(schema: dict[str, Any], value: Any, *, path: str) -> list[str]:
    if not isinstance(value, int) or isinstance(value, bool):
        return [f"{path}: expected integer"]
    minimum = schema.get("minimum")
    if isinstance(minimum, int | float) and value < minimum:
        return [f"{path}: expected integer >= {minimum}"]
    return []


def validate_object(
    schema: dict[str, Any],
    value: dict[str, Any],
    *,
    path: str,
) -> list[str]:
    errors: list[str] = []
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        properties = {}
    required = schema.get("required")
    required_names = required if isinstance(required, list) else []
    for name in required_names:
        if isinstance(name, str) and name not in value:
            errors.append(f"{path}.{name}: missing required property")
    if schema.get("additionalProperties") is False:
        for key in value:
            if key not in properties:
                errors.append(f"{path}.{key}: unexpected property")
    for key, item in value.items():
        property_schema = properties.get(key)
        if isinstance(property_schema, dict):
            errors.extend(validate_schema(property_schema, item, path=f"{path}.{key}"))
    return errors
