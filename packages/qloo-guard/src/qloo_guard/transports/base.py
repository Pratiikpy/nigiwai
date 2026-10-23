"""Transport protocol and the raw response record."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from ..requests import Params


@dataclass
class RawResponse:
    status: int
    body: Any  # parsed JSON (dict or list), or None when the body was not JSON
    headers: dict[str, str] = field(default_factory=dict)  # lower-cased names
    elapsed_ms: int = 0
    transport: str = "none"
    text: str = ""  # first characters of a non-JSON body, for diagnostics only


class Transport(Protocol):
    name: str

    def supports(self, path: str, params: Params) -> bool:
        """Whether this transport can carry the request without losing information the Guard needs."""
        ...

    async def get(self, path: str, params: Params) -> RawResponse: ...

    async def aclose(self) -> None: ...
