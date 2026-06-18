"""Substrate refs and ref errors."""

from __future__ import annotations

from dataclasses import dataclass

from .object import ObjectId

RefName = str


@dataclass(frozen=True)
class Ref:
    """Resolved mutable substrate ref."""

    name: RefName
    object_id: ObjectId


@dataclass(frozen=True)
class RefUpdate:
    """Result of moving a mutable ref."""

    name: RefName
    old_object_id: ObjectId | None
    new_object_id: ObjectId
    updated: bool


class UnknownIdError(LookupError):
    """A trace id token matched no ref, object id, or prefix."""

    def __init__(self, token: str) -> None:
        super().__init__(token)
        self.token = token


class AmbiguousIdError(LookupError):
    """A trace id prefix matched more than one object."""

    def __init__(self, token: str, candidates: list[ObjectId]) -> None:
        super().__init__(token)
        self.token = token
        self.candidates = candidates


class UnknownSessionError(LookupError):
    """A session id named no recorded trace store."""

    def __init__(self, session_id: str, available: list[str]) -> None:
        super().__init__(session_id)
        self.session_id = session_id
        self.available = available
