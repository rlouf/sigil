"""Single-file edit proposals reviewed through an external diff editor."""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .ansi import MUTED, RESET
from .security import make_security
from .server import start_qwen_for_pi
from .state import append_event

MAX_EDIT_FILE_BYTES = 128 * 1024
MAX_PROPOSAL_BYTES = 256 * 1024

EDIT_SYSTEM_PROMPT = """You are Sigil's single-file edit proposer.

You may read exactly one source file and edit exactly one proposal file.
Do not edit the source file. Do not edit any other file.
Do not run commands. Do not use shell tools.

The proposal file already contains the current source contents. Modify only the
proposal file so that it becomes the complete reviewed candidate replacement for
the source file. Preserve unrelated content. Keep the edit narrowly scoped to
the user's instruction.
"""


@dataclass(frozen=True)
class EditResult:
    """Outcome of a single-file edit review."""

    path: Path
    proposal_path: Path
    before_sha256: str
    after_sha256: str | None
    applied: bool
    editor_status: int
    proposal_event_id: str
    final_event_id: str | None = None


def edit_file(
    path: Path,
    instruction: str,
    *,
    editor: str | None = None,
    yes: bool = False,
) -> EditResult:
    """Generate, review, and optionally apply a one-file edit proposal."""
    target = validate_target(path)
    original = read_text_file(target, MAX_EDIT_FILE_BYTES)
    before_hash = sha256_text(original)
    proposal_path = make_proposal_path(target)
    proposal_path.write_text(original, encoding="utf-8")

    security = make_security(
        glyph="edit",
        integrity="local_model",
        capability="write_boxed",
        taint=["model"],
        fresh_human=True,
    )
    proposal_event = append_event(
        {
            "type": "file_edit_proposed",
            "path": str(target),
            "proposal_path": str(proposal_path),
            "instruction": instruction,
            "before_sha256": before_hash,
            **security,
        }
    )

    run_pi_edit(target, proposal_path, instruction)
    after_pi = read_text_file(target, MAX_EDIT_FILE_BYTES)
    if sha256_text(after_pi) != before_hash:
        raise RuntimeError("pi modified the source file; refusing to continue")
    reviewed = read_text_file(proposal_path, MAX_PROPOSAL_BYTES)
    if not reviewed:
        raise ValueError("proposal file is empty")

    editor_status = open_diff(target, proposal_path, editor)
    if editor_status != 0:
        final_event = append_event(
            {
                "type": "file_edit_cancelled",
                "path": str(target),
                "proposal_path": str(proposal_path),
                "reason": f"editor exited with status {editor_status}",
                **make_security(
                    glyph="edit",
                    integrity="local_model",
                    capability="write_boxed",
                    taint=["model"],
                    inputs=[proposal_event["id"]],
                    input_records=[proposal_event],
                    fresh_human=True,
                ),
            }
        )
        return EditResult(
            path=target,
            proposal_path=proposal_path,
            before_sha256=before_hash,
            after_sha256=None,
            applied=False,
            editor_status=editor_status,
            proposal_event_id=proposal_event["id"],
            final_event_id=final_event["id"],
        )

    reviewed = read_text_file(proposal_path, MAX_PROPOSAL_BYTES)
    after_hash = sha256_text(reviewed)
    apply = yes or confirm_apply(target)
    if apply:
        after_editor_original = read_text_file(target, MAX_EDIT_FILE_BYTES)
        if sha256_text(after_editor_original) != before_hash:
            raise RuntimeError("source file changed during review; refusing to apply")
        apply_reviewed_file(target, reviewed)

    final_event = append_event(
        {
            "type": "file_edit_applied" if apply else "file_edit_cancelled",
            "path": str(target),
            "proposal_path": str(proposal_path),
            "instruction": instruction,
            "before_sha256": before_hash,
            "after_sha256": after_hash if apply else None,
            "applied": apply,
            **make_security(
                glyph="edit",
                integrity="local_model",
                capability="write_boxed",
                taint=["model"],
                inputs=[proposal_event["id"]],
                input_records=[proposal_event],
                fresh_human=True,
            ),
        }
    )
    return EditResult(
        path=target,
        proposal_path=proposal_path,
        before_sha256=before_hash,
        after_sha256=after_hash if apply else None,
        applied=apply,
        editor_status=editor_status,
        proposal_event_id=proposal_event["id"],
        final_event_id=final_event["id"],
    )


def validate_target(path: Path) -> Path:
    """Return a resolved target path or raise a user-facing error."""
    target = path.expanduser().resolve()
    if not target.exists():
        raise FileNotFoundError(str(path))
    if target.is_symlink():
        raise ValueError("sigil edit does not follow symlinks in v1")
    if not target.is_file():
        raise ValueError("sigil edit requires a regular file")
    size = target.stat().st_size
    if size > MAX_EDIT_FILE_BYTES:
        raise ValueError(
            f"file is too large for sigil edit v1 "
            f"({size} bytes > {MAX_EDIT_FILE_BYTES} bytes)"
        )
    data = target.read_bytes()
    if b"\x00" in data:
        raise ValueError("sigil edit refuses binary files")
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("sigil edit requires UTF-8 text files") from exc
    return target


def read_text_file(path: Path, limit: int) -> str:
    """Read a bounded UTF-8 text file."""
    data = path.read_bytes()
    if len(data) > limit:
        raise ValueError(f"{path} exceeds {limit} bytes")
    if b"\x00" in data:
        raise ValueError(f"{path} is binary")
    return data.decode("utf-8")


def sha256_text(text: str) -> str:
    """Hash text content using its UTF-8 bytes."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def make_proposal_path(target: Path) -> Path:
    """Create a temp proposal path seeded by the original basename."""
    temp_dir = Path(tempfile.mkdtemp(prefix="sigil-edit-"))
    return temp_dir / f"{target.name}.proposed"


def run_pi_edit(target: Path, proposal: Path, instruction: str) -> None:
    """Ask Pi to edit only the proposal file."""
    if not start_qwen_for_pi():
        raise RuntimeError("local model server is not available")
    prompt = "\n\n".join(
        [
            "Prepare a reviewed candidate replacement for one file.",
            f"Source file, read-only: {target}",
            f"Proposal file, edit-only: {proposal}",
            f"Instruction: {instruction}",
            "Use only the read and edit tools. Read the source file if needed. "
            "Edit the proposal file until it contains the complete desired file. "
            "Do not edit the source file.",
        ]
    )
    cmd = [
        "pi",
        "-p",
        "--no-session",
        "--no-context-files",
        "--tools",
        "read,edit",
        "--append-system-prompt",
        EDIT_SYSTEM_PROMPT,
        prompt,
    ]
    print(f"{MUTED}❯ pi edit · single-file proposal{RESET}", file=sys.stderr)
    proc = subprocess.run(
        cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    if proc.returncode != 0:
        if proc.stderr:
            print(proc.stderr, file=sys.stderr, end="")
        raise RuntimeError(f"pi edit failed with status {proc.returncode}")


def editor_command(editor: str | None) -> list[str]:
    """Resolve the diff editor command."""
    value = editor or os.environ.get("SIGIL_EDITOR") or os.environ.get("VISUAL")
    value = value or os.environ.get("EDITOR") or "nvim"
    args = shlex.split(value)
    if not args:
        return ["nvim"]
    return args


def open_diff(original: Path, proposed: Path, editor: str | None = None) -> int:
    """Open the external diff editor for human hunk review."""
    args = editor_command(editor)
    if "-d" not in args and "--diff" not in args:
        args.append("-d")
    args.extend([str(original), str(proposed)])
    try:
        return subprocess.run(args, check=False).returncode
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"editor not found: {args[0]}. {cleanup_editor_hint()}"
        ) from exc


def confirm_apply(path: Path) -> bool:
    """Ask whether to copy the reviewed proposal back over the original."""
    print(f"apply reviewed proposal to {path}? [y/N] ", end="", file=sys.stderr)
    answer = sys.stdin.readline().strip().lower()
    return answer in {"y", "yes"}


def apply_reviewed_file(path: Path, content: str) -> None:
    """Atomically replace the original file with reviewed content."""
    stat = path.stat()
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.chmod(temp_path, stat.st_mode)
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def result_to_json(result: EditResult) -> str:
    """Serialize an edit result for CLI JSON output."""
    return json.dumps(
        {
            "path": str(result.path),
            "proposal_path": str(result.proposal_path),
            "before_sha256": result.before_sha256,
            "after_sha256": result.after_sha256,
            "applied": result.applied,
            "editor_status": result.editor_status,
            "proposal_event_id": result.proposal_event_id,
            "final_event_id": result.final_event_id,
        },
        ensure_ascii=False,
        indent=2,
    )


def cleanup_editor_hint() -> str:
    """Return a concise hint for missing editor errors."""
    if shutil.which("nvim"):
        return "Set SIGIL_EDITOR, VISUAL, or EDITOR if you want a different editor."
    return "Install nvim or set SIGIL_EDITOR, VISUAL, or EDITOR."
