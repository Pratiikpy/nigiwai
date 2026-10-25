"""A scripted stand-in for Qloo's HTTP API, for tests of the API layer. Every name and id is invented."""

from __future__ import annotations

import itertools
from collections.abc import Callable
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


def place(
    name: str,
    entity_id: str | None = None,
    *,
    distance: float,
    affinity: float | None = None,
    closed: bool | None = False,
    lat: float = 51.5,
    lon: float = -0.12,
) -> dict[str, Any]:
    """A bar as Qloo describes one: located, with its distance from the asked-about point and, when the question had a taste
    signal, an affinity."""
    query: dict[str, Any] = {"distance": distance}
    if affinity is not None:
        query["affinity"] = affinity
    properties: dict[str, Any] = {"address": f"{name}, Invented Street"}
    if closed is not None:
        properties["is_closed"] = closed
    return {
        "name": name,
        "entity_id": entity_id or new_id(),
        "type": "urn:entity",
        "subtype": "urn:entity:place",
        "popularity": 0.3,
        "location": {"lat": lat, "lon": lon},
        "tags": [
            {"id": "urn:tag:category:place:bar", "name": "bar", "type": "urn:tag:category:place"}
        ],
        "query": query,
        "properties": properties,
    }


def search_place(
    name: str,
    entity_id: str | None = None,
    *,
    address: str | None = None,
    lat: float = 51.5,
    lon: float = -0.12,
    kind: str = "Bar",
    extra: list[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """A place as Qloo's /search returns one: located, with an address and a long list of tags, only some of which are taste.
    `extra` adds (tag id, name) pairs, so a test can give a place a protected kind or a protected word."""
    slug = kind.lower().replace(" ", "_")
    tags = [
        (f"urn:tag:category:place:{slug}", kind, "urn:tag:category:place"),
        (f"urn:tag:genre:place:{slug}", kind, "urn:tag:genre:place"),
        ("urn:tag:ambience:qloo:lively", "Lively", "urn:tag:ambience:qloo"),
        ("urn:tag:decor:qloo:industrial", "Industrial", "urn:tag:decor:qloo"),
        ("urn:tag:payments:place:visa", "Visa", "urn:tag:payments:place"),
        (
            "urn:tag:accessibility:place:ramp",
            "Wheelchair accessible entrance",
            "urn:tag:accessibility:place",
        ),
        ("urn:tag:customer_identity:qloo:students", "Students", "urn:tag:customer_identity:qloo"),
    ] + [(tid, nm, ":".join(tid.split(":")[:4])) for tid, nm in extra or []]
    return {
        "name": name,
        "entity_id": entity_id or new_id(),
        "types": ["urn:entity:place"],
        "popularity": 0.3,
        "location": {"lat": lat, "lon": lon},
        "tags": [{"tag_id": a, "name": b, "type": c} for a, b, c in tags],
        "properties": {"address": address or f"{name}, Invented Street"},
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
        # entity id -> planted group, for artist insights: an entity in the same group as the signal's majority scores
        # high, anything else low, with a small stable jitter so no two scores tie
        self.group_of: dict[str, int] = {}
        self.names: dict[
            str, str
        ] = {}  # entity id -> name, for entities scored but absent from the catalogue
        # artists offered as neighbours when insights is asked with no results filter, best matches first by group
        self.neighbour_pool: list[dict[str, Any]] = []
        # when set, place insights is answered by this: (seed ids, radius in metres, take) -> places, best first. Every place it
        # returns is also known to /entities, so the closure check can read its `is_closed`.
        self.place_answer: Callable[[list[str], int, int], list[dict[str, Any]]] | None = None
        self.known_places: dict[str, dict[str, Any]] = {}

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
            ]
            if "filter.location" in p:
                # a point biases the search: the nearest first (and, as in Qloo, nothing but places comes back)
                lat0, lon0 = (float(x) for x in p["filter.location"].split(","))
                hits = [e for e in hits if "urn:entity:place" in e["types"]]
                hits.sort(
                    key=lambda e: (
                        (e["location"]["lat"] - lat0) ** 2 + (e["location"]["lon"] - lon0) ** 2
                    )
                )
            hits = hits[: int(p.get("take", "5"))]
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
            if kind == "urn:entity:artist" and self.group_of:
                return self._artist_insights(p, seed)
            if kind == "urn:entity:place" and self.place_answer is not None:
                rows = self.place_answer(
                    [s for s in seed.split(",") if s],
                    int(p.get("filter.location.radius", "0") or 0),
                    int(p.get("take", "20")),
                )
                self.known_places.update({r["entity_id"]: r for r in rows})
                return RawResponse(
                    status=200,
                    body=self._with_warnings(
                        {"success": True, "results": {"entities": rows}}, seed
                    ),
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
            hits = [
                e
                for e in [*self.catalogue, *self.known_places.values()]
                if e["entity_id"] in wanted
            ]
            return RawResponse(status=200, body={"results": hits}, transport="rest")
        return RawResponse(status=404, body=None, transport="rest")

    def _affinity(self, seeds: list[str], entity_id: str) -> float:
        votes: dict[int, int] = {}
        for sd in seeds:
            g = self.group_of.get(sd)
            if g is not None:
                votes[g] = votes.get(g, 0) + 1
        home = max(votes, key=lambda g: (votes[g], -g)) if votes else None
        jitter = (int(entity_id.replace("-", "")[-6:], 16) % 997) / 997 * 0.02
        return (0.93 if self.group_of.get(entity_id) == home else 0.72) + jitter

    def _artist_insights(self, p: dict[str, str], seed: str) -> RawResponse:
        seeds = seed.split(",") if seed else []
        wanted = [e for e in p.get("filter.results.entities", "").split(",") if e]
        by_id = {e["entity_id"]: e for e in [*self.catalogue, *self.neighbour_pool]}
        if wanted:
            pool = [
                by_id.get(e) or {"name": self.names.get(e, f"Planted {e[-6:]}"), "entity_id": e}
                for e in wanted
                if e not in seeds
            ]
        else:
            pool = sorted(
                (e for e in self.neighbour_pool if e["entity_id"] not in seeds),
                key=lambda e: -self._affinity(seeds, e["entity_id"]),
            )[: int(p.get("take", "20"))]
        rows = [
            {
                "name": e["name"],
                "entity_id": e["entity_id"],
                "type": "urn:entity",
                "subtype": "urn:entity:artist",
                "popularity": e.get("popularity", 0.2),
                "tags": e.get("tags", []),
                "query": {"affinity": self._affinity(seeds, e["entity_id"])},
                "properties": e.get("properties", {}),
            }
            for e in pool
        ]
        return RawResponse(
            status=200,
            body=self._with_warnings({"success": True, "results": {"entities": rows}}, seed),
            transport="rest",
        )

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
