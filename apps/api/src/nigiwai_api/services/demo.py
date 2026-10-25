"""Judge mode (PRD M25): a few real venues that anyone can open without an account.

Each demo venue is an ordinary business under one fixed system tenant that has no users, so nobody can sign in to it. Its
crowd is the public event lineups of the room (MusicBrainz, public domain) resolved to Qloo; its Soundchecks, suggested acts,
Booking Brief and map are built by the same code an owner's venue uses, ahead of time, so the first view never waits on a
slow Qloo call. A weekly job rebuilds them. Opening a demo venue reads stored results and costs no Qloo call.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

from qloo_guard import QlooGuard
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from ..db import transaction
from . import compare as compare_service
from . import grow, lineup, mapdata, soundcheck
from .llm import ModelClient

log = logging.getLogger("nigiwai.demo")

# The tenant that owns every demo venue. Migration 0009 creates it and the demo_venue table refuses any other tenant, so a
# demo row can never expose a real customer's venue.
DEMO_TENANT_ID = UUID("6e1c0de0-0000-4000-8000-00000000d3a0")
REBUILD_AFTER_HOURS = 24 * 7
REQUEST_KEEP_DAYS = 7  # a venue a visitor asked for is deleted after this
MAX_REQUESTED_KEPT = 20  # and at most this many are kept at once
RETRY_AFTER_HOURS = 1  # a request that failed may be asked for again after this
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


async def _create(
    engine: AsyncEngine, spec: Spec, place: lineup.PlaceHit, *, requested: bool = False
) -> UUID:
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
                "INSERT INTO demo_venue (slug, name, city, blurb, tenant_id, business_id, status, requested, place_mbid, requested_at)"
                " VALUES (:s, :n, :c, :bl, :t, :b, 'building', :rq, :mb, CASE WHEN :rq THEN now() END)"
            ),
            {
                "s": spec.slug,
                "n": spec.query,
                "c": spec.city,
                "bl": spec.blurb,
                "t": DEMO_TENANT_ID,
                "b": business_id,
                "rq": requested,
                "mb": place.mbid if requested else None,
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


async def refresh_grow(engine: AsyncEngine, guard: QlooGuard, business_id: UUID) -> None:
    """Grow for a demo venue is a stored result like its suggestions. Anything that goes wrong here must not fail the venue's
    build, and an earlier finished run stays in place if this one does not finish."""
    read = (
        "SELECT status, basis_kind, basis_ref, result, error FROM grow_run WHERE business_id = :b"
    )
    async with transaction(engine, tenant_id=DEMO_TENANT_ID) as conn:
        before = (await conn.execute(text(read), {"b": business_id})).first()
    try:
        await grow.run_job(engine, guard, DEMO_TENANT_ID, business_id)
    except Exception:
        log.exception("grow could not be run for demo venue %s", business_id)
    async with transaction(engine, tenant_id=DEMO_TENANT_ID) as conn:
        after = (await conn.execute(text(read), {"b": business_id})).first()
        if (
            (after is None or after.status != "ready")
            and before is not None
            and before.status == "ready"
        ):
            await conn.execute(
                text(
                    "UPDATE grow_run SET status = 'ready', basis_kind = :k, basis_ref = :r, result = CAST(:d AS jsonb),"
                    " error = NULL, updated_at = now() WHERE business_id = :b"
                ),
                {
                    "b": business_id,
                    "k": before.basis_kind,
                    "r": before.basis_ref,
                    "d": json.dumps(before.result),
                },
            )


async def build_venue(
    engine: AsyncEngine,
    guard: QlooGuard | None,
    mb: lineup.MusicBrainz,
    llm: ModelClient | None,
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
        await refresh_grow(engine, guard, business_id)
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
    llm: ModelClient | None,
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
                    "SELECT slug, name, city, blurb, tenant_id, business_id, status, summary, refreshed_at, requested, requested_at,"
                    " place_mbid, error"
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
        "requested": bool(row.requested),
        "expires_at": (row.requested_at + timedelta(days=REQUEST_KEEP_DAYS)).isoformat()
        if row.requested and row.requested_at
        else None,
        "retry_at": (row.requested_at + timedelta(hours=RETRY_AFTER_HOURS)).isoformat()
        if row.requested and row.requested_at
        else None,
        "place_mbid": row.place_mbid,
        "error": row.error,
    }


async def listing(engine: AsyncEngine) -> list[dict[str, Any]]:
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT slug, name, city, blurb, summary, refreshed_at FROM demo_venue"
                    " WHERE status = 'ready' AND NOT requested ORDER BY name"
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


async def missing_grow(engine: AsyncEngine) -> list[UUID]:
    """Business ids of ready demo venues with no finished Grow run: venues built before Grow existed pick it up on the next look,
    without a full rebuild."""
    async with engine.connect() as conn:
        venues = (
            await conn.execute(
                text("SELECT business_id FROM demo_venue WHERE status = 'ready' AND NOT requested")
            )
        ).all()
    lacking: list[UUID] = []
    for v in venues:
        business_id = UUID(str(v.business_id))
        async with transaction(engine, tenant_id=DEMO_TENANT_ID) as conn:
            done = (
                await conn.execute(
                    text("SELECT 1 FROM grow_run WHERE business_id = :b AND status = 'ready'"),
                    {"b": business_id},
                )
            ).first()
        if done is None:
            lacking.append(business_id)
    return lacking


async def due_for_rebuild(engine: AsyncEngine) -> list[str]:
    """Slugs of ready venues not rebuilt for a week. A venue that never became ready is the seeder's to fix, not the job's."""
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT slug FROM demo_venue WHERE status = 'ready' AND NOT requested"
                    " AND refreshed_at < now() - make_interval(hours => :h) ORDER BY refreshed_at"
                ),
                {"h": REBUILD_AFTER_HOURS},
            )
        ).all()
    return [r.slug for r in rows]


# ---------------------------------------------------------------------------------------------------- venues a visitor asks for
def slug_for(place: lineup.PlaceHit) -> str:
    """req-<name>-<six characters of the MusicBrainz id>: readable, within the table's slug rule, and one per place."""
    words = (
        re.sub(r"[^a-z0-9]+", "-", place.name.casefold().encode("ascii", "ignore").decode())
        .strip("-")[:22]
        .strip("-")
    )
    return f"req-{words or 'venue'}-{place.mbid.replace('-', '')[:6]}"


def spec_for(place: lineup.PlaceHit, slug: str) -> Spec:
    where = place.area or "an unnamed area"
    return Spec(
        slug,
        place.name,
        place.area or "",
        place.area or "Unknown area",
        "UTC",  # the room's own time zone is not in MusicBrainz; a demo venue has no scans, so nothing depends on it
        f"A venue a visitor asked for in {where}, read from the public lineups of its past events.",
    )


def reason_for(error: str | None) -> str:
    """What a visitor is told when a build failed: the product's own reason when it has one, never a stack trace or a class name."""
    if error and error.startswith("DemoError: "):
        return error[len("DemoError: ") :]
    return "Something went wrong while building this venue. Please try again in a little while."


async def places_known(engine: AsyncEngine, mbids: list[str]) -> dict[str, dict[str, str]]:
    """The demo venues already built or building for these MusicBrainz places: mbid -> {slug, status}."""
    if not mbids:
        return {}
    out: dict[str, dict[str, str]] = {}
    async with transaction(engine, tenant_id=DEMO_TENANT_ID) as conn:
        for r in (
            await conn.execute(
                text(
                    "SELECT d.slug, d.status, coalesce(d.place_mbid, l.place_mbid) AS mbid FROM demo_venue d"
                    " LEFT JOIN lineup_profile l ON l.business_id = d.business_id"
                    " WHERE coalesce(d.place_mbid, l.place_mbid) = ANY(:m)"
                ),
                {"m": mbids},
            )
        ).all():
            out[r.mbid] = {"slug": r.slug, "status": r.status}
    return out


class RequestRefused(Exception):
    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.status = status


async def request_venue(
    engine: AsyncEngine, place: lineup.PlaceHit, admit: Callable[[], Awaitable[None]]
) -> dict[str, str]:
    """A visitor asks for a venue. One row per place: asking again for one that is built, building or recently failed just points at it.
    A new one makes its business and location now (cheap) and queues the build for the worker (minutes, and Qloo calls); `admit` is
    called just before that and may refuse with an HTTP error, so a look at a venue that already exists never spends the day's allowance."""
    if place.lat is None or place.lon is None:
        raise RequestRefused(
            "MusicBrainz has no position for that venue, so it cannot be placed on a map.", 422
        )
    known = (await places_known(engine, [place.mbid])).get(place.mbid)
    slug = slug_for(place)
    if known is not None:
        if known["status"] != "failed":
            return {"slug": known["slug"], "status": known["status"]}
        async with engine.connect() as conn:
            stale = (
                await conn.execute(
                    text(
                        "SELECT 1 FROM demo_venue WHERE slug = :s AND requested AND coalesce(requested_at, now() - interval '1 year')"
                        " < now() - make_interval(hours => :h)"
                    ),
                    {"s": known["slug"], "h": RETRY_AFTER_HOURS},
                )
            ).first()
        if stale is None:
            return {"slug": known["slug"], "status": "failed"}
        await admit()
        async with transaction(engine, tenant_id=DEMO_TENANT_ID) as conn:
            await conn.execute(
                text(
                    "UPDATE demo_venue SET status = 'building', error = NULL, requested_at = now() WHERE slug = :s"
                ),
                {"s": known["slug"]},
            )
        await _enqueue(engine, known["slug"], place)
        return {"slug": known["slug"], "status": "building"}
    async with engine.connect() as conn:
        kept = (
            await conn.execute(
                text("SELECT count(*) FROM demo_venue WHERE requested AND status <> 'failed'")
            )
        ).scalar_one()
    if int(kept) >= MAX_REQUESTED_KEPT:
        raise RequestRefused("The demo is busy with other requests. Please try again later.", 429)
    await admit()
    try:
        await _create(engine, spec_for(place, slug), place, requested=True)
    except IntegrityError:
        # Two visitors asked for the same place at the same moment: the other one's request made it, and is the one that builds it.
        raced = (await places_known(engine, [place.mbid])).get(place.mbid)
        if raced is None:
            raise
        return {"slug": raced["slug"], "status": raced["status"]}
    await _enqueue(engine, slug, place)
    return {"slug": slug, "status": "building"}


async def _enqueue(engine: AsyncEngine, slug: str, place: lineup.PlaceHit) -> None:
    async with transaction(engine, tenant_id=DEMO_TENANT_ID) as conn:
        business_id = (
            await conn.execute(
                text("SELECT business_id FROM demo_venue WHERE slug = :s"), {"s": slug}
            )
        ).scalar_one()
        await conn.execute(
            text(
                "INSERT INTO job (kind, tenant_id, business_id, payload) VALUES ('demo_build', :t, :b, CAST(:p AS jsonb))"
                " ON CONFLICT (kind, business_id) WHERE state = 'pending' DO NOTHING"
            ),
            {
                "t": DEMO_TENANT_ID,
                "b": business_id,
                "p": json.dumps(
                    {
                        "slug": slug,
                        "mbid": place.mbid,
                        "name": place.name,
                        "area": place.area,
                        "address": place.address,
                        "kind": place.kind,
                        "lat": place.lat,
                        "lon": place.lon,
                    }
                ),
            },
        )


def place_from(payload: dict[str, Any]) -> lineup.PlaceHit:
    return lineup.PlaceHit(
        str(payload["mbid"]),
        str(payload["name"]),
        payload.get("area"),
        payload.get("address"),
        payload.get("kind"),
        payload.get("lat"),
        payload.get("lon"),
    )


async def build_requested(
    engine: AsyncEngine,
    guard: QlooGuard | None,
    mb: lineup.MusicBrainz,
    llm: ModelClient | None,
    limiter: Any,
    daily_limit: int,
    payload: dict[str, Any],
) -> str:
    """The worker's side of a request. A venue whose public lineup is too thin is a result to tell the visitor, not a fault to retry."""
    place = place_from(payload)
    spec = spec_for(place, str(payload["slug"]))
    try:
        await build_venue(engine, guard, mb, llm, limiter, daily_limit, spec, place)
    except DemoError as exc:
        log.info("requested demo venue %s: %s", spec.slug, exc)
        return "failed"
    except Exception:
        # build_venue has already marked the venue failed. A retry would spend another hundred Qloo calls for a visitor who
        # can simply ask again, so a fault is logged and the job ends here.
        log.exception("requested demo venue %s could not be built", spec.slug)
        return "failed"
    return "ready"


async def expire_requested(engine: AsyncEngine) -> int:
    """Delete venues visitors asked for once they are a week old, and mark as failed any that never finished building. The business
    goes and the cascade takes the demo row, the lineup, the suggestions, the checks and the rest with it."""
    async with transaction(engine, tenant_id=DEMO_TENANT_ID) as conn:
        await conn.execute(
            text(
                "UPDATE demo_venue SET status = 'failed', error = 'DemoError: Building this venue took too long. Please ask for it again.'"
                " WHERE requested AND status = 'building' AND requested_at < now() - interval '3 hours'"
            )
        )
        gone = (
            await conn.execute(
                text(
                    "DELETE FROM business WHERE id IN (SELECT business_id FROM demo_venue WHERE requested"
                    " AND requested_at < now() - make_interval(days => :d)) RETURNING id"
                ),
                {"d": REQUEST_KEEP_DAYS},
            )
        ).all()
    return len(gone)
