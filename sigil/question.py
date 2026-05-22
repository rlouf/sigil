from __future__ import annotations

import os
import shutil
import subprocess
import sys

from .ansi import MUTED, RESET
from .server import start_qwen_for_pi
from .state import append_event, append_jsonl, read_jsonl, write_jsonl


QUESTION_SYSTEM_PROMPT = (
    "Answer concisely. You are responding to a quick question typed at a shell prompt."
)


def continuation_prompt(question: str) -> str:
    turns = [
        turn
        for turn in read_jsonl("last-question.jsonl")
        if turn.get("role") in {"user", "assistant"} and turn.get("content")
    ]
    if not turns:
        return question
    transcript = "\n\n".join(
        f"{turn['role']}:\n{turn['content']}"
        for turn in turns
    )
    return "\n\n".join(
        [
            "Continue the previous shell discussion.",
            f"Transcript so far:\n{transcript}",
            f"Follow-up question:\n{question}",
        ]
    )


def ask(question: str, stream_filter: str, *, follow_up: bool = False) -> int:
    if not start_qwen_for_pi():
        return 1

    prompt = continuation_prompt(question) if follow_up else question
    question_turn = {
        "role": "user",
        "content": question,
        "prompt": prompt,
        "follow_up": follow_up,
    }
    if follow_up:
        append_jsonl("last-question.jsonl", question_turn)
    else:
        write_jsonl("last-question.jsonl", [question_turn])
    append_event(
        {
            "type": "question",
            "question": question,
            "prompt": prompt,
            "follow_up": follow_up,
        }
    )
    print(f"{MUTED}❯ pi · read + web{RESET}", file=sys.stderr)

    pi_cmd = [
        "pi",
        "-p",
        "--mode",
        "json",
        "--no-session",
        "--tools",
        "read,web_search",
        "--append-system-prompt",
        QUESTION_SYSTEM_PROMPT,
        prompt,
    ]
    filter_cmd = [stream_filter]
    renderer_cmd = ["glow", "-s", "dark", "-"] if shutil.which("glow") else ["cat"]
    filter_env = {**os.environ, "SIGIL_CAPTURE_ANSWER": "1"}

    pi_proc = subprocess.Popen(pi_cmd, stdout=subprocess.PIPE)
    filter_proc = subprocess.Popen(
        filter_cmd,
        stdin=pi_proc.stdout,
        stdout=subprocess.PIPE,
        env=filter_env,
    )
    assert pi_proc.stdout is not None
    pi_proc.stdout.close()
    renderer_proc = subprocess.Popen(renderer_cmd, stdin=filter_proc.stdout)
    assert filter_proc.stdout is not None
    filter_proc.stdout.close()

    renderer_code = renderer_proc.wait()
    filter_code = filter_proc.wait()
    pi_code = pi_proc.wait()
    print()
    if pi_code:
        return pi_code
    if filter_code:
        return filter_code
    return renderer_code
