"""Private response cache (ARCHITECTURE 3.5) and the store protocol used by replay.

The cache is private: it is never exported, never committed and never served as an API. The API implements
`ResponseStore` on Postgres (table `qloo_response`); `MemoryStore` serves tests and the single-process CLI.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Protocol

DAY = 86_400

# TTL by endpoint class (seconds).
TTL_SEARCH = 30 * DAY
TTL_TAGS = 30 * DAY
TTL_INSIGHTS_MEDIA = 14 * DAY
TTL_INSIGHTS_PLACE = 3 * DAY
TTL_ENTITIES = 7 * DAY
TTL_ENTITIES_PLACE_LISTED = DAY
TTL_PROBE = 90 * DAY
TTL_COMPARE = 14 * DAY
TTL_DEMOGRAPHICS = 14 * DAY


@dataclass
class StoredResponse:
    cache_key: str
    host: str
    endpoint: str
    params: list[tuple[str, str]]
    status: int
    body: Any
    headers: dict[str, str] = field(default_factory=dict)
    transport: str = "none"
    fetched_at: float = 0.0
    expires_at: float = 0.0
    guard_version: str = "1"

    def fresh(self, now: float) -> bool:
        return now < self.expires_at

    def stale_usable(self, now: float) -> bool:
        """Stale-while-revalidate window: up to 2x TTL, picker only."""
        ttl = self.expires_at - self.fetched_at
        return now < self.fetched_at + 2 * ttl


class ResponseStore(Protocol):
    async def get(self, cache_key: str) -> StoredResponse | None: ...

    async def put(self, response: StoredResponse) -> None: ...


class MemoryStore:
    def __init__(self) -> None:
        self._items: dict[str, StoredResponse] = {}

    async def get(self, cache_key: str) -> StoredResponse | None:
        return self._items.get(cache_key)

    async def put(self, response: StoredResponse) -> None:
        self._items[response.cache_key] = response

    def __len__(self) -> int:
        return len(self._items)


def ttl_for(
    path: str, params: list[tuple[str, str]], *, probe: bool = False, place_listed: bool = False
) -> int:
    if probe:
        return TTL_PROBE
    if path == "/search":
        return TTL_SEARCH
    if path == "/v2/tags":
        return TTL_TAGS
    if path == "/entities":
        return TTL_ENTITIES_PLACE_LISTED if place_listed else TTL_ENTITIES
    if path == "/v2/analysis/compare":
        return TTL_COMPARE
    if path == "/v2/insights":
        d = dict(params)
        ftype = d.get("filter.type", "")
        if ftype == "urn:demographics":
            return TTL_DEMOGRAPHICS
        return TTL_INSIGHTS_PLACE if ftype == "urn:entity:place" else TTL_INSIGHTS_MEDIA
    return DAY


def now() -> float:
    return time.time()
