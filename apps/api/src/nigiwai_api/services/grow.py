"""Grow (PRD M8): who else might come, who already serves the crowd nearby, and lookalike venues elsewhere.

A run asks Qloo a bounded set of questions about the venue's groups (about 25 calls), keeps our own derived record of the answers in
`grow_run`, and the page reads that record: opening it makes no Qloo call. What the answers are allowed to say is decided in
grow_model.py, from checks made on the owner's own groups every run. Every place is looked up once more for Qloo's closure flag and a
place marked closed is left off; an open flag is Qloo's word, not a confirmation, and the page says so.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import UTC, datetime
from difflib import SequenceMatcher
from typing import Any
from uuid import UUID, uuid4

from nigiwai_fit import Group
from nigiwai_tribes import place
from qloo_guard import (
    AreaRef,
    ArtistInsights,
    CallContext,
    EntitiesRequest,
    Entity,
    GeoPoint,
    GuardError,
    PlaceCategory,
    PlaceInsights,
    QlooGuard,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from ..db import transaction
from . import grow_model as gm
from . import soundcheck, tribes
from .card import PLACE_CATEGORY
from .mapdata import _calls as qloo_calls

log = logging.getLogger("nigiwai.grow")

ARTIST = "urn:entity:artist"
NEIGHBOURS_TAKE = 20
PLACES_TAKE = 20
WIDE_TAKE = 50
WIDE_FACTOR = 5
WIDE_MIN_EXTRA_M = 2000
WIDE_MAX_M = 50_000
CROWD_SEEDS = 5
OWN_VENUE_M = 40  # a place this close to the venue's own point is the venue itself
SAME_NAME = 0.85
ENTITY_BATCH = 50
MIN_SEEDS = soundcheck.MIN_SEEDS


class GrowError(Exception):
    """A run that cannot be made, with wording a person can act on."""

    def __init__(self, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class Where:
    lat: float
    lon: float
    radius_m: int
    names: tuple[str, ...]  # the venue's own names, to leave it out of its own neighbours
    category: PlaceCategory | None
    business_type: str

    @property
    def point(self) -> GeoPoint:
        return GeoPoint(lat=self.lat, lon=self.lon)

    @property
    def wide_m(self) -> int:
        return min(max(self.radius_m * WIDE_FACTOR, self.radius_m + WIDE_MIN_EXTRA_M), WIDE_MAX_M)


async def _where(engine: AsyncEngine, tenant_id: UUID, business_id: UUID) -> Where | None:
    async with transaction(engine, tenant_id=tenant_id) as conn:
        business = (
            await conn.execute(
                text("SELECT name, type FROM business WHERE id = :b"), {"b": business_id}
            )
        ).first()
        home = (
            await conn.execute(
                text(
                    "SELECT name, radius_m, ST_Y(geom::geometry) AS lat, ST_X(geom::geometry) AS lon FROM location"
                    " WHERE business_id = :b AND geom IS NOT NULL ORDER BY created_at, id LIMIT 1"
                ),
                {"b": business_id},
            )
        ).first()
    if business is None or home is None:
        return None
    names = tuple(dict.fromkeys(n for n in (business.name, home.name) if n))
    return Where(
        lat=float(home.lat),
        lon=float(home.lon),
        radius_m=int(home.radius_m),
        names=names,
        category=PLACE_CATEGORY.get(business.type),
        business_type=business.type,
    )


def _same(a: str, b: str) -> float:
    def norm(s: str) -> str:
        return "".join(ch for ch in s.casefold() if ch.isalnum() or ch == " ").strip()

    return SequenceMatcher(None, norm(a), norm(b)).ratio()


def _signal_ignored(res: Any) -> bool:
    """Qloo dropped a seed, or gave every result the same score: either way the answer is not about the seeds that were sent."""
    return any(e.rule in ("T12-dropped-seed", "T7-flat-affinity") for e in res.rule_events)


# ----------------------------------------------------------------------------------------------------- the crowd
async def _guest_presence(
    engine: AsyncEngine, tenant_id: UUID, business_id: UUID, basis: soundcheck.Basis
) -> gm.Presence:
    """The genre tags the guests' artist picks carry: how many guests carry each, and for each group the membership-weighted share
    of its members who do. Only guests with at least one artist pick are counted, since the rest say nothing about acts."""
    async with transaction(engine, tenant_id=tenant_id) as conn:
        prev = await tribes.latest(conn, business_id)
        rows = await tribes._rows(conn, business_id)
    if prev is None or str(prev.version) != basis.ref:
        raise GrowError("Your groups changed while this was running. Try again.", 409)
    result = tribes._from_json(prev.result)
    if result is None:
        raise GrowError("The stored groups could not be read. Refit them on My people.")
    shown = [t for t in result.tribes if t.shown]
    index_of = {t.index: k for k, t in enumerate(result.tribes)}
    carriers: dict[str, int] = {}
    names: dict[str, str] = {}
    num: dict[int, dict[str, float]] = {t.index: {} for t in shown}
    den: dict[int, float] = {t.index: 0.0 for t in shown}
    total = 0
    for r in tribes._respondents(rows):
        artist_picks = [p for p in r.picks if p.type == ARTIST]
        if not artist_picks:
            continue
        placed = place(result, list(r.picks))
        if placed is None:
            continue
        mine: dict[str, str] = {}
        for p in artist_picks:
            mine.update(gm.genre_tags([(t.tag_id, t.name, t.type) for t in p.tags]))
        total += 1
        for tid, nm in mine.items():
            carriers[tid] = carriers.get(tid, 0) + 1
            names.setdefault(tid, nm)
        for t in shown:
            w = float(placed.memberships[index_of[t.index]])
            den[t.index] += w
            for tid in mine:
                num[t.index][tid] = num[t.index].get(tid, 0.0) + w
    share = {
        g: {tid: v / den[g] for tid, v in tags.items()} if den[g] > 0 else {}
        for g, tags in num.items()
    }
    return gm.Presence("guests", total, gm.MIN_GROUP_GUESTS, carriers, share, names)


async def _lineup_presence(
    engine: AsyncEngine, tenant_id: UUID, business_id: UUID, basis: soundcheck.Basis
) -> gm.Presence:
    """With no guests yet, the room's own acts stand in for the crowd: the genres across the acts that play there, and for each
    scene the share of its lead acts that carry each."""
    async with transaction(engine, tenant_id=tenant_id) as conn:
        row = await soundcheck._lineup_row(conn, business_id)
    doc = (row.result if row else None) or {}
    acts = [a for a in doc.get("acts", []) if a.get("entity_id")]
    tags_of: dict[str, dict[str, str]] = {
        a["entity_id"]: dict(gm.genre_tags([tuple(t) for t in a.get("tags", [])])) for a in acts
    }
    carriers: dict[str, int] = {}
    names: dict[str, str] = {}
    for tags in tags_of.values():
        for tid, nm in tags.items():
            carriers[tid] = carriers.get(tid, 0) + 1
            names.setdefault(tid, nm)
    share: dict[int, dict[str, float]] = {}
    for g in basis.groups:
        leads = [e for e, _ in basis.seed_pool.get(g.index, []) if e in tags_of]
        counts: dict[str, int] = {}
        for e in leads:
            for tid in tags_of[e]:
                counts[tid] = counts.get(tid, 0) + 1
        share[g.index] = {tid: c / len(leads) for tid, c in counts.items()} if leads else {}
    return gm.Presence("acts", len(acts), gm.MIN_GROUP_ACTS, carriers, share, names)


# --------------------------------------------------------------------------------------------------------- Qloo
async def _eligible(
    guard: QlooGuard, tenant_id: UUID, trace: UUID, candidates: list[tuple[str, str]]
) -> list[tuple[str, str]]:
    """The first SEED_N seeds Qloo can use, probed under this run's own trace so the probes show in its call list."""
    ctx = CallContext(trace_id=trace, purpose="lineup", tenant_id=tenant_id)
    pool = candidates[: soundcheck.SEED_POOL]
    verdicts = await guard.ensure_eligible(tuple(e for e, _ in pool), ctx)
    return [(e, n) for e, n in pool if verdicts.get(e) is True][: soundcheck.SEED_N]


async def _neighbours(
    guard: QlooGuard, ctx: CallContext, seeds: list[tuple[str, str]], banned: set[str]
) -> list[gm.Neighbour] | None:
    """Qloo's neighbouring acts for a group's seeds. The same request Soundcheck's suggestions make, so a recent one is answered
    from the private cache. None when Qloo did not answer, or answered without regard to the seeds."""
    res = await guard.insights(
        ArtistInsights(signal_entities=tuple(e for e, _ in seeds), take=NEIGHBOURS_TAKE), ctx
    )
    if not res.ok or _signal_ignored(res):
        return None
    return [
        gm.Neighbour(
            e.entity_id,
            e.name,
            float(e.affinity),
            gm.genre_tags([(t.tag_id, t.name, t.type or "") for t in e.tags]),
        )
        for e in res.items
        if e.entity_id not in banned and e.affinity is not None
    ]


async def _places_call(
    guard: QlooGuard,
    ctx: CallContext,
    where: Where,
    radius_m: int,
    seeds: tuple[str, ...],
    take: int,
) -> list[Entity] | None:
    """Places of the venue's kind inside an exact area, with the given seeds as the signal (none for the plain list). None when
    Qloo did not answer, or ignored a seed (then the list is not about those seeds)."""
    res = await guard.insights(
        PlaceInsights(
            signal_entities=seeds,
            area=AreaRef(center=where.point, radius_m=radius_m),
            category=where.category,
            take=take,
        ),
        ctx,
    )
    if not res.ok or (seeds and _signal_ignored(res)):
        return None
    return [e for e in res.items if e.location is not None]


class _Closure:
    """Qloo's closure flag for every place a run lists, asked once per place in batches of 50."""

    def __init__(self, guard: QlooGuard, ctx: CallContext) -> None:
        self.guard = guard
        self.ctx = ctx
        self.closed: set[str] = set()
        self.asked: set[str] = set()
        self.unanswered = False

    async def check(self, ids: list[str]) -> None:
        todo = [i for i in dict.fromkeys(ids) if i not in self.asked]
        for i in range(0, len(todo), ENTITY_BATCH):
            batch = todo[i : i + ENTITY_BATCH]
            self.asked.update(batch)
            try:
                res = await self.guard.entities(EntitiesRequest(entity_ids=tuple(batch)), self.ctx)
            except GuardError:
                self.unanswered = True
                continue
            if not res.ok:
                self.unanswered = True
                continue
            self.closed.update(e.entity_id for e in res.items if e.is_closed is True)


def _to_places(entities: list[Entity] | None, where: Where, closed: set[str]) -> list[gm.Place]:
    """Our own record of each open place, with the venue itself left out."""
    out: list[gm.Place] = []
    for e in entities or []:
        if e.location is None or e.entity_id in closed:
            continue
        metres = (
            round(e.distance_m)
            if e.distance_m is not None
            else round(where.point.distance_m(e.location))
        )
        if metres <= OWN_VENUE_M or any(_same(e.name, n) >= SAME_NAME for n in where.names):
            continue
        out.append(gm.Place(e.entity_id, e.name, metres, e.address, e.location.lat, e.location.lon))
    return out


def _crowd_seeds(order: list[int], seeds: dict[int, list[tuple[str, str]]]) -> tuple[str, ...]:
    """Up to five seeds that stand for the whole crowd: one from each group in turn, the biggest group first."""
    picked: list[str] = []
    depth = 0
    while len(picked) < CROWD_SEEDS and any(depth < len(seeds.get(g, [])) for g in order):
        for g in order:
            if depth < len(seeds.get(g, [])) and len(picked) < CROWD_SEEDS:
                e = seeds[g][depth][0]
                if e not in picked:
                    picked.append(e)
        depth += 1
    return tuple(picked)


# ----------------------------------------------------------------------------------------------------------- run
async def _places_part(
    guard: QlooGuard,
    ctx: CallContext,
    where: Where,
    groups: list[gm.GroupInfo],
    seeds: dict[int, list[tuple[str, str]]],
) -> dict[str, Any]:
    order = [g.index for g in sorted(groups, key=lambda g: (-g.share, g.index))]
    crowd = _crowd_seeds(order, seeds)
    usable = [g for g in groups if len(seeds.get(g.index, [])) >= MIN_SEEDS]
    r, wide = where.radius_m, where.wide_m
    closure = _Closure(guard, ctx)

    async def safe(coro: Awaitable[list[Entity] | None]) -> list[Entity] | None:
        try:
            return await coro
        except GuardError as exc:
            log.info("grow places call refused: %s", exc)
            return None

    async def nothing() -> list[Entity] | None:
        return None

    with_crowd = len(crowd) >= MIN_SEEDS
    answers = await asyncio.gather(
        safe(_places_call(guard, ctx, where, r, (), PLACES_TAKE)),
        safe(_places_call(guard, ctx, where, r, crowd, PLACES_TAKE)) if with_crowd else nothing(),
        safe(_places_call(guard, ctx, where, wide, (), WIDE_TAKE)),
        safe(_places_call(guard, ctx, where, wide, crowd, WIDE_TAKE)) if with_crowd else nothing(),
        *(
            safe(
                _places_call(guard, ctx, where, r, tuple(e for e, _ in seeds[g.index]), PLACES_TAKE)
            )
            for g in usable
        ),
    )
    plain_in, crowd_in, plain_wide, crowd_wide = answers[:4]
    group_in = {g.index: lst for g, lst in zip(usable, answers[4:], strict=True) if lst is not None}

    def ids_of(*lists: list[Entity] | None) -> list[str]:
        return [e.entity_id for lst in lists if lst for e in lst]

    await closure.check(ids_of(plain_in, crowd_in, plain_wide, crowd_wide, *group_in.values()))

    def build(lst: list[Entity] | None) -> list[gm.Place]:
        return _to_places(lst, where, closure.closed)

    # a crowd list Qloo would not answer for falls back to the plain list: it is then honestly "near you", never "matched"
    near = gm.places_section(
        gm.PlaceLists(
            crowd=build(crowd_in if crowd_in is not None else plain_in),
            plain=build(plain_in),
            by_group={g: build(lst) for g, lst in group_in.items()},
        ),
        groups,
        label="Who serves your crowd nearby",
    )
    near["note"] = gm.nearby_note(near)
    near["gaps"] = gm.gaps_from(near)

    wide_groups: dict[int, list[Entity]] = {}
    if near["told_apart"]:
        got = await asyncio.gather(
            *(
                safe(
                    _places_call(
                        guard, ctx, where, wide, tuple(e for e, _ in seeds[g.index]), WIDE_TAKE
                    )
                )
                for g in usable
            )
        )
        wide_groups = {g.index: lst for g, lst in zip(usable, got, strict=True) if lst is not None}
        await closure.check(ids_of(*wide_groups.values()))
    far = gm.places_section(
        gm.PlaceLists(
            crowd=build(crowd_wide if crowd_wide is not None else plain_wide),
            plain=build(plain_wide),
            by_group={g: build(lst) for g, lst in wide_groups.items()},
        ),
        groups,
        label="Lookalike places further out",
        outside_only_m=r,
    )
    far["note"] = gm.elsewhere_note(far)
    return {
        "status": "ok",
        "category": where.category.name.lower() if where.category else None,
        "radius_m": r,
        "wide_radius_m": wide,
        "nearby": near,
        "elsewhere": far,
        "dropped_closed": len(closure.closed),
        "closure_unanswered": closure.unanswered,
    }


async def compute(
    engine: AsyncEngine, guard: QlooGuard, tenant_id: UUID, business_id: UUID
) -> dict[str, Any]:
    try:
        basis = await soundcheck.load_basis(engine, tenant_id, business_id)
    except soundcheck.SoundcheckError as exc:
        raise GrowError(str(exc)) from exc
    where = await _where(engine, tenant_id, business_id)
    trace = uuid4()
    elig = uuid4()
    ctx = CallContext(trace_id=trace, purpose="board", tenant_id=tenant_id)
    groups = [gm.GroupInfo(g.index, g.label, g.share, g.size) for g in basis.groups]

    banned = (
        set(basis.played)
        | {e for pool in basis.seed_pool.values() for e, _ in pool}
        | {e for e, _, _ in basis.pool}
    )
    seeds: dict[int, list[tuple[str, str]]] = {}
    skipped: dict[int, str] = {}

    async def read(g: Group) -> tuple[int, list[gm.Neighbour] | None]:
        try:
            got = await _eligible(guard, tenant_id, elig, basis.seed_pool.get(g.index, []))
            seeds[g.index] = got
            if len(got) < MIN_SEEDS:
                skipped[g.index] = (
                    "Qloo could use fewer than three of this group's favourites as a starting point."
                )
                return g.index, None
            found = await _neighbours(guard, ctx, got, banned)
        except GuardError as exc:
            log.info("grow neighbours refused: %s", exc)
            found = None
        if found is None and g.index not in skipped:
            skipped[g.index] = (
                "Qloo did not give an answer that depended on this group's favourites."
            )
        return g.index, found

    read_all = await asyncio.gather(*(read(g) for g in basis.groups))
    neighbours = {i: ns for i, ns in read_all if ns is not None}
    if not neighbours:
        raise GrowError(
            "Qloo gave no neighbouring acts for any of your groups, so there is nothing to build on yet.",
            404,
        )

    presence = (
        await _guest_presence(engine, tenant_id, business_id, basis)
        if basis.kind == "guests"
        else await _lineup_presence(engine, tenant_id, business_id, basis)
    )
    ghosts = gm.ghost_section(groups, neighbours, presence, skipped)

    if where is None:
        places: dict[str, Any] = {
            "status": "unavailable",
            "reason": "Add your address on Your venue so places can be looked up around it.",
        }
    elif where.category is None:
        places = {
            "status": "unavailable",
            "reason": "Place suggestions need a bar, live music venue, cafe, restaurant or hotel bar as the business type.",
        }
    else:
        places = await _places_part(guard, ctx, where, groups, seeds)

    calls = [str(elig), str(trace)]
    return {
        "basis": {
            "kind": basis.kind,
            "ref": basis.ref,
            "label": basis.label,
            "provisional": basis.crowd.provisional,
        },
        "groups": [
            {"index": g.index, "label": g.label, "share": round(g.share, 3)} for g in groups
        ],
        "ghosts": ghosts,
        "places": places,
        "trace_ids": calls,
        "generated_at": datetime.now(UTC).isoformat(),
    }


# ------------------------------------------------------------------------------------------------------ stored run
async def _current_ref(engine: AsyncEngine, tenant_id: UUID, business_id: UUID) -> dict[str, Any]:
    """What a run would use right now, and whether anything can be built, without a Qloo call."""
    status = await soundcheck.basis_status(engine, tenant_id, business_id)
    kind = status["use"]
    ref: str | None = None
    if kind == "guests":
        ref = str(status["guests"]["version"])
    elif kind == "lineup":
        async with transaction(engine, tenant_id=tenant_id) as conn:
            row = await soundcheck._lineup_row(conn, business_id)
        ref = row.finished_at.isoformat() if row and row.finished_at else "0"
    return {"kind": kind, "ref": ref, "status": status}


async def get(engine: AsyncEngine, tenant_id: UUID, business_id: UUID) -> dict[str, Any]:
    """What the Grow page shows. Reads stored rows only."""
    current = await _current_ref(engine, tenant_id, business_id)
    async with transaction(engine, tenant_id=tenant_id) as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT status, basis_kind, basis_ref, result, error, updated_at FROM grow_run"
                    " WHERE business_id = :b"
                ),
                {"b": business_id},
            )
        ).first()
    can_build = current["kind"] is not None
    out: dict[str, Any] = {
        "can_build": can_build,
        "basis_now": {"kind": current["kind"], "ref": current["ref"]},
        "run": None,
        "updated_at": None,
        "error": None,
    }
    if not can_build:
        out["state"] = "no_crowd"
        out["reason"] = (
            "There is no crowd to read yet. Collect at least 60 guests, or start from public lineups on My people."
        )
        return out
    if row is None:
        out["state"] = "not_run"
        out["reason"] = "Nothing has been looked up yet. A look-up finds tastes that sit next to your groups' and the places that serve them."
        return out
    out["updated_at"] = row.updated_at.isoformat()
    out["error"] = row.error
    if row.status in ("queued", "running"):
        out["state"] = row.status
        out["reason"] = "Looking things up. This takes a minute or two and the page updates itself."
        return out
    if row.status == "failed":
        out["state"] = "failed"
        out["reason"] = row.error or "The last run failed."
        return out
    out["run"] = row.result
    stale = (row.basis_kind, row.basis_ref) != (current["kind"], current["ref"])
    out["state"] = "stale" if stale else "ready"
    out["reason"] = (
        "Made for an older version of your groups. Run it again to use the current one."
        if stale
        else ""
    )
    return out


async def calls(
    engine: AsyncEngine, tenant_id: UUID, business_id: UUID
) -> list[dict[str, Any]] | None:
    """The Qloo calls behind the stored run, for the inspector."""
    async with transaction(engine, tenant_id=tenant_id) as conn:
        row = (
            await conn.execute(
                text("SELECT result FROM grow_run WHERE business_id = :b AND status = 'ready'"),
                {"b": business_id},
            )
        ).first()
    if row is None or not isinstance(row.result, dict):
        return None
    traces = [t for t in row.result.get("trace_ids", []) if isinstance(t, str)]
    return await qloo_calls(engine, tenant_id, traces) if traces else []


async def run_job(
    engine: AsyncEngine, guard: QlooGuard | None, tenant_id: UUID, business_id: UUID
) -> None:
    """The worker's side: mark the row running, compute, and store either the result or the reason it failed."""
    async with transaction(engine, tenant_id=tenant_id) as conn:
        await conn.execute(
            text(
                "INSERT INTO grow_run (business_id, tenant_id, status) VALUES (:b, :t, 'running')"
                " ON CONFLICT (business_id) DO UPDATE SET status = 'running', error = NULL, updated_at = now()"
            ),
            {"b": business_id, "t": tenant_id},
        )
    try:
        if guard is None:
            raise GrowError("Qloo is not configured on this server, so Grow cannot run.", 503)
        doc = await compute(engine, guard, tenant_id, business_id)
    except GrowError as exc:
        async with transaction(engine, tenant_id=tenant_id) as conn:
            await conn.execute(
                text(
                    "UPDATE grow_run SET status = 'failed', error = :e, result = NULL, updated_at = now()"
                    " WHERE business_id = :b"
                ),
                {"b": business_id, "e": str(exc)[:500]},
            )
        return
    async with transaction(engine, tenant_id=tenant_id) as conn:
        await conn.execute(
            text(
                "UPDATE grow_run SET status = 'ready', error = NULL, basis_kind = :k, basis_ref = :r,"
                " result = CAST(:d AS jsonb), updated_at = now() WHERE business_id = :b"
            ),
            {
                "b": business_id,
                "k": doc["basis"]["kind"],
                "r": doc["basis"]["ref"],
                "d": json.dumps(doc),
            },
        )
