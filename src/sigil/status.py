"""Compact current-session status for shell-native Sigil workflows."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Literal

from .failure import latest_active_failure
from .state import session_id

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

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable status payload."""
        return asdict(self)


def current_status() -> Status:
    """Reduce current session state into the most important live condition."""
    current_session = session_id()
    cwd = os.getcwd()

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
        )

    return Status(
        state="clean",
        reason="clean",
        session_id=current_session,
        cwd=cwd,
        actions=(),
        details={},
    )


def attention(
    reason: str,
    *,
    session: str,
    cwd: str,
    actions: tuple[str, ...],
    details: dict[str, object],
) -> Status:
    """Build an attention status."""
    return Status(
        state="attention",
        reason=reason,
        session_id=session,
        cwd=cwd,
        actions=actions,
        details=details,
    )


def format_status(status: Status) -> str:
    """Render status as terse human-readable terminal text."""
    if status.state == "clean":
        return "clean"

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

    return "\n".join(lines)
