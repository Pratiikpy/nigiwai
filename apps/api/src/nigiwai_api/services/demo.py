"""Judge mode (PRD M25): a few real venues that anyone can open without an account.

Each demo venue is an ordinary business under one fixed system tenant that has no users, so nobody can sign in to it. Its
crowd is the public event lineups of the room (MusicBrainz, public domain) resolved to Qloo; its Soundchecks, suggested acts,
Booking Brief and map are built by the same code an owner's venue uses, ahead of time, so the first view never waits on a
slow Qloo call. A weekly job rebuilds them. Opening a demo venue reads stored results and costs no Qloo call.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from qloo_guard import QlooGuard
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from ..db import transaction
from . import compare as compare_service
from . import lineup, mapdata, soundcheck
from .llm import LlmClient

log = logging.getLogger("nigiwai.demo")

# The tenant that owns every demo venue. Migration 0009 creates it and the demo_venue table refuses any other tenant, so a
# demo row can never expose a real customer's venue.
DEMO_TENANT_ID = UUID("6e1c0de0-0000-4000-8000-00000000d3a0")
REBUILD_AFTER_HOURS = 24 * 7
KEEP_CHECKS_DAYS = 7  # visitors' own checks and superseded builds are dropped after this
MAX_LINEUP_PASSES = 6  # a pass resolves at most 60 acts; stop earlier when a pass finds nothing new


@dataclass(frozen=True)
class Spec:
    slug: str
    query: str  # what to search MusicBrainz for
    area_hint: str  # the place's area must contain this
    city: str
    timezone: str
    blurb: str


SPECS = (
    Spec(
        "mercury-lounge",
        "Mercury Lounge",
        "New York",
        "New York",
        "America/New_York",
        "A small Lower East Side room that books rising indie and rock acts most nights.",
    ),
    Spec(
        "the-hideout",
        "The Hideout",
        "Chicago",
        "Chicago",
        "America/Chicago",
        "A Chicago bar and music room known for local bands, roots acts and left-field bookings.",
    ),
    Spec(
        "empty-bottle",
        "Empty Bottle",
        "Chicago",
        "Chicago",
        "America/Chicago",
        "A West Town Chicago club with a long run of indie, experimental and punk shows.",
    ),
)


class DemoError(Exception):
    pass


async def find_place(mb: lineup.MusicBrainz, spec: Spec) -> lineup.PlaceHit:
    """The MusicBrainz place for a spec: the exact name, in the right area, with coordinates."""
    hits = await mb.search_places(spec.query, limit=10)
    for h in hits:
        if h.name.casefold() != spec.query.casefold():
            continue
        # MusicBrainz names a place's area at neighbourhood level ("Lower East Side"), so the city may be only in the address.
        where = f"{h.area or ''} {h.address or ''}".casefold()
        if spec.area_hint.casefold() not in where:
            continue
        if h.lat is None or h.lon is None:
            continue
        return h
    raise DemoError(
        f"MusicBrainz has no place called {spec.query} in {spec.area_hint} with coordinates"
    )


async def _create(engine: AsyncEngine, spec: Spec, place: lineup.PlaceHit) -> UUID:
    """A new demo venue: its business, its location from the place's coordinates, and its row in the demo list."""
    async with transaction(engine, tenant_id=DEMO_TENANT_ID) as conn:
        business_id = uuid4()
        await conn.execute(
            text(
                "INSERT INTO business (id, tenant_id, name, type, language, currency)"
                " VALUES (:i, :t, :n, 'live_music_venue', 'en', 'USD')"
            ),
            {"i": business_id, "t": DEMO_TENANT_ID, "n": spec.query},
        )
        await conn.execute(
            text(
                "INSERT INTO location (tenant_id, business_id, name, address, geom, radius_m, timezone)"
                " VALUES (:t, :b, :n, :a, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, 800, :tz)"
            ),
            {
                "t": DEMO_TENANT_ID,
                "b": business_id,
                "n": spec.query,
                "a": place.address,
                "lon": place.lon,
                "lat": place.lat,
                "tz": spec.timezone,
            },
        )
        await conn.execute(
            text(
                "INSERT INTO demo_venue (slug, name, city, blurb, tenant_id, business_id, status)"
                " VALUES (:s, :n, :c, :bl, :t, :b, 'building')"
            ),
            {
                "s": spec.slug,
                "n": spec.query,
                "c": spec.city,
                "bl": spec.blurb,
                "t": DEMO_TENANT_ID,
                "b": business_id,
            },
        )
    return business_id


async def _stored_place(engine: AsyncEngine, business_id: UUID) -> lineup.PlaceHit | None:
    """The MusicBrainz place a venue was built from, so a rebuild does not have to find it again."""
    async with transaction(engine, tenant_id=DEMO_TENANT_ID) as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT place_mbid, place_name, place_area FROM lineup_profile WHERE business_id = :b"
                ),
                {"b": business_id},
            )
        ).first()
    if row is None:
        return None
    return lineup.PlaceHit(row.place_mbid, row.place_name, row.place_area, None, None)


async def _snapshot(engine: AsyncEngine, business_id: UUID) -> dict[str, Any]:
    """What a rebuild is about to overwrite. Both jobs clear their stored result when they fail, so a failed rebuild puts
    this back and the venue keeps showing what it showed."""
    async with transaction(engine, tenant_id=DEMO_TENANT_ID) as conn:
        profile = (
            await conn.execute(
                text(
                    "SELECT status, progress, result, error, finished_at FROM lineup_profile WHERE business_id = :b"
                ),
                {"b": business_id},
            )
        ).first()
        suggestion = (
            await conn.execute(
                text(
                    "SELECT status, basis_kind, basis_ref, result, error, updated_at FROM act_suggestion"
                    " WHERE business_id = :b"
                ),
                {"b": business_id},
            )
        ).first()
    return {"profile": profile, "suggestion": suggestion}


async def _restore(engine: AsyncEngine, business_id: UUID, saved: dict[str, Any]) -> None:
    async with transaction(engine, tenant_id=DEMO_TENANT_ID) as conn:
        p = saved["profile"]
        if p is not None:
            await conn.execute(
                text(
                    "UPDATE lineup_profile SET status = :s, progress = CAST(:pr AS jsonb),"
                    " result = CAST(:r AS jsonb), error = :e, finished_at = :f WHERE business_id = :b"
                ),
                {
                    "b": business_id,
                    "s": p.status,
                    "pr": json.dumps(p.progress),
                    "r": json.dumps(p.result) if p.result is not None else None,
                    "e": p.error,
                    "f": p.finished_at,
                },
            )
        g = saved["suggestion"]
        if g is not None:
            await conn.execute(
                text(
                    "UPDATE act_suggestion SET status = :s, basis_kind = :k, basis_ref = :r,"
                    " result = CAST(:d AS jsonb), error = :e, updated_at = :u WHERE business_id = :b"
                ),
                {
                    "b": business_id,
                    "s": g.status,
                    "k": g.basis_kind,
                    "r": g.basis_ref,
                    "d": json.dumps(g.result) if g.result is not None else None,
                    "e": g.error,
                    "u": g.updated_at,
                },
            )


async def _mark(engine: AsyncEngine, slug: str, status: str | None, error: str | None) -> None:
    """Record the outcome of a build. A venue that was ready stays ready when a rebuild fails: the stored results are
    still true, only older, and the error is kept for the operator."""
    async with engine.begin() as conn:
        if status is None:
            await conn.execute(
                text("UPDATE demo_venue SET error = :e WHERE slug = :s"), {"s": slug, "e": error}
            )
        else:
            await conn.execute(
                text("UPDATE demo_venue SET status = :st, error = :e WHERE slug = :s"),
                {"s": slug, "st": status, "e": error},
            )


async def build_venue(
    engine: AsyncEngine,
    guard: QlooGuard | None,
    mb: lineup.MusicBrainz,
    llm: LlmClient | None,
    limiter: Any,
    daily_limit: int,
    spec: Spec,
    place: lineup.PlaceHit | None = None,
) -> dict[str, Any]:
    """Build (or rebuild) one demo venue end to end with real data. Returns its summary."""
    if guard is None:
        raise DemoError("Qloo is not configured, so a demo venue cannot be built")
    existing = await venue(engine, spec.slug)
    if existing is None:
        place = place or await find_place(mb, spec)
        business_id = await _create(engine, spec, place)
        was_ready = False
    else:
        business_id = existing["business_id"]
        was_ready = existing["status"] == "ready"
    if not was_ready:
        await _mark(engine, spec.slug, "building", None)
    saved = await _snapshot(engine, business_id) if was_ready else None
    try:
        place = place or await _stored_place(engine, business_id) or await find_place(mb, spec)
        async with transaction(engine, tenant_id=DEMO_TENANT_ID) as conn:
            await conn.execute(
                text(
                    "INSERT INTO lineup_profile (tenant_id, business_id, place_mbid, place_name, place_area, status)"
                    " VALUES (:t, :b, :m, :n, :a, 'queued')"
                    " ON CONFLICT (business_id) DO UPDATE SET place_mbid = EXCLUDED.place_mbid,"
                    " place_name = EXCLUDED.place_name, place_area = EXCLUDED.place_area,"
                    " status = 'queued', error = NULL"
                ),
                {
                    "t": DEMO_TENANT_ID,
                    "b": business_id,
                    "m": place.mbid,
                    "n": place.name,
                    "a": place.area,
                },
            )
        doc: dict[str, Any] = {}
        resolved = -1
        for _ in range(MAX_LINEUP_PASSES):
            doc = await lineup.build(engine, guard, DEMO_TENANT_ID, business_id, mb)
            now_resolved = int((doc.get("performers") or {}).get("resolved") or 0)
            if now_resolved <= resolved:
                break
            resolved = now_resolved
        if doc.get("state") != "profile":
            raise DemoError(
                doc.get("reason") or "the public lineup is too thin to build a demo from"
            )
        await soundcheck.run_suggest_job(engine, guard, DEMO_TENANT_ID, business_id)
        sug = await soundcheck.suggestions(engine, DEMO_TENANT_ID, business_id)
        if not sug or sug["status"] != "ready" or not sug["result"]:
            raise DemoError((sug or {}).get("error") or "no acts could be suggested for this room")
        result = sug["result"]
        # Warm what a first view needs, so it is served from storage.
        suggested = [*result["top"], *([result["wildcard"]] if result["wildcard"] else [])]
        for s in suggested:
            await compare_service.build(
                engine,
                guard,
                llm,
                limiter,
                daily_limit,
                DEMO_TENANT_ID,
                business_id,
                UUID(s["soundcheck_id"]),
            )
        await mapdata.around_for(engine, guard, DEMO_TENANT_ID, business_id)
        # Old checks go (visitors' own, and earlier builds'), but never one the current suggestions point at: a stored
        # check is reused when its inputs are unchanged, so a suggested act's check can be older than the window.
        keep = [UUID(s["soundcheck_id"]) for s in suggested]
        async with transaction(engine, tenant_id=DEMO_TENANT_ID) as conn:
            await conn.execute(
                text(
                    "DELETE FROM soundcheck WHERE business_id = :b"
                    " AND created_at < now() - make_interval(days => :d) AND NOT (id = ANY(:keep))"
                ),
                {"b": business_id, "d": KEEP_CHECKS_DAYS, "keep": keep},
            )
        summary: dict[str, Any] = {
            "place": place.name,
            "area": place.area,
            "events": (doc.get("events") or {}).get("with_lineup"),
            "first": (doc.get("events") or {}).get("first"),
            "last": (doc.get("events") or {}).get("last"),
            "acts_matched": (doc.get("performers") or {}).get("resolved"),
            "performers": (doc.get("performers") or {}).get("unique"),
            "top": [t["name"] for t in result["top"]],
            "wildcard": result["wildcard"]["name"] if result["wildcard"] else None,
        }
    except Exception as exc:
        if saved is not None:
            await _restore(engine, business_id, saved)
        await _mark(
            engine,
            spec.slug,
            None if was_ready else "failed",
            f"{type(exc).__name__}: {exc}"[:400],
        )
        raise
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE demo_venue SET status = 'ready', error = NULL, summary = CAST(:m AS jsonb),"
                " refreshed_at = now() WHERE slug = :s"
            ),
            {"s": spec.slug, "m": json.dumps(summary)},
        )
    return summary


async def seed(
    engine: AsyncEngine,
    guard: QlooGuard | None,
    mb: lineup.MusicBrainz,
    llm: LlmClient | None,
    limiter: Any,
    daily_limit: int,
    only: str | None = None,
) -> dict[str, str]:
    """Build every demo venue (or one). One failing venue does not stop the others; each outcome is reported."""
    out: dict[str, str] = {}
    for spec in SPECS:
        if only and spec.slug != only:
            continue
        try:
            await build_venue(engine, guard, mb, llm, limiter, daily_limit, spec)
            out[spec.slug] = "ready"
        except Exception as exc:
            log.exception("demo venue %s failed", spec.slug)
            out[spec.slug] = f"failed: {exc}"
    return out


async def venue(engine: AsyncEngine, slug: str) -> dict[str, Any] | None:
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT slug, name, city, blurb, tenant_id, business_id, status, summary, refreshed_at"
                    " FROM demo_venue WHERE slug = :s"
                ),
                {"s": slug},
            )
        ).first()
    if row is None:
        return None
    return {
        "slug": row.slug,
        "name": row.name,
        "city": row.city,
        "blurb": row.blurb,
        "tenant_id": UUID(str(row.tenant_id)),
        "business_id": UUID(str(row.business_id)),
        "status": row.status,
        "summary": dict(row.summary),
        "refreshed_at": row.refreshed_at.isoformat() if row.refreshed_at else None,
    }


async def listing(engine: AsyncEngine) -> list[dict[str, Any]]:
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT slug, name, city, blurb, summary, refreshed_at FROM demo_venue"
                    " WHERE status = 'ready' ORDER BY name"
                )
            )
        ).all()
    return [
        {
            "slug": r.slug,
            "name": r.name,
            "city": r.city,
            "blurb": r.blurb,
            "summary": dict(r.summary),
            "refreshed_at": r.refreshed_at.isoformat() if r.refreshed_at else None,
        }
        for r in rows
    ]


async def due_for_rebuild(engine: AsyncEngine) -> list[str]:
    """Slugs of ready venues not rebuilt for a week. A venue that never became ready is the seeder's to fix, not the job's."""
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT slug FROM demo_venue WHERE status = 'ready'"
                    " AND refreshed_at < now() - make_interval(hours => :h) ORDER BY refreshed_at"
                ),
                {"h": REBUILD_AFTER_HOURS},
            )
        ).all()
    return [r.slug for r in rows]
