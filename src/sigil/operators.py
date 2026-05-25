"""Semantic operator parsing for future stream-oriented glyph routes."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal, cast

OperatorBase = Literal["?", ",", "^"]

OPERATOR_NAMES: dict[OperatorBase, str] = {
    "?": "inspect",
    ",": "propose",
    "^": "repair",
}

SUPPORTED_OPERATORS = frozenset(OPERATOR_NAMES)


@dataclass(frozen=True)
class OperatorInvocation:
    """Parsed semantic operator invocation metadata."""

    glyph: str
    base: OperatorBase
    depth: int
    name: str
    prompt: str
    stdin: str
    mode: str

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""
        return asdict(self)


def parse_operator_token(token: str) -> tuple[OperatorBase, int]:
    """Parse a repeated semantic operator token.

    Examples:

    ```text
    ?   -> ("?", 1)
    ??  -> ("?", 2)
    ^^^ -> ("^", 3)
    ```
    """
    if not token:
        raise ValueError("operator token is required")
    base = token[0]
    if base not in SUPPORTED_OPERATORS:
        raise ValueError(f"unsupported operator: {base}")
    operator = cast(OperatorBase, base)
    if any(char != base for char in token):
        raise ValueError(f"operator token must repeat one glyph: {token}")
    return operator, len(token)


def create_invocation(
    token: str,
    *,
    prompt: str = "",
    stdin: str = "",
    mode: str = "interactive",
) -> OperatorInvocation:
    """Create parsed invocation metadata for the semantic operator runtime."""
    base, depth = parse_operator_token(token)
    return OperatorInvocation(
        glyph=token,
        base=base,
        depth=depth,
        name=OPERATOR_NAMES[base],
        prompt=prompt,
        stdin=stdin,
        mode=mode,
    )
