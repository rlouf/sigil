"""Transcript storage and chat-message conversion for Zeta."""

from __future__ import annotations

import json
from typing import Any

from ..protocols import is_shell_handoff_result, is_shell_prompt_handoff
from ..state import append_jsonl, read_jsonl

TRANSCRIPT = "zeta-transcript.jsonl"
DEFAULT_TAIL_LIMIT = 50


def append_transcript(event: dict[str, Any]) -> dict[str, Any]:
    return append_jsonl(TRANSCRIPT, event)


def transcript_tail(limit: int = DEFAULT_TAIL_LIMIT) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    return read_jsonl(TRANSCRIPT)[-limit:]


def transcript_chat_messages(
    transcript: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    tool_call_ids: set[str] = set()
    resolved_shell_handoffs = resolved_shell_handoff_call_ids(transcript)
    for index, event in enumerate(transcript):
        message = role_chat_message(event)
        if message is not None:
            messages.append(message)
            continue
        event_type = str(event.get("type") or "")
        message = event_chat_message(event_type, event)
        if message is not None:
            messages.append(message)
            record_tool_call_ids(message, tool_call_ids)
            continue
        if event_type == "tool_call":
            tool_call_id = str(event.get("id") or event.get("tool_call_id") or "")
            if tool_call_id and tool_call_id in tool_call_ids:
                continue
            message = tool_call_message(event, fallback_id=f"call-{index}")
            messages.append(message)
            record_tool_call_ids(message, tool_call_ids)
            continue
        if event_type == "tool_result":
            if is_resolved_shell_prompt_handoff(event, resolved_shell_handoffs):
                continue
            messages.append(tool_result_message(event, tool_call_ids))
    return messages


def resolved_shell_handoff_call_ids(transcript: list[dict[str, Any]]) -> set[str]:
    """Return tool call ids that have a real shell handoff outcome."""
    resolved: set[str] = set()
    for event in transcript:
        if str(event.get("type") or "") != "tool_result":
            continue
        result = event.get("result")
        if not is_shell_handoff_result(result):
            continue
        tool_call_id = str(event.get("tool_call_id") or "")
        if tool_call_id:
            resolved.add(tool_call_id)
    return resolved


def is_resolved_shell_prompt_handoff(
    event: dict[str, Any],
    resolved_shell_handoffs: set[str],
) -> bool:
    """Return whether this staging handoff was superseded by shell output."""
    tool_call_id = str(event.get("tool_call_id") or "")
    if not tool_call_id or tool_call_id not in resolved_shell_handoffs:
        return False
    result = event.get("result")
    if not isinstance(result, dict):
        return False
    return is_shell_prompt_handoff(result.get("handoff"))


def role_chat_message(event: dict[str, Any]) -> dict[str, Any] | None:
    role = str(event.get("role") or "")
    if role not in {"user", "assistant"}:
        return None
    content = str(event.get("content") or "")
    if not content:
        return None
    return {"role": role, "content": content}


def event_chat_message(
    event_type: str,
    event: dict[str, Any],
) -> dict[str, Any] | None:
    role_by_type = {
        "user_message": "user",
        "assistant_message": "assistant",
    }
    role = role_by_type.get(event_type)
    if role is None:
        return None
    content = str(event.get("content") or "")
    tool_calls = event.get("tool_calls")
    if isinstance(tool_calls, list) and role == "assistant":
        return {
            "role": "assistant",
            "content": content or None,
            "tool_calls": tool_calls,
        }
    if not content:
        return None
    return {"role": role, "content": content}


def record_tool_call_ids(
    message: dict[str, Any],
    tool_call_ids: set[str],
) -> None:
    tool_calls = message.get("tool_calls")
    if not isinstance(tool_calls, list):
        return
    for call in tool_calls:
        if isinstance(call, dict):
            tool_call_ids.add(str(call.get("id") or ""))


def tool_call_message(
    event: dict[str, Any],
    *,
    fallback_id: str,
) -> dict[str, Any]:
    tool_call_id = str(event.get("id") or event.get("tool_call_id") or fallback_id)
    tool_name = str(event.get("name") or "")
    tool_input = event.get("input")
    if not isinstance(tool_input, dict):
        tool_input = {}
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": tool_call_id,
                "type": "function",
                "function": {
                    "name": tool_name,
                    "arguments": json.dumps(
                        tool_input,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                },
            }
        ],
    }


def tool_result_message(
    event: dict[str, Any],
    tool_call_ids: set[str],
) -> dict[str, Any]:
    tool_call_id = str(event.get("tool_call_id") or "")
    if tool_call_id and tool_call_id in tool_call_ids:
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": json.dumps(
                event.get("result") or {},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        }
    return {
        "role": "user",
        "content": "Tool result JSON:\n"
        + json.dumps(event, ensure_ascii=False, separators=(",", ":")),
    }
