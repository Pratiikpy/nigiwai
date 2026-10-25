"""The public-lineup start (M24): a provisional picture of a room from who has played there.

Events and their performers come from MusicBrainz (CC0 data). Each performer is resolved to a Qloo artist, accepted only
on an exact match (the same MusicBrainz id, or the same name after normalisation): proof O found that the top hit for a
name Qloo does not hold is usually a different artist, so a near match is never taken. What cannot be resolved is counted
and reported, never guessed. Everything is labelled as modelled from public lineups, with the number of events used.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
from nigiwai_tribes import Pick, Respondent, Tag, TribesConfig, compute
from qloo_guard import EntityType, QlooGuard, SearchRequest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from ..db import transaction
from .tribes import public_view

log = logging.getLogger("nigiwai.lineup")

PERFORMER_RELATIONS = {
    "main performer",
    "support act",
    "guest performer",
    "performer",
    "headliner",
    "opening act",
}
CACHE_TTL = timedelta(days=7)
MIN_EVENTS = 10  # below this the view says there is not enough public data yet
MIN_RESOLVED_ACTS = 15
GROUPS_FROM_EVENTS = 60  # the same bar as guests: events with two or more resolved acts
MAX_STORED_ACTS = 300  # resolved acts kept with their tags, most-booked first
PAGE = 100
MAX_PAGES = 3
SOURCE_LABEL = "Modelled from public lineups"


def normalise_name(name: str) -> str:
    """Comparison form of an act's name: accents, case, '&', a leading 'the' and punctuation do not matter."""
    s = unicodedata.normalize("NFKC", name).casefold()
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    s = unicodedata.normalize("NFKC", s).replace("&", " and ")
    s = re.sub(r"^the\s+", "", s.strip())
    s = re.sub(r"[^\w]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def exact_match(a: str, b: str) -> bool:
    na, nb = normalise_name(a), normalise_name(b)
    if not na or not nb:  # names made only of symbols: compare the raw casefolded characters
        ra = re.sub(r"\s+", "", unicodedata.normalize("NFKC", a).casefold())
        rb = re.sub(r"\s+", "", unicodedata.normalize("NFKC", b).casefold())
        return bool(ra) and ra == rb
    return na == nb or na.replace(" ", "") == nb.replace(" ", "")


@dataclass(frozen=True)
class PlaceHit:
    mbid: str
    name: str
    area: str | None
    address: str | None
    kind: str | None
    lat: float | None = None
    lon: float | None = None


@dataclass
class Performer:
    mbid: str
    name: str
    events: int = 0


@dataclass
class EventLineup:
    mbid: str
    name: str
    date: str | None
    performers: list[Performer]


def _without_nul(value: Any) -> Any:
    """A NUL character cannot be stored in the cache's JSON column, and a hand-edited public record may hold one."""
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, list):
        return [_without_nul(v) for v in value]
    if isinstance(value, dict):
        return {k: _without_nul(v) for k, v in value.items()}
    return value


def _tidy(value: Any, limit: int) -> str | None:
    """Text from a hand-edited public database, made safe to store and show: printable characters only (a NUL cannot be stored at
    all), whitespace collapsed to single spaces, and no longer than a name or an address ever needs to be."""
    if not isinstance(value, str):
        return None
    cleaned = " ".join("".join(ch for ch in value if ch.isprintable() or ch.isspace()).split())
    return cleaned[:limit] or None


def _place_hit(p: dict[str, Any]) -> PlaceHit | None:
    name = _tidy(p.get("name"), 100)
    if not p.get("id") or not name:
        return None
    area = _tidy((p.get("area") or {}).get("name"), 100)
    coordinates = p.get("coordinates") or {}
    lat: float | None
    lon: float | None
    try:
        lat, lon = float(coordinates["latitude"]), float(coordinates["longitude"])
    except (KeyError, TypeError, ValueError):
        lat = lon = None
    # MusicBrainz is hand-edited: it holds places with a longitude of -457. Out of range is no position at all.
    if lat is not None and lon is not None and not (-90 <= lat <= 90 and -180 <= lon <= 180):
        lat = lon = None
    return PlaceHit(
        p["id"],
        name,
        area,
        _tidy(p.get("address"), 200),
        _tidy(p.get("disambiguation") or p.get("type"), 60),
        lat,
        lon,
    )


class MusicBrainz:
    """The slice of the MusicBrainz web service this needs, polite by construction: one request per 1.1 s across the
    process, an identifying User-Agent (their rule), results cached for a week."""

    _lock = asyncio.Lock()
    _last = 0.0
    INTERVAL = 1.1  # seconds between requests: MusicBrainz asks for one per second at most

    def __init__(
        self,
        engine: AsyncEngine,
        base_url: str,
        contact: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._engine = engine
        self._base = base_url.rstrip("/")
        self._headers = {"User-Agent": f"Nigiwai/0.1 ({contact})", "Accept": "application/json"}
        self._client = client or httpx.AsyncClient(timeout=20.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        key = hashlib.sha256(f"mb|{path}|{sorted(params.items())}".encode()).hexdigest()
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT body, fetched_at FROM external_cache WHERE key = :k AND status = 200"
                    ),
                    {"k": key},
                )
            ).first()
        if row is not None and datetime.now(UTC) - row.fetched_at < CACHE_TTL:
            return dict(row.body)
        last_error: Exception | None = None
        for attempt in range(3):
            async with self._lock:
                wait = self.INTERVAL - (time.monotonic() - MusicBrainz._last)
                if wait > 0:
                    await asyncio.sleep(wait)
                MusicBrainz._last = time.monotonic()
                try:
                    resp = await self._client.get(
                        f"{self._base}{path}",
                        params={**params, "fmt": "json"},
                        headers=self._headers,
                    )
                except httpx.HTTPError as exc:
                    last_error = exc
                    resp = None
            if resp is not None and resp.status_code == 200:
                body = _without_nul(resp.json())
                async with self._engine.begin() as conn:
                    await conn.execute(
                        text(
                            "INSERT INTO external_cache (key, source, status, body) VALUES (:k, 'musicbrainz', 200, CAST(:b AS jsonb))"
                            " ON CONFLICT (key) DO UPDATE SET body = EXCLUDED.body, status = 200, fetched_at = now()"
                        ),
                        {"k": key, "b": json.dumps(body)},
                    )
                return dict(body)
            if resp is not None and resp.status_code not in (429, 503):
                raise LineupError(f"MusicBrainz answered {resp.status_code}")
            await asyncio.sleep(2.0 * (attempt + 1))
        raise LineupError(f"MusicBrainz is not answering right now ({last_error or 'busy'})")

    async def search_places(self, query: str, limit: int = 8) -> list[PlaceHit]:
        quoted = '"' + query.replace('"', " ").strip() + '"'
        body = await self._get("/place", {"query": quoted, "limit": str(limit)})
        return [hit for p in body.get("places", []) if (hit := _place_hit(p)) is not None]

    async def lookup_place(self, mbid: str) -> PlaceHit | None:
        """One place by its MusicBrainz id, or None when MusicBrainz has no such place."""
        try:
            body = await self._get(f"/place/{mbid}", {})
        except LineupError as exc:
            if "answered 404" in str(exc):
                return None
            raise
        return _place_hit(body)

    async def events(self, place_mbid: str) -> list[EventLineup]:
        out: list[EventLineup] = []
        for page in range(MAX_PAGES):
            body = await self._get(
                "/event",
                {
                    "place": place_mbid,
                    "inc": "artist-rels",
                    "limit": str(PAGE),
                    "offset": str(page * PAGE),
                },
            )
            for e in body.get("events", []):
                performers = [
                    Performer(r["artist"]["id"], r["artist"]["name"])
                    for r in e.get("relations", [])
                    if r.get("artist")
                    and r.get("type") in PERFORMER_RELATIONS
                    and r["artist"].get("id")
                ]
                date = (e.get("life-span") or {}).get("begin")
                out.append(EventLineup(e["id"], e.get("name", ""), date, performers))
            if len(body.get("events", [])) < PAGE:
                break
        return out


class LineupError(Exception):
    pass


async def _local_matches(engine: AsyncEngine, mbids: list[str]) -> dict[str, Any]:
    if not mbids:
        return {}
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT entity_id, name_nfc, musicbrainz_id, tags FROM qloo_entity"
                    " WHERE musicbrainz_id = ANY(:m) AND type = 'urn:entity:artist'"
                ),
                {"m": mbids},
            )
        ).all()
    return {r.musicbrainz_id: r for r in rows}


async def resolve_performers(
    engine: AsyncEngine,
    guard: QlooGuard | None,
    tenant_id: UUID,
    performers: list[Performer],
    max_calls: int,
) -> tuple[dict[str, tuple[str, str, tuple[Tag, ...]]], int]:
    """performer mbid -> (qloo entity id, qloo name, tags), for those found by an exact match. Second value: calls made."""
    resolved: dict[str, tuple[str, str, tuple[Tag, ...]]] = {}
    local = await _local_matches(engine, [p.mbid for p in performers])
    for p in performers:
        row = local.get(p.mbid)
        if row is not None and row.tags:
            resolved[p.mbid] = (
                row.entity_id,
                row.name_nfc,
                tuple(Tag(t[0], t[1], t[2]) for t in row.tags),
            )
    calls = 0
    if guard is None:
        return resolved, 0
    ctx = guard.new_context("lineup", tenant_id=tenant_id)
    todo = sorted(
        (p for p in performers if p.mbid not in resolved), key=lambda p: (-p.events, p.name)
    )
    for p in todo:
        if calls >= max_calls:
            break
        try:
            res = await guard.search(
                SearchRequest(query=p.name[:200], types=(EntityType.ARTIST,), take=3), ctx
            )
        except Exception:
            log.warning("lineup search failed for %r", p.name, exc_info=True)
            calls += 1
            continue
        calls += 1
        if not res.ok:
            continue
        for hit in res.items:
            if (hit.musicbrainz_id and hit.musicbrainz_id == p.mbid) or exact_match(
                p.name, hit.name
            ):
                if hit.tags:
                    resolved[p.mbid] = (
                        hit.entity_id,
                        hit.name,
                        tuple(Tag(t.tag_id, t.name, t.type or "") for t in hit.tags),
                    )
                break
    return resolved, calls


def build_profile(
    events: list[EventLineup],
    resolved: dict[str, tuple[str, str, tuple[Tag, ...]]],
    place: PlaceHit,
    cfg: TribesConfig | None = None,
) -> dict[str, Any]:
    """The profile document: counts, top acts and tags (observed from Qloo's tags on resolved acts), and groups only
    when there are enough events to support them."""
    counts: Counter[str] = Counter()
    names: dict[str, str] = {}
    for e in events:
        for p in {x.mbid: x for x in e.performers}.values():
            counts[p.mbid] += 1
            names[p.mbid] = p.name
    dated = sorted(d for d in (e.date for e in events) if d)
    with_lineup = [e for e in events if e.performers]
    unique = len(counts)
    acts_resolved = [m for m in counts if m in resolved]

    tag_acts: Counter[str] = Counter()
    tag_meta: dict[str, tuple[str, str]] = {}
    for m in acts_resolved:
        seen: set[str] = set()
        for t in resolved[m][2]:
            if t.tag_id not in seen:
                seen.add(t.tag_id)
                tag_acts[t.tag_id] += 1
                tag_meta.setdefault(t.tag_id, (t.name, t.type))
    dropped = TribesConfig().dropped_namespaces

    def tag_rows(genre: bool) -> list[dict[str, Any]]:
        """Genre tags say what the room books; the rest (audience, mood and style words) describe its feel."""
        return [
            {
                "tag_id": tid,
                "name": tag_meta[tid][0],
                "acts": n,
                "share": round(n / max(len(acts_resolved), 1), 3),
            }
            for tid, n in tag_acts.most_common()
            if n >= 2
            and ("genre" in tag_meta[tid][1]) == genre
            and not any(ns in tag_meta[tid][1].split(":") + tid.split(":") for ns in dropped)
        ][:10]

    top_tags = tag_rows(True)
    top_feel = tag_rows(False)
    top_acts = [
        {
            "name": resolved[m][1] if m in resolved else names[m],
            "mbid": m,
            "entity_id": resolved[m][0] if m in resolved else None,
            "events": n,
        }
        for m, n in counts.most_common(10)
    ]

    state = "profile"
    reason = ""
    if len(with_lineup) < MIN_EVENTS or len(acts_resolved) < MIN_RESOLVED_ACTS:
        state = "insufficient"
        reason = (
            f"Not enough public data yet: {len(with_lineup)} events with a lineup and {len(acts_resolved)} acts Qloo "
            f"could match exactly. This needs at least {MIN_EVENTS} events and {MIN_RESOLVED_ACTS} acts."
        )

    groups: dict[str, Any] | None = None
    if state == "profile":
        respondents = []
        for e in with_lineup:
            picks = tuple(
                Pick(
                    resolved[p.mbid][0],
                    "urn:entity:artist",
                    resolved[p.mbid][1],
                    resolved[p.mbid][2],
                )
                for p in {x.mbid: x for x in e.performers}.values()
                if p.mbid in resolved
            )
            if len(picks) >= 2:
                respondents.append(Respondent(e.mbid, picks))
        if len(respondents) >= GROUPS_FROM_EVENTS:
            gcfg = cfg or TribesConfig(min_usable_picks=2)
            result = compute(respondents, gcfg)
            groups = public_view(result.to_dict())

    # Every resolved act with its Qloo tags: the Soundcheck groups them into scenes and uses them as references.
    acts = [
        {
            "entity_id": resolved[m][0],
            "name": resolved[m][1],
            "mbid": m,
            "events": n,
            "tags": [[t.tag_id, t.name, t.type] for t in resolved[m][2]],
        }
        for m, n in counts.most_common(MAX_STORED_ACTS)
        if m in resolved
    ]
    weekdays = [0] * 7
    for d in dated:
        if len(d) == 10:  # a full date; partial dates (a year, a month) have no weekday
            try:
                weekdays[date.fromisoformat(d).weekday()] += 1
            except ValueError:
                continue

    return {
        "label": SOURCE_LABEL,
        "state": state,
        "reason": reason,
        "source": {
            "name": "MusicBrainz",
            "licence": "CC0 (public domain)",
            "place_mbid": place.mbid,
        },
        "place": {"name": place.name, "area": place.area, "address": place.address},
        "events": {
            "used": len(events),
            "with_lineup": len(with_lineup),
            "first": dated[0] if dated else None,
            "last": dated[-1] if dated else None,
        },
        "performers": {
            "unique": unique,
            "resolved": len(acts_resolved),
            "rate": round(len(acts_resolved) / unique, 3) if unique else 0.0,
        },
        "top_acts": top_acts,
        "acts": acts,
        "weekdays": weekdays,
        "top_tags": top_tags,
        "top_feel": top_feel,
        "groups": groups,
    }


def owner_view(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    """What an owner's browser receives: the profile without the per-act tag lists, which only the server needs."""
    if doc is None:
        return None
    out = {k: v for k, v in doc.items() if k != "acts"}
    out["acts_stored"] = len(doc.get("acts") or [])
    return out


async def build(
    engine: AsyncEngine,
    guard: QlooGuard | None,
    tenant_id: UUID,
    business_id: UUID,
    mb: MusicBrainz,
    *,
    max_calls: int = 60,
) -> dict[str, Any]:
    async with transaction(engine, tenant_id=tenant_id) as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT place_mbid, place_name, place_area FROM lineup_profile WHERE business_id = :b"
                ),
                {"b": business_id},
            )
        ).first()
        if row is None:
            raise LineupError("no lineup was requested for this business")
        await conn.execute(
            text(
                "UPDATE lineup_profile SET status = 'running', error = NULL WHERE business_id = :b"
            ),
            {"b": business_id},
        )
    place = PlaceHit(row.place_mbid, row.place_name, row.place_area, None, None)
    try:
        events = await mb.events(place.mbid)
        by_performer: dict[str, Performer] = {}
        for e in events:
            for p in e.performers:
                got = by_performer.setdefault(p.mbid, Performer(p.mbid, p.name))
                got.events += 1
        async with transaction(engine, tenant_id=tenant_id) as conn:
            await conn.execute(
                text(
                    "UPDATE lineup_profile SET progress = CAST(:p AS jsonb) WHERE business_id = :b"
                ),
                {
                    "b": business_id,
                    "p": json.dumps(
                        {
                            "events": len(events),
                            "performers": len(by_performer),
                            "stage": "resolving",
                        }
                    ),
                },
            )
        resolved, calls = await resolve_performers(
            engine, guard, tenant_id, list(by_performer.values()), max_calls
        )
        doc = build_profile(events, resolved, place)
        doc["qloo_calls"] = calls
        doc["built_at"] = datetime.now(UTC).isoformat()
        status, error = "ready", None
    except LineupError as exc:
        doc, status, error = {}, "failed", str(exc)
    async with transaction(engine, tenant_id=tenant_id) as conn:
        await conn.execute(
            text(
                "UPDATE lineup_profile SET status = :s, result = CAST(:r AS jsonb), error = :e, finished_at = now()"
                " WHERE business_id = :b"
            ),
            {"s": status, "r": json.dumps(doc) if doc else None, "e": error, "b": business_id},
        )
    if status == "failed":
        raise LineupError(error or "failed")
    return doc
