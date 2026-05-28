"""Render Pi JSON events while preserving structured state.

Pi emits machine-readable events. This filter turns tool calls into live grey
status lines, streams answer text to stdout for `glow`, and writes only the
right pieces into session state: assistant turns to the question transcript and
tool calls to the tool trace.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from typing import TextIO, cast

from .ansi import MUTED, RESET
from .security import normalize_capability, normalize_integrity
from .state import append_event, append_jsonl

TOOL_START_EVENT_TYPES = {
    "tool_execution_start",
    "tool_call",
    "function_call",
}
TOOL_END_EVENT_TYPES = {
    "tool_execution_end",
    "tool_result",
    "tool_call_result",
    "function_call_result",
}


def is_interactive(stream: TextIO) -> bool:
    """Return whether a stream is attached to an interactive terminal."""
    return bool(getattr(stream, "isatty", lambda: False)())


def should_color(stream: TextIO) -> bool:
    """Return whether terminal color should be emitted to a stream."""
    return is_interactive(stream) and "NO_COLOR" not in os.environ


def muted(text: str, *, enabled: bool) -> str:
    """Apply muted terminal styling when color is enabled."""
    if not enabled:
        return text
    return f"{MUTED}{text}{RESET}"


def clear_status(stderr: TextIO) -> None:
    """Erase the transient spinner/status line before printing durable output."""
    stderr.write("\r\033[K")
    stderr.flush()


def summarize(tool: str, args: object) -> str:
    """Extract a short human-readable label for a tool call."""
    if not isinstance(args, dict):
        return ""
    tool_args = cast(dict[str, object], args)
    if tool == "read":
        return str(tool_args.get("path") or tool_args.get("file_path") or "")
    if tool in {"edit", "write"}:
        return str(tool_args.get("path") or tool_args.get("file_path") or "")
    if tool == "bash":
        return str(tool_args.get("command") or tool_args.get("cmd") or "")
    if tool in {"grep", "find", "ls"}:
        return str(
            tool_args.get("pattern")
            or tool_args.get("query")
            or tool_args.get("path")
            or tool_args.get("glob")
            or ""
        )
    if tool == "web_search":
        return str(tool_args.get("query") or tool_args.get("q") or "")
    return " ".join(
        f"{k}={v}"
        for k, v in tool_args.items()
        if isinstance(v, (str, int, float, bool))
    )


def event_payload(event: dict[str, object]) -> dict[str, object]:
    """Return the event object that carries Pi payload fields."""
    update = event.get("assistantMessageEvent")
    if event.get("type") == "message_update" and isinstance(update, dict):
        return cast(dict[str, object], update)
    return event


def event_kind(event: dict[str, object]) -> str:
    """Return the concrete Pi event kind, including nested message updates."""
    payload = event_payload(event)
    return str(payload.get("type") or "")


def tool_name(payload: dict[str, object]) -> str:
    """Extract a tool/function name from known Pi event shapes."""
    for key in ("toolName", "functionName", "name", "tool"):
        value = payload.get(key)
        if value:
            return str(value)
    function = payload.get("function")
    if isinstance(function, dict):
        function_payload = cast(dict[str, object], function)
        name = function_payload.get("name")
        if name:
            return str(name)
    return ""


def tool_args(payload: dict[str, object]) -> object:
    """Extract tool/function arguments from known Pi event shapes."""
    for key in ("args", "input", "arguments"):
        if key in payload:
            return decoded_args(payload.get(key))
    function = payload.get("function")
    if isinstance(function, dict):
        function_payload = cast(dict[str, object], function)
        return decoded_args(function_payload.get("arguments"))
    return None


def decoded_args(value: object) -> object:
    """Decode JSON argument strings used by function-call events."""
    if not isinstance(value, str):
        return value
    try:
        decoded = json.loads(value)
    except Exception:
        return value
    return decoded


def tool_start_event(event: dict[str, object]) -> tuple[str, object] | None:
    """Return normalized tool start data when an event begins a call."""
    payload = event_payload(event)
    if event_kind(event) not in TOOL_START_EVENT_TYPES:
        return None
    name = tool_name(payload)
    if not name:
        return None
    return name, tool_args(payload)


def tool_end_event(event: dict[str, object]) -> str | None:
    """Return a normalized tool name when an event ends a call."""
    payload = event_payload(event)
    if event_kind(event) not in TOOL_END_EVENT_TYPES:
        return None
    return tool_name(payload)


def compact_tool_label(tool: object) -> str:
    """Return the short label used in compact act traces."""
    if tool == "bash":
        return "check"
    if tool == "grep":
        return "search"
    if tool == "ls":
        return "list"
    return str(tool or "tool")


def compact_detail(detail: str, *, limit: int = 120) -> str:
    """Shorten paths and commands for compact terminal display."""
    text = " ".join(detail.split())
    if not text:
        return ""
    try:
        path = os.path.relpath(text, os.getcwd())
    except ValueError:
        path = text
    if not path.startswith(".."):
        text = path
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def compact_answer_summary(answer: str, *, limit: int = 180) -> str:
    """Return a one-line completion summary from Pi's final answer."""
    lines = []
    in_fence = False
    for raw_line in answer.splitlines():
        line = raw_line.strip()
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not line:
            continue
        line = line.strip("*`- ")
        if line.lower().startswith("verification command"):
            break
        lines.append(line)
    start = None
    for index in range(len(lines) - 1, -1, -1):
        lower = lines[index].lower()
        if "all tests pass" in lower or "what changed" in lower:
            start = index
            break
    if start is None:
        for index in range(len(lines) - 1, -1, -1):
            lower = lines[index].lower()
            if lower.startswith(("updated", "changed", "done")):
                start = index
                break
    if start is None:
        selected = lines[-2:]
    else:
        selected = lines[start : start + 3]
    text = " ".join(selected) or "completed"
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def env_security() -> dict[str, object]:
    """Recover trust metadata passed from the parent operator or ask process."""
    taint = [
        item for item in os.environ.get("SIGIL_SECURITY_TAINT", "").split(",") if item
    ]
    inputs = [
        item for item in os.environ.get("SIGIL_SECURITY_INPUTS", "").split(",") if item
    ]
    return {
        "glyph": os.environ.get("SIGIL_SECURITY_GLYPH", "?"),
        "inputs": inputs,
        "integrity": normalize_integrity(os.environ.get("SIGIL_SECURITY_INTEGRITY")),
        "capability": normalize_capability(os.environ.get("SIGIL_SECURITY_CAPABILITY")),
        "taint": taint or ["web"],
        "provisional": os.environ.get("SIGIL_SECURITY_PROVISIONAL") == "1",
    }


def stream_events(
    stdin: TextIO = sys.stdin,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
    *,
    json_output: bool = False,
    compact: bool = False,
) -> int:
    """Filter Pi's event stream into terminal output and Sigil state files."""
    started_text = False
    answer_chunks: list[str] = []
    tool_events: list[dict[str, object]] = []
    malformed_events = 0
    security = env_security()
    interactive_stderr = is_interactive(stderr)
    color_enabled = should_color(stderr)
    spinner_running = not json_output and not compact and interactive_stderr
    spinner_paused = False
    spinner_lock = threading.Lock()
    spinner_thread: threading.Thread | None = None

    def spinner() -> None:
        frames = ["thinking", "thinking.", "thinking..", "thinking..."]
        i = 0
        while True:
            with spinner_lock:
                if not spinner_running:
                    clear_status(stderr)
                    return
                paused = spinner_paused
            if not paused:
                stderr.write(
                    f"\r\033[K{muted(f'❯ {frames[i % len(frames)]}', enabled=color_enabled)}"
                )
                stderr.flush()
                i += 1
            time.sleep(0.35)

    def pause_spinner() -> None:
        nonlocal spinner_paused
        with spinner_lock:
            spinner_paused = True
        clear_status(stderr)

    def resume_spinner() -> None:
        nonlocal spinner_paused
        with spinner_lock:
            if spinner_running:
                spinner_paused = False

    def stop_spinner() -> None:
        nonlocal spinner_running, spinner_paused
        if spinner_thread is None:
            return
        with spinner_lock:
            spinner_running = False
            spinner_paused = False
        spinner_thread.join()

    if spinner_running:
        spinner_thread = threading.Thread(target=spinner, daemon=True)
        spinner_thread.start()

    try:
        for raw_line in stdin:
            try:
                event = json.loads(raw_line)
            except Exception:
                malformed_events += 1
                continue

            tool_start = tool_start_event(event)
            if tool_start is not None:
                if spinner_running:
                    pause_spinner()
                tool, args = tool_start
                detail = summarize(tool, args)
                trace_event = {
                    "type": "tool_start",
                    "tool": tool,
                    "detail": detail,
                    "args": args,
                    **security,
                }
                tool_events.append(trace_event)
                if os.environ.get("SIGIL_CAPTURE_TRACE") == "1":
                    append_jsonl("last-tools.jsonl", trace_event)
                append_event(trace_event)
                if compact and not json_output:
                    label = compact_tool_label(tool)
                    short_detail = compact_detail(detail)
                    status = (
                        f"  {label:<6} {short_detail}" if short_detail else f"  {label}"
                    )
                    print(status, file=stderr, flush=True)
                elif not json_output:
                    status = f"❯ {tool}  {detail}" if detail else f"❯ {tool}"
                    print(
                        muted(status, enabled=color_enabled),
                        file=stderr,
                        flush=True,
                    )
                continue

            tool_end = tool_end_event(event)
            if tool_end is not None:
                trace_event = {
                    "type": "tool_end",
                    "tool": tool_end,
                    **security,
                }
                tool_events.append(trace_event)
                if os.environ.get("SIGIL_CAPTURE_TRACE") == "1":
                    append_jsonl("last-tools.jsonl", trace_event)
                append_event(trace_event)
                if spinner_running:
                    resume_spinner()
                continue

            if event.get("type") != "message_update":
                continue

            update = event.get("assistantMessageEvent") or {}
            if update.get("type") == "text_delta":
                if compact:
                    delta = update.get("delta", "")
                    answer_chunks.append(delta)
                    continue
                if not json_output and not started_text:
                    stop_spinner()
                    stdout.write("\n")
                    started_text = True
                delta = update.get("delta", "")
                answer_chunks.append(delta)
                if not json_output:
                    stdout.write(delta)
                    stdout.flush()
    finally:
        if spinner_running:
            stop_spinner()
        answer = "".join(answer_chunks)
        answer_event_id = None
        if answer:
            answer_event = append_event(
                {
                    "type": "answer_done",
                    "bytes": len(answer.encode("utf-8")),
                    **security,
                }
            )
            answer_event_id = answer_event["id"]
            if os.environ.get("SIGIL_CAPTURE_ANSWER") == "1":
                append_jsonl(
                    "last-question.jsonl",
                    {
                        "role": "assistant",
                        "content": answer,
                        "event_id": answer_event["id"],
                        **security,
                    },
                )
        if json_output:
            stdout.write(
                json.dumps(
                    {
                        "ok": True,
                        "type": "answer",
                        "question": os.environ.get("SIGIL_QUESTION", ""),
                        "prompt": os.environ.get("SIGIL_PROMPT", ""),
                        "follow_up": os.environ.get("SIGIL_FOLLOW_UP") == "1",
                        "answer": answer,
                        "answer_event_id": answer_event_id,
                        "tools": tool_events,
                        "malformed_events": malformed_events,
                        "security": security,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            stdout.flush()
        elif compact:
            stdout.write(f"done: {compact_answer_summary(answer)}\n")
            stdout.flush()
        elif malformed_events:
            noun = "event" if malformed_events == 1 else "events"
            print(
                f"sigil: ignored {malformed_events} malformed Pi {noun}",
                file=stderr,
            )
    return 0
