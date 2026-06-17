"""Turn/effect history derived from durable events."""

from __future__ import annotations

import os
import re
import time
from collections.abc import Mapping
from typing import Any, cast

from .events import Event, time_from_timestamp_micros

SINCE_PATTERN = re.compile(r"(\d+)([dhm])")
SINCE_SCALES = {"d": 86400, "h": 3600, "m": 60}
EFFECT_RECORD_SCHEMA = "sigil.effect"


class UnknownTurnError(LookupError):
    """A turn id token matched no record or prefix."""

    def __init__(self, token: str) -> None:
        super().__init__(token)
        self.token = token


class AmbiguousTurnError(LookupError):
    """A turn id prefix matched more than one record."""

    def __init__(self, token: str, candidates: list[str]) -> None:
        super().__init__(token)
        self.token = token
        self.candidates = candidates


def parse_since(value: str) -> float:
    """Parse a YYYY-MM-DD date or an age like 2d/6h/30m into an epoch bound."""
    relative = SINCE_PATTERN.fullmatch(value.strip())
    if relative is not None:
        return time.time() - int(relative.group(1)) * SINCE_SCALES[relative.group(2)]
    return time.mktime(time.strptime(value.strip(), "%Y-%m-%d"))


def touched_path_variants(path: str) -> tuple[str, ...]:
    """Return the path as given plus its absolute form, deduplicated."""
    variants = [path]
    absolute = os.path.abspath(path)
    if absolute not in variants:
        variants.append(absolute)
    return tuple(variants)


def resolve_turn_id(index: HistoryIndex, token: str) -> str:
    """Resolve a full turn id or unique prefix, or raise with candidates."""
    if index.turn(token) is not None:
        return token
    matches = index.turn_ids_with_prefix(token)
    if len(matches) == 1:
        return matches[0]
    if matches:
        raise AmbiguousTurnError(token, matches)
    raise UnknownTurnError(token)


class HistoryIndex:
    """Derived turn/effect history over durable events."""

    def __init__(self, events: list[Event]) -> None:
        self._events = events

    def _turns_by_id(self) -> dict[str, dict[str, Any]]:
        turns: dict[str, dict[str, Any]] = {}
        for event in self._events:
            if not event.event_type.startswith("sigil.turn."):
                continue
            record = history_event_record(event)
            turn_id = str(record.get("turn_id") or "")
            if turn_id:
                turns[turn_id] = record
        return turns

    def _effects_by_id(self) -> dict[str, dict[str, Any]]:
        effects: dict[str, dict[str, Any]] = {}
        for event in self._events:
            if event.event_type != "zeta.tool.called":
                continue
            raw_effects = event.payload.get("effects")
            if not isinstance(raw_effects, list):
                continue
            for effect in raw_effects:
                if not is_effect_record(effect):
                    continue
                record = effect_event_record(
                    effect,
                    timestamp=event_time(event),
                    session_id=event.session_id,
                    cwd=event.payload.get("cwd"),
                )
                effect_id = str(record.get("effect_id") or "")
                if effect_id:
                    effects[effect_id] = record
        return effects

    def query_turns(
        self,
        *,
        session: str | None = None,
        workflow: str | None = None,
        since: float | None = None,
        failed: bool = False,
        touched: tuple[str, ...] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return turn records newest first, narrowed by the given filters."""
        touched_turns = self._touched_turn_ids(touched)
        turns = [
            turn
            for turn in self._turns_by_id().values()
            if turn_matches_filters(
                turn,
                session=session,
                workflow=workflow,
                since=since,
                failed=failed,
                touched_turns=touched_turns,
            )
        ]
        turns.sort(key=turn_sort_key, reverse=True)
        return turns[:limit] if limit is not None else turns

    def _touched_turn_ids(self, touched: tuple[str, ...] | None) -> set[str] | None:
        if touched is None:
            return None
        return {
            str(effect.get("turn_id") or "")
            for effect in self._effects_by_id().values()
            if effect.get("path") in touched
        }

    def turn_ids_with_prefix(self, prefix: str, limit: int = 16) -> list[str]:
        """Return turn ids starting with a prefix, sorted, bounded."""
        matches = [
            turn_id for turn_id in self._turns_by_id() if turn_id.startswith(prefix)
        ]
        return sorted(matches)[:limit]

    def pending_staged_command(self, session: str) -> dict[str, Any] | None:
        """Return the newest staged command effect awaiting resolution."""
        effects = list(self._effects_by_id().values())
        resolved_calls = resolved_tool_call_ids(effects)
        candidates = [
            effect
            for effect in effects
            if is_pending_staged_command(
                effect,
                session=session,
                resolved_calls=resolved_calls,
            )
        ]
        candidates.sort(key=effect_sort_key, reverse=True)
        return candidates[0] if candidates else None

    def cost_since(self, session: str, since: float) -> dict[str, int]:
        """Sum the session's turn costs recorded at or after a time."""
        totals = {"input_tokens": 0, "output_tokens": 0, "model_calls": 0, "turns": 0}
        for turn in self.query_turns(session=session, since=since):
            totals["turns"] += 1
            cost = turn.get("cost")
            if not isinstance(cost, dict):
                continue
            totals["input_tokens"] += int(cost.get("input_tokens") or 0)
            totals["output_tokens"] += int(cost.get("output_tokens") or 0)
            totals["model_calls"] += int(cost.get("model_calls") or 0)
        return totals

    def turn(self, turn_id: str) -> dict[str, Any] | None:
        return self._turns_by_id().get(turn_id)

    def effect(self, effect_id: str) -> dict[str, Any] | None:
        return self._effects_by_id().get(effect_id)

    def turns(self, limit: int | None = None) -> list[dict[str, Any]]:
        return self.query_turns(limit=limit)

    def effects(self) -> list[dict[str, Any]]:
        effects = list(self._effects_by_id().values())
        effects.sort(key=effect_sort_key)
        return effects

    def effects_for_turn(self, turn_id: str) -> list[dict[str, Any]]:
        effects = [
            effect
            for effect in self._effects_by_id().values()
            if effect.get("turn_id") == turn_id
        ]
        effects.sort(key=effect_sort_key)
        return effects

    def effects_touching(self, path: str) -> list[dict[str, Any]]:
        effects = [
            effect
            for effect in self._effects_by_id().values()
            if effect.get("path") == path
        ]
        effects.sort(key=effect_sort_key)
        return effects


def is_effect_record(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    record = cast(Mapping[str, Any], value)
    return record.get("schema") == EFFECT_RECORD_SCHEMA


def turn_matches_filters(
    turn: dict[str, Any],
    *,
    session: str | None,
    workflow: str | None,
    since: float | None,
    failed: bool,
    touched_turns: set[str] | None,
) -> bool:
    turn_id = str(turn.get("turn_id") or "")
    checks = (
        optional_match(turn.get("session"), session),
        optional_match(turn.get("workflow"), workflow),
        since is None or float(turn.get("time") or 0.0) >= since,
        not failed or turn.get("outcome") in {"failed", "aborted"},
        touched_turns is None or turn_id in touched_turns,
    )
    return all(checks)


def optional_match(value: Any, expected: Any | None) -> bool:
    return expected is None or value == expected


def turn_sort_key(turn: dict[str, Any]) -> tuple[float, str]:
    return (float(turn.get("time") or 0.0), str(turn.get("turn_id") or ""))


def resolved_tool_call_ids(effects: list[dict[str, Any]]) -> set[str]:
    return {
        str(effect.get("tool_call_id") or "")
        for effect in effects
        if effect.get("resolved_outcome") is not None and effect.get("tool_call_id")
    }


def is_pending_staged_command(
    effect: dict[str, Any],
    *,
    session: str,
    resolved_calls: set[str],
) -> bool:
    tool_call_id = str(effect.get("tool_call_id") or "")
    return (
        effect.get("session") == session
        and effect.get("staged") is True
        and effect.get("kind") == "command"
        and bool(tool_call_id)
        and tool_call_id not in resolved_calls
    )


def effect_sort_key(effect: dict[str, Any]) -> tuple[float, str]:
    return (float(effect.get("time") or 0.0), str(effect.get("effect_id") or ""))


def history_event_record(event: Event) -> dict[str, Any]:
    record = dict(event.payload)
    record.update(
        {
            "id": event.id,
            "type": event.event_type,
            "time": time_from_timestamp_micros(event.timestamp_micros),
        }
    )
    if event.session_id is not None:
        record["session"] = event.session_id
    if event.caused_by is not None:
        record["caused_by"] = event.caused_by
    return record


def effect_event_record(
    record: dict[str, Any],
    *,
    timestamp: float,
    session_id: str | None,
    cwd: Any = None,
) -> dict[str, Any]:
    payload = {"cwd": cwd if isinstance(cwd, str) else os.getcwd(), **record}
    payload["time"] = timestamp
    if session_id is not None:
        payload["session"] = session_id
    return payload


def event_time(event: Event) -> float:
    return time_from_timestamp_micros(event.timestamp_micros)
