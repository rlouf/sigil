"""Compact current-session status for shell-native Sigil workflows."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Literal

from .session import latest_active_failure
from .state import session_id
from .zeta.models import resolve_active_model

StatusState = Literal["clean", "attention"]


@dataclass(frozen=True)
class Status:
    """Current operational status for the shell session."""

    state: StatusState
    reason: str
    session_id: str
    cwd: str
    actions: tuple[str, ...]
    details: dict[str, object]
    model: dict[str, str]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable status payload."""
        return asdict(self)


def current_status() -> Status:
    """Reduce current session state into the most important live condition."""
    current_session = session_id()
    cwd = os.getcwd()
    model = active_model_fields()

    failure = latest_active_failure()
    if failure is not None:
        return attention(
            "last command failed",
            session=current_session,
            cwd=cwd,
            actions=(", suggest a fix",),
            details={
                "event_id": failure.get("event_id"),
                "command": failure.get("command"),
                "status": failure.get("status"),
                "cwd": failure.get("cwd"),
            },
            model=model,
        )

    return Status(
        state="clean",
        reason="clean",
        session_id=current_session,
        cwd=cwd,
        actions=(),
        details={},
        model=model,
    )


def attention(
    reason: str,
    *,
    session: str,
    cwd: str,
    actions: tuple[str, ...],
    details: dict[str, object],
    model: dict[str, str],
) -> Status:
    """Build an attention status."""
    return Status(
        state="attention",
        reason=reason,
        session_id=session,
        cwd=cwd,
        actions=actions,
        details=details,
        model=model,
    )


def active_model_fields() -> dict[str, str]:
    """Return the resolved model the next request will use, with its source."""
    resolution = resolve_active_model()
    selection = resolution.selection
    return {
        "profile": selection.profile,
        "model": selection.model,
        "url": selection.url,
        "source": resolution.source,
    }


def format_status(status: Status) -> str:
    """Render status as terse human-readable terminal text."""
    if status.state == "clean":
        return "\n".join(["clean", format_model_line(status.model)])

    lines = [f"attention: {status.reason}"]
    details = status.details

    command = details.get("command")
    if command:
        lines.extend(["", "command", f"  {command}"])

    objective = details.get("objective")
    if objective:
        lines.extend(["", "objective", f"  {objective}"])

    if status.actions:
        lines.extend(["", "next"])
        lines.extend(f"  {action}" for action in status.actions)

    lines.extend(["", format_model_line(status.model)])
    return "\n".join(lines)


def format_model_line(model: dict[str, str]) -> str:
    """Render the resolved model selection as one status line."""
    return (
        f"model: {model['profile']} -> {model['model']} "
        f"@ {model['url']} ({model['source']})"
    )
