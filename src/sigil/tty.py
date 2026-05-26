"""Terminal confirmation helpers shared by CLI and operator runtimes."""

from __future__ import annotations

import os
import sys


def confirm_on_tty(prompt: str) -> bool:
    """Read a yes/no confirmation from the controlling terminal."""
    errors = []
    tty_fd = os.environ.get("SIGIL_TTY_FD")
    if tty_fd:
        try:
            fd = os.dup(int(tty_fd))
            try:
                return confirm_on_fd(fd, prompt)
            finally:
                os.close(fd)
        except (OSError, ValueError) as exc:
            errors.append(f"fd {tty_fd}: {exc}")

    tty_paths = confirmation_tty_paths()
    for tty_path in tty_paths:
        try:
            fd = os.open(tty_path, os.O_RDWR)
            try:
                return confirm_on_fd(fd, prompt)
            finally:
                os.close(fd)
        except OSError as exc:
            errors.append(f"{tty_path}: {exc}")
            continue
    tried = [f"fd {tty_fd}"] if tty_fd else []
    tried.extend(tty_paths)
    detail = f"; errors: {'; '.join(errors)}" if errors else ""
    print(
        "sigil: could not open a terminal for confirmation; "
        f"tried {', '.join(tried)}{detail}; declining",
        file=sys.stderr,
    )
    return False


def confirm_on_fd(fd: int, prompt: str) -> bool:
    """Ask for confirmation on an already-open terminal-like file descriptor."""
    os.write(fd, prompt.encode("utf-8"))
    answer = os.read(fd, 1024)
    return answer.strip().lower() in {b"y", b"yes"}


def confirmation_tty_paths() -> list[str]:
    """Return candidate terminal devices for interactive confirmation."""
    paths = []
    for name in ("SIGIL_TTY", "TTY"):
        value = os.environ.get(name)
        if value:
            paths.append(value)
    paths.append("/dev/tty")
    return list(dict.fromkeys(paths))
