from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any


def state_dir() -> Path:
    base = os.environ.get("SIGIL_STATE_DIR")
    if base:
        return Path(base)
    return Path.home() / ".sigil"


def session_id() -> str:
    return os.environ.get("SIGIL_SESSION_ID") or "default"


def session_dir() -> Path:
    base = os.environ.get("SIGIL_SESSION_DIR")
    if base:
        return Path(base)
    return state_dir() / "sessions" / session_id()


def append_event(event: dict[str, Any]) -> None:
    root = state_dir()
    root.mkdir(parents=True, exist_ok=True)
    payload = {
        "id": str(uuid.uuid4()),
        "time": time.time(),
        "cwd": os.getcwd(),
        "session": session_id(),
        **event,
    }
    with (root / "events.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")


def write_json(name: str, value: Any) -> None:
    root = session_dir()
    root.mkdir(parents=True, exist_ok=True)
    tmp = root / f"{name}.tmp"
    final = root / name
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(final)


def append_jsonl(name: str, event: dict[str, Any]) -> None:
    root = session_dir()
    root.mkdir(parents=True, exist_ok=True)
    payload = {
        "id": str(uuid.uuid4()),
        "time": time.time(),
        "cwd": os.getcwd(),
        "session": session_id(),
        **event,
    }
    with (root / name).open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")


def write_jsonl(name: str, events: list[dict[str, Any]]) -> None:
    root = session_dir()
    root.mkdir(parents=True, exist_ok=True)
    tmp = root / f"{name}.tmp"
    final = root / name
    with tmp.open("w", encoding="utf-8") as f:
        for event in events:
            payload = {
                "id": str(uuid.uuid4()),
                "time": time.time(),
                "cwd": os.getcwd(),
                "session": session_id(),
                **event,
            }
            f.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    tmp.replace(final)


def read_jsonl(name: str) -> list[dict[str, Any]]:
    path = session_dir() / name
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except Exception:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def read_json(name: str) -> Any | None:
    path = session_dir() / name
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
