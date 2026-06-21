"""Session resources for Zeta runtime calls."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from zeta.agents.capabilities import AgentConfig
from zeta.kernel.capabilities import ExecutionMode

if TYPE_CHECKING:
    from zeta.capabilities.registry import CapabilityRegistry
    from zeta.store.events import EventStoreProtocol
    from zeta.store.substrate import Store


@dataclass(frozen=True)
class Session:
    """Runtime dependencies for one Zeta host/session."""

    session_id: str
    event_sink: EventStoreProtocol
    trace_store: Store
    tool_registry: CapabilityRegistry
    state_dir: Path
    session_dir: Path


@dataclass
class SessionRequestError(ValueError):
    """Raised when a session-level request cannot be converted into a turn."""

    code: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        super().__init__(self.message)


SessionWorkflow = Literal["ask", "propose", "do"]


@dataclass(frozen=True)
class SessionRunParams:
    objective: str
    workflow: SessionWorkflow = "ask"
    tools: list[str] | None = None
    context: str = ""
    system: str | None = None
    model: str | None = None
    url: str | None = None
    thinking: str | None = None
    api: str | None = None
    max_steps: int | None = None
    max_wall_seconds: float | None = None

    def run_payload(self, run_id: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "objective": self.objective,
            "workflow": self.workflow,
            "runtime": "zeta-rpc",
            "run_id": run_id,
            "tools": list(self.tools or ()),
            "context": self.context,
        }
        for key in (
            "system",
            "model",
            "url",
            "thinking",
            "api",
            "max_steps",
            "max_wall_seconds",
        ):
            value = getattr(self, key)
            if value is not None:
                payload[key] = value
        return payload


def session_run_params(params: dict[str, Any]) -> SessionRunParams:
    """Construct validated session run params without reviving mapping parser methods."""

    try:
        request = SessionRunParams(**params)
    except TypeError as exc:
        raise SessionRequestError(
            "invalid_params",
            f"SessionRunParams parameters are invalid: {exc}",
            {"message": f"SessionRunParams parameters are invalid: {exc}"},
        ) from exc
    if not request.objective:
        raise SessionRequestError(
            "missing_objective",
            "session.run requires objective",
            {"message": "session.run requires objective"},
        )
    if request.workflow not in {"ask", "propose", "do"}:
        raise SessionRequestError(
            "invalid_workflow",
            "workflow must be ask, propose, or do",
            {
                "message": "workflow must be ask, propose, or do",
                "workflow": request.workflow,
            },
        )
    if request.tools is not None:
        for tool in request.tools:
            if not isinstance(tool, str) or not tool:
                raise SessionRequestError(
                    "invalid_tools",
                    "tools must contain non-empty strings",
                    {"message": "tools must contain non-empty strings"},
                )
    return request


def default_session() -> Session:
    """Return the default process session for pure Zeta runtime calls."""

    state_dir = zeta_state_dir()
    session_id = os.environ.get("ZETA_SESSION_ID") or "default"
    return session_for_id(
        session_id=session_id,
        state_dir=state_dir,
        session_dir=state_dir / "sessions" / session_id,
    )


def session_for_id(
    *,
    session_id: str,
    state_dir: Path,
    session_dir: Path,
    tool_registry: CapabilityRegistry | None = None,
) -> Session:
    """Build the default Zeta runtime dependencies for one session."""

    from zeta.store.events import SqliteEventStore, event_store_path
    from zeta.store.substrate import SqliteStore, zeta_sqlite_path

    if tool_registry is None:
        from zeta.capabilities.registry import registry as tool_registry

    return Session(
        session_id=session_id,
        event_sink=SqliteEventStore(event_store_path(state_dir)),
        trace_store=SqliteStore(zeta_sqlite_path(state_dir), session_id=session_id),
        tool_registry=tool_registry,
        state_dir=state_dir,
        session_dir=session_dir,
    )


def zeta_state_dir() -> Path:
    root = os.environ.get("ZETA_STATE_DIR")
    return Path(root).expanduser() if root else Path.home() / ".zeta"


def session_agent_config(
    params: SessionRunParams,
    *,
    enabled_capabilities: tuple[str, ...],
    execution_mode: ExecutionMode,
    session_id: str,
) -> AgentConfig:
    return AgentConfig(
        system_prompt=params.system,
        allowed_capabilities=enabled_capabilities,
        max_turns=params.max_steps,
        stop_on_staged_effect=True,
        execution_mode=execution_mode,
        model_name=params.model,
        model_url=params.url,
        model_session_id=session_id,
        thinking=params.thinking,
        model_api=params.api,
        max_wall_seconds=params.max_wall_seconds,
    )
