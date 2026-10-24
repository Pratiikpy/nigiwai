"""A scripted stand-in for Qloo's HTTP API, for tests of the API layer. Every name and id is invented."""

from __future__ import annotations

import itertools
from typing import Any

from qloo_guard.requests import Params
from qloo_guard.transports.base import RawResponse

_ids = itertools.count(1)


def new_id() -> str:
    return f"00000000-0000-4000-8000-{next(_ids):012d}"


def artist(
    name: str,
    entity_id: str | None = None,
    year: int | None = None,
    tags: list[tuple[str, str]] | None = None,
    mbid: str | None = None,
) -> dict[str, Any]:
    props: dict[str, Any] = {"short_description": f"{name}, an invented act."}
    if year:
        props["release_year"] = year
    if mbid:
        props["external"] = {"musicbrainz": {"id": mbid}}
    return {
        "name": name,
        "entity_id": entity_id or new_id(),
        "types": ["urn:entity:artist"],
        "popularity": 0.2,
        "tags": [{"tag_id": t[0], "name": t[1], "type": "urn:tag:genre:qloo"} for t in tags or []],
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
        self.drop_seeds: set[str] = (
            set()
        )  # entity ids Qloo "does not know": dropped with a not_found warning
        self.delay = 0.0  # seconds every call takes, to exercise slow answers
        # entity id -> (female index, older-minus-younger age contrast), for the demographics answers
        self.demographics: dict[str, tuple[float, float]] = {}

    def supports(self, path: str, params: Params) -> bool:
        return True

    async def get(self, path: str, params: Params) -> RawResponse:
        self.calls.append((path, list(params)))
        if self.delay:
            import asyncio

            await asyncio.sleep(self.delay)
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
            kind = p.get("filter.type", "urn:entity:artist")
            if kind == "urn:demographics":
                return RawResponse(
                    status=200,
                    body={
                        "success": True,
                        "results": {
                            "demographics": [
                                self._demographic(e)
                                for e in seed.split(",")
                                if e in self.demographics
                            ]
                        },
                    },
                    transport="rest",
                )
            if kind == "urn:entity:place":
                places = [
                    {
                        "name": f"Invented Bar {i}",
                        "entity_id": new_id(),
                        "type": "urn:entity",
                        "subtype": "urn:entity:place",
                        "popularity": 0.3,
                        "location": {"lat": 51.5 + i * 0.001, "lon": -0.12},
                        "tags": [
                            {
                                "id": "urn:tag:category:place:bar",
                                "name": "bar",
                                "type": "urn:tag:category:place",
                            }
                        ],
                        "query": {"distance": 150.0 * (i + 1), "affinity": 0.8},
                        "properties": {"address": f"{i + 1} Invented Street", "is_closed": False},
                    }
                    for i in range(3)
                ]
                return RawResponse(
                    status=200,
                    body=self._with_warnings(
                        {"success": True, "results": {"entities": places}}, seed
                    ),
                    transport="rest",
                )
            rows = [
                {
                    "name": f"Neighbour {i}",
                    "entity_id": new_id(),
                    "type": "urn:entity",
                    "subtype": kind,
                    "popularity": 0.1,
                    "tags": [],
                    "query": {"affinity": 0.7},
                    "properties": {},
                }
                for i in range(4)
            ]
            return RawResponse(
                status=200,
                body=self._with_warnings({"success": True, "results": {"entities": rows}}, seed),
                transport="rest",
            )
        if path == "/entities":
            wanted = set(p.get("entity_ids", "").split(","))
            hits = [e for e in self.catalogue if e["entity_id"] in wanted]
            return RawResponse(status=200, body={"results": hits}, transport="rest")
        return RawResponse(status=404, body=None, transport="rest")

    def _demographic(self, entity_id: str) -> dict[str, Any]:
        female, contrast = self.demographics[entity_id]
        q = contrast / 4  # spread so that (45+ bands) - (under 30 bands) equals the contrast
        return {
            "entity_id": entity_id,
            "query": {
                "age": {
                    "24_and_younger": -q,
                    "25_to_29": -q,
                    "30_to_34": 0.0,
                    "35_to_44": 0.0,
                    "45_to_54": q,
                    "55_and_older": q,
                },
                "gender": {"female": female, "male": -female},
            },
        }

    def _with_warnings(self, body: dict[str, Any], seed: str) -> dict[str, Any]:
        if seed in self.drop_seeds:
            body["warnings"] = [{"type": "not_found", "signal.interests.entities": [seed]}]
        return body

    async def aclose(self) -> None:
        return None
