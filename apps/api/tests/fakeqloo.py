"""A scripted stand-in for Qloo's HTTP API, for tests of the API layer. Every name and id is invented."""

from __future__ import annotations

import itertools
from typing import Any

from qloo_guard.requests import Params
from qloo_guard.transports.base import RawResponse

_ids = itertools.count(1)


def new_id() -> str:
    return f"00000000-0000-4000-8000-{next(_ids):012d}"


def artist(name: str, entity_id: str | None = None, year: int | None = None) -> dict[str, Any]:
    props: dict[str, Any] = {"short_description": f"{name}, an invented act."}
    if year:
        props["release_year"] = year
    return {
        "name": name,
        "entity_id": entity_id or new_id(),
        "types": ["urn:entity:artist"],
        "popularity": 0.2,
        "tags": [],
        "properties": props,
    }


def movie(name: str, entity_id: str | None = None, year: int = 2001) -> dict[str, Any]:
    return {
        "name": name,
        "entity_id": entity_id or new_id(),
        "types": ["urn:entity:movie"],
        "popularity": 0.2,
        "tags": [],
        "properties": {"release_year": year, "short_description": f"{name}, an invented film."},
    }


class FakeQloo:
    """Search matches by substring over a catalogue; insights (the eligibility probe) answers 200 or 400."""

    name = "rest"

    def __init__(self, catalogue: list[dict[str, Any]] | None = None) -> None:
        self.catalogue = catalogue or []
        self.ineligible: set[str] = set()
        self.calls: list[tuple[str, Params]] = []
        self.down = False

    def supports(self, path: str, params: Params) -> bool:
        return True

    async def get(self, path: str, params: Params) -> RawResponse:
        self.calls.append((path, list(params)))
        if self.down:
            return RawResponse(status=503, body=None, transport="rest")
        p = dict(params)
        if path == "/search":
            q = p.get("query", "").lower()
            wanted = set(p.get("types", "").split(","))
            hits = [
                e for e in self.catalogue if q in e["name"].lower() and wanted & set(e["types"])
            ][: int(p.get("take", "5"))]
            return RawResponse(status=200, body={"results": hits}, transport="rest")
        if path == "/v2/insights":
            seed = p.get("signal.interests.entities", "")
            if seed in self.ineligible:
                return RawResponse(status=400, body={"error": "bad seed"}, transport="rest")
            row = {
                "name": "Neighbour",
                "entity_id": new_id(),
                "type": "urn:entity",
                "subtype": p.get("filter.type", "urn:entity:artist"),
                "popularity": 0.1,
                "tags": [],
                "query": {"affinity": 0.7},
                "properties": {},
            }
            return RawResponse(
                status=200, body={"success": True, "results": {"entities": [row]}}, transport="rest"
            )
        return RawResponse(status=404, body=None, transport="rest")

    async def aclose(self) -> None:
        return None
