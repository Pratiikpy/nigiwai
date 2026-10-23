"""Shared fixtures. Every name, id and number here is invented: no Qloo response data is committed."""

from __future__ import annotations

import itertools
from collections.abc import Callable
from typing import Any, cast

import pytest
from qloo_guard import (
    MemoryQuotaLedger,
    MemoryRecorder,
    MemoryRegistry,
    MemoryStore,
    QlooConfig,
    QlooGuard,
    QuotaManager,
    RegistryEntry,
)
from qloo_guard.ratelimit import CircuitBreaker, TokenBucket
from qloo_guard.requests import Params
from qloo_guard.transports.base import RawResponse

_counter = itertools.count(1)


def make_id() -> str:
    n = next(_counter)
    return f"00000000-0000-4000-8000-{n:012d}"


def artist_raw(
    name: str = "Lantern Hollow", entity_id: str | None = None, **over: Any
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "name": name,
        "entity_id": entity_id or make_id(),
        "types": ["urn:entity:artist"],
        "popularity": 0.2,
        "tags": [
            {
                "name": "Dream Pop",
                "tag_id": "urn:tag:genre:qloo:dream_pop",
                "type": "urn:tag:genre:qloo",
            }
        ],
        "properties": {
            "short_description": "An invented band.",
            "external": {"musicbrainz": {"id": "mb-1"}},
        },
    }
    base.update(over)
    return base


def insights_artist_raw(name: str, affinity: float, entity_id: str | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "entity_id": entity_id or make_id(),
        "type": "urn:entity",  # live insights entities carry the real type in `subtype`
        "subtype": "urn:entity:artist",
        "popularity": 0.1,
        "tags": [{"id": "urn:tag:genre:qloo:folk", "name": "Folk", "type": "urn:tag:genre:qloo"}],
        "query": {"affinity": affinity},
        "properties": {},
    }


def place_raw(
    name: str, distance: float, entity_id: str | None = None, tags: list[str] | None = None
) -> dict[str, Any]:
    return {
        "name": name,
        "entity_id": entity_id or make_id(),
        "type": "urn:entity",
        "subtype": "urn:entity:place",
        "popularity": 0.3,
        "location": {"lat": 40.7201, "lon": -73.9901},
        "tags": [
            {"id": t, "name": t.split(":")[-1], "type": "urn:tag:category:place"}
            for t in (tags or ["urn:tag:category:place:bar"])
        ],
        "query": {"distance": distance},
        "properties": {"address": "1 Invented Street", "is_closed": False},
    }


def search_body(*entities: dict[str, Any]) -> dict[str, Any]:
    return {"results": list(entities)}


def insights_body(
    *entities: dict[str, Any], warnings: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    body: dict[str, Any] = {"success": True, "results": {"entities": list(entities)}}
    if warnings is not None:
        body["warnings"] = warnings
    return body


class FakeTransport:
    """Scripted transport. `respond` receives (path, params) and returns a RawResponse or raises."""

    def __init__(
        self,
        name: str = "rest",
        respond: Callable[[str, Params], RawResponse] | None = None,
        supports: Callable[[str, Params], bool] | None = None,
    ) -> None:
        self.name = name
        self.calls: list[tuple[str, Params]] = []
        self._respond = respond
        self._supports = supports or (lambda path, params: True)
        self.queue: list[Any] = []

    def supports(self, path: str, params: Params) -> bool:
        return self._supports(path, params)

    async def get(self, path: str, params: Params) -> RawResponse:
        self.calls.append((path, list(params)))
        if self.queue:
            item = self.queue.pop(0)
            if isinstance(item, Exception):
                raise item
            return cast(RawResponse, item)
        if self._respond is None:
            raise AssertionError("FakeTransport has no response scripted")
        return self._respond(path, params)

    async def aclose(self) -> None:
        return None


def ok(body: Any, headers: dict[str, str] | None = None, transport: str = "rest") -> RawResponse:
    return RawResponse(
        status=200, body=body, headers=headers or {}, elapsed_ms=5, transport=transport
    )


async def _no_sleep(_s: float) -> None:
    return None


@pytest.fixture
def config() -> QlooConfig:
    return QlooConfig(rate_per_second=1000.0, burst=1000)


class Rig:
    def __init__(
        self,
        guard: QlooGuard,
        transport: FakeTransport,
        recorder: MemoryRecorder,
        registry: MemoryRegistry,
        store: MemoryStore,
        ledger: MemoryQuotaLedger,
    ) -> None:
        self.guard = guard
        self.transport = transport
        self.recorder = recorder
        self.registry = registry
        self.store = store
        self.ledger = ledger

    async def known(
        self,
        entity_id: str,
        types: tuple[str, ...] = ("urn:entity:artist",),
        name: str = "Known",
        eligible: bool | None = True,
    ) -> str:
        await self.registry.put(RegistryEntry(entity_id, types, name, eligible=eligible))
        return entity_id


@pytest.fixture
def make_rig(config: QlooConfig) -> Callable[..., Rig]:
    def build(
        transport: FakeTransport | None = None,
        transports: list[FakeTransport] | None = None,
        cfg: QlooConfig | None = None,
    ) -> Rig:
        cfg = cfg or config
        ts = transports or [transport or FakeTransport(respond=lambda p, q: ok(search_body()))]
        ledger = MemoryQuotaLedger()
        recorder = MemoryRecorder()
        registry = MemoryRegistry()
        store = MemoryStore()
        guard = QlooGuard(
            config=cfg,
            transports=ts,  # type: ignore[arg-type]
            store=store,
            registry=registry,
            quota=QuotaManager(cfg, ledger),
            limiter=TokenBucket(cfg.rate_per_second, cfg.burst),
            recorder=recorder,
            ledger=ledger,
            key_fingerprint="abcd1234",
            breaker=CircuitBreaker(),
            sleep=_no_sleep,
        )
        return Rig(guard, ts[0], recorder, registry, store, ledger)

    return build
