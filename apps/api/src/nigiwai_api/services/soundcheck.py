"""Soundcheck: how well an act fits a venue's crowd (PRD M19, M9; ARCHITECTURE 5.3 and 14.2).

The crowd comes from the venue's own guests when their groups exist, and otherwise from public lineups (provisional).
Either way it is a set of groups, each with a few seed acts. For one group, Qloo is asked for the affinity of the candidate
and of up to twenty reference acts from the venue's own pool, in a single call; the pure Fit package turns the answers
into a score. Nothing here invents a number: every figure traces to one of those calls or to a survey or lineup count.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from nigiwai_fit import (
    Constraint,
    Crowd,
    Group,
    Observation,
    Weights,
    compute_fit,
    to_dict,
)
from nigiwai_tribes import SceneAct, Tag, place, scene_groups
from qloo_guard import ArtistInsights, CallContext, QlooGuard
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from ..db import transaction
from . import tribes

log = logging.getLogger("nigiwai.soundcheck")

ARTIST = "urn:entity:artist"
SEED_N = 5  # seeds sent as the signal for one group
SEED_POOL = (
    8  # candidates for seeds, so a few that fail the eligibility probe do not leave a group empty
)
MIN_SEEDS = 3
REF_N = 20  # reference acts per call (ARCHITECTURE 5.3)
POOL_N = 40
BATCH = (
    30  # candidates scored in one call (the Guard allows 50 ids in total, including the references)
)
MIN_EVENTS = 10  # public lineups: Fit needs at least this many events with a lineup (PRD M19)
MIN_ACTS = 20  # and at least this many distinct acts Qloo could match
MIN_RESPONDENTS = 30  # guests: under this there is no number (ARCHITECTURE 5.3)

WEIGHTS = Weights()


class SoundcheckError(Exception):
    """A request that cannot be answered, with wording a person can act on."""

    def __init__(self, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class Candidate:
    entity_id: str
    name: str
    tags: list[tuple[str, str, str]] = field(default_factory=list)  # (tag_id, name, type)
    popularity: float | None = None
    description: str | None = None
    release_year: int | None = None


@dataclass
class Basis:
    kind: str  # "guests" | "lineup"
    ref: str  # the tribe version number, or when the lineup profile finished
    label: str
    groups: list[Group]
    seed_pool: dict[int, list[tuple[str, str]]]  # group index -> (entity id, name), best first
    pool: list[
        tuple[str, str, float]
    ]  # (entity id, name, weight): the venue's own acts, strongest first
    crowd: Crowd
    played: dict[str, int]  # entity id -> nights played here, when public lineups are known
    venue_weekday: tuple[float, ...] | None
    source: dict[str, Any]


# --------------------------------------------------------------------------------------------------- the crowd
async def _location(conn: Any, business_id: UUID) -> Any:
    return (
        await conn.execute(
            text(
                "SELECT id, name, capacity, curfew, excluded_genres, show_nights FROM location"
                " WHERE business_id = :b ORDER BY created_at, id LIMIT 1"
            ),
            {"b": business_id},
        )
    ).first()


def _weekday_vector(rhythm: list[list[float]]) -> tuple[float, ...] | None:
    """A group's scans by weekday (Monday first) from its 7 x 24 rhythm grid, as shares."""
    if len(rhythm) != 7:
        return None
    totals = [float(sum(row)) for row in rhythm]
    s = sum(totals)
    return tuple(t / s for t in totals) if s > 0 else None


async def _lineup_row(conn: Any, business_id: UUID) -> Any:
    return (
        await conn.execute(
            text(
                "SELECT status, result, finished_at, place_name FROM lineup_profile WHERE business_id = :b"
            ),
            {"b": business_id},
        )
    ).first()


async def basis_status(engine: AsyncEngine, tenant_id: UUID, business_id: UUID) -> dict[str, Any]:
    """What Soundcheck can use for this venue, without making any Qloo call."""
    async with transaction(engine, tenant_id=tenant_id) as conn:
        prev = await tribes.latest(conn, business_id)
        lineup = await _lineup_row(conn, business_id)
    out: dict[str, Any] = {"guests": None, "lineup": None, "use": None}
    if prev is not None:
        shown = [t for t in prev.result.get("tribes", []) if t.get("shown")]
        usable = prev.state in ("provisional", "named") and bool(shown)
        out["guests"] = {
            "state": prev.state,
            "version": prev.version,
            "n": prev.n,
            "groups": len(shown),
            "usable": usable,
        }
    if lineup is not None:
        doc = lineup.result or {}
        events = int((doc.get("events") or {}).get("with_lineup", 0))
        acts = len(doc.get("acts") or [])
        resolved = int((doc.get("performers") or {}).get("resolved", 0))
        out["lineup"] = {
            "status": lineup.status,
            "place": lineup.place_name,
            "events": events,
            "acts": resolved,
            "sufficient": events >= MIN_EVENTS and resolved >= MIN_ACTS,
            "needs_refresh": lineup.status == "ready"
            and doc.get("state") == "profile"
            and acts == 0,
            "usable": lineup.status == "ready" and doc.get("state") == "profile" and acts > 0,
        }
    if out["guests"] and out["guests"]["usable"]:
        out["use"] = "guests"
    elif out["lineup"] and out["lineup"]["usable"]:
        out["use"] = "lineup"
    return out


async def load_basis(
    engine: AsyncEngine, tenant_id: UUID, business_id: UUID, prefer: str | None = None
) -> Basis:
    status = await basis_status(engine, tenant_id, business_id)
    kind = prefer or status["use"]
    if kind == "guests" and status["guests"] and status["guests"]["usable"]:
        return await _guest_basis(engine, tenant_id, business_id)
    if kind == "lineup" and status["lineup"] and status["lineup"]["usable"]:
        return await _lineup_basis(engine, tenant_id, business_id)
    if status["lineup"] and status["lineup"]["needs_refresh"]:
        raise SoundcheckError(
            "Your public lineup was built before Soundcheck existed. Rebuild it on My people, then try again."
        )
    raise SoundcheckError(
        "There is no crowd to check against yet. Collect at least 60 guests, or start from public lineups on My people."
    )


async def _played(conn: Any, business_id: UUID) -> dict[str, int]:
    row = await _lineup_row(conn, business_id)
    doc = (row.result if row else None) or {}
    return {a["entity_id"]: int(a["events"]) for a in doc.get("acts", []) if a.get("entity_id")}


async def _guest_basis(engine: AsyncEngine, tenant_id: UUID, business_id: UUID) -> Basis:
    async with transaction(engine, tenant_id=tenant_id) as conn:
        prev = await tribes.latest(conn, business_id)
        rows = await tribes._rows(conn, business_id)
        played = await _played(conn, business_id)
    assert prev is not None
    result = tribes._from_json(prev.result)
    if result is None:
        raise SoundcheckError("The stored groups could not be read. Refit them on My people.")
    respondents = tribes._respondents(rows)
    shown = [t for t in result.tribes if t.shown]
    index_of = {t.index: k for k, t in enumerate(result.tribes)}

    placed: list[tuple[Any, list[float]]] = []
    for r in respondents:
        p = place(result, list(r.picks))
        if p is not None:
            placed.append((r, p.memberships))
    if len(placed) < MIN_RESPONDENTS:
        raise SoundcheckError(
            f"Only {len(placed)} guests could be placed in your groups; Soundcheck needs at least {MIN_RESPONDENTS}."
        )

    weight: dict[int, dict[str, float]] = {t.index: {} for t in shown}
    support: dict[int, dict[str, int]] = {t.index: {} for t in shown}
    names: dict[str, str] = {}
    pick_count: dict[str, int] = {}
    for r, m in placed:
        for pick in r.picks:
            if pick.type != ARTIST:
                continue
            names[pick.entity_id] = pick.name
            pick_count[pick.entity_id] = pick_count.get(pick.entity_id, 0) + 1
            for t in shown:
                w = m[index_of[t.index]]
                weight[t.index][pick.entity_id] = weight[t.index].get(pick.entity_id, 0.0) + w
                if w >= 0.2:
                    support[t.index][pick.entity_id] = support[t.index].get(pick.entity_id, 0) + 1

    groups: list[Group] = []
    seed_pool: dict[int, list[tuple[str, str]]] = {}
    for t in shown:
        w_t = weight[t.index]
        ranked = sorted(
            (e for e, c in support[t.index].items() if c >= 2), key=lambda e: (-w_t[e], e)
        )[:SEED_POOL]
        seed_pool[t.index] = [(e, names[e]) for e in ranked]
        groups.append(
            Group(
                index=t.index,
                label=t.label,
                share=float(t.share),
                size=float(t.soft_size),
                seed_ids=tuple(e for e, _ in seed_pool[t.index][:SEED_N]),
                seed_names=tuple(n for _, n in seed_pool[t.index][:SEED_N]),
                weekday=_weekday_vector(t.rhythm),
            )
        )
    pool = [
        (e, names[e], float(c))
        for e, c in sorted(pick_count.items(), key=lambda kv: (-kv[1], kv[0]))
        if c >= 2
    ][:POOL_N]
    memberships = tuple(tuple(m[index_of[t.index]] for t in shown) for _, m in placed)
    crowd = Crowd(
        kind="guests",
        n=len(placed),
        provisional=prev.state != "named",
        sufficient=True,
        memberships=memberships,
    )
    return Basis(
        kind="guests",
        ref=str(prev.version),
        label=f"Your guests ({len(placed)}, groups version {prev.version})",
        groups=groups,
        seed_pool=seed_pool,
        pool=pool,
        crowd=crowd,
        played=played,
        venue_weekday=None,
        source={"tribe_version": prev.version, "input_hash": prev.input_hash},
    )


async def _lineup_basis(engine: AsyncEngine, tenant_id: UUID, business_id: UUID) -> Basis:
    async with transaction(engine, tenant_id=tenant_id) as conn:
        row = await _lineup_row(conn, business_id)
    assert row is not None
    assert row.result
    doc = row.result
    acts = [
        SceneAct(
            a["entity_id"],
            a["name"],
            int(a["events"]),
            tuple(Tag(t[0], t[1], t[2]) for t in a.get("tags", [])),
        )
        for a in doc.get("acts", [])
    ]
    scenes = scene_groups(acts)
    if not scenes:
        raise SoundcheckError(
            "The acts at this venue share too few tags for Qloo to tell scenes apart, so there is nothing to check against."
        )
    events = int((doc.get("events") or {}).get("with_lineup", 0))
    resolved = int((doc.get("performers") or {}).get("resolved", 0))
    sufficient = events >= MIN_EVENTS and resolved >= MIN_ACTS
    reason = (
        ""
        if sufficient
        else (
            f"Public lineups give {events} events with a lineup and {resolved} acts Qloo could match; "
            f"Soundcheck needs at least {MIN_EVENTS} events and {MIN_ACTS} acts."
        )
    )
    groups: list[Group] = []
    seed_pool: dict[int, list[tuple[str, str]]] = {}
    for s in scenes:
        seed_pool[s.index] = list(zip(s.seed_ids, s.seed_names, strict=True))
        groups.append(
            Group(
                index=s.index,
                label=s.label,
                share=s.share,
                size=float(s.size),
                seed_ids=tuple(s.seed_ids[:SEED_N]),
                seed_names=tuple(s.seed_names[:SEED_N]),
            )
        )
    pool = [
        (a.entity_id, a.name, float(a.events))
        for a in sorted(acts, key=lambda a: (-a.events, a.entity_id))
    ][:POOL_N]
    wd = doc.get("weekdays") or []
    venue_weekday = tuple(w / sum(wd) for w in wd) if len(wd) == 7 and sum(wd) > 0 else None
    place_name = row.place_name
    return Basis(
        kind="lineup",
        ref=row.finished_at.isoformat() if row.finished_at else "0",
        label=f"Public lineups at {place_name} ({events} events, {resolved} acts matched)",
        groups=groups,
        seed_pool=seed_pool,
        pool=pool,
        crowd=Crowd(
            kind="lineup", n=events, provisional=True, sufficient=sufficient, reason=reason
        ),
        played={a.entity_id: a.events for a in acts},
        venue_weekday=venue_weekday,
        source={"place": place_name, "events": events, "acts": resolved},
    )


# ------------------------------------------------------------------------------------------------- candidates
def _short(text_: object, limit: int = 180) -> str | None:
    """A description trimmed at a word boundary, so it never ends mid-word."""
    if not isinstance(text_, str) or not text_.strip():
        return None
    t = " ".join(text_.split())
    if len(t) <= limit:
        return t if t[-1] in ".!?…" else t + "…"
    return t[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def _norm(s: str) -> str:
    return " ".join(s.casefold().split())


async def load_candidate(engine: AsyncEngine, entity_id: str) -> Candidate:
    async with engine.begin() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT entity_id, name_nfc, type, types, tags, popularity, props FROM qloo_entity"
                    " WHERE entity_id = :e"
                ),
                {"e": entity_id},
            )
        ).first()
    if row is None:
        raise SoundcheckError("Search for the act first so Qloo can resolve it.", 404)
    if ARTIST not in list(row.types) and row.type != ARTIST:
        raise SoundcheckError("Soundcheck checks acts: pick an artist, not another kind of thing.")
    props = row.props or {}
    return Candidate(
        entity_id=row.entity_id,
        name=row.name_nfc,
        tags=[
            (t[0], t[1], t[2])
            if isinstance(t, list)
            else (t["tag_id"], t["name"], t.get("type", ""))
            for t in row.tags
        ],
        popularity=float(row.popularity) if row.popularity is not None else None,
        description=_short(props.get("short_description") or props.get("description")),
        release_year=props.get("release_year"),
    )


def constraints_for(candidate: Candidate, location: Any | None, basis: Basis) -> list[Constraint]:
    """Checks that come from the owner's own profile. Only excluded genres can be tested against an act: Qloo has no
    stage size, sound level or fee for acts, so the other fields are shown and plainly not scored."""
    out: list[Constraint] = []
    excluded = [_norm(g) for g in (location.excluded_genres if location else []) or []]
    if excluded:
        hits = sorted(
            {name for _, name, _ in candidate.tags if _norm(name) in excluded},
            key=str.casefold,
        )
        if hits:
            out.append(
                Constraint(
                    "excluded genres",
                    "fail",
                    f"{', '.join(hits)} {'is' if len(hits) == 1 else 'are'} on your excluded list",
                )
            )
        else:
            out.append(
                Constraint(
                    "excluded genres",
                    "pass",
                    "None of this act's Qloo genre tags is on your excluded list",
                )
            )
    if location and location.capacity:
        out.append(
            Constraint(
                "capacity",
                "not_scored",
                f"Your room holds {location.capacity}. Qloo has no stage-size or draw data for acts, so this is not scored.",
            )
        )
    if location and location.curfew:
        out.append(
            Constraint(
                "curfew",
                "not_scored",
                f"Your curfew is {location.curfew}. Qloo has no set-length data for acts, so this is not scored.",
            )
        )
    return out


# ---------------------------------------------------------------------------------------------------- scoring
def _seed_dropped(res: Any) -> bool:
    return any(e.rule == "T12-dropped-seed" for e in res.rule_events)


async def eligible_seeds(
    guard: QlooGuard, tenant_id: UUID, candidates: list[tuple[str, str]]
) -> list[tuple[str, str]]:
    """The first SEED_N seeds that pass the eligibility probe. Probes count against the lineup budget, not the fit one."""
    ctx = CallContext(trace_id=uuid4(), purpose="lineup", tenant_id=tenant_id)
    verdicts = await guard.ensure_eligible(tuple(e for e, _ in candidates[:SEED_POOL]), ctx)
    return [(e, n) for e, n in candidates[:SEED_POOL] if verdicts.get(e) is True][:SEED_N]


@dataclass
class Scored:
    """Observations for a batch of candidates, one list entry per group, and the traces behind them."""

    observations: dict[str, list[Observation]]
    seeds: dict[int, list[tuple[str, str]]]
    traces: list[str]
    problems: list[str]


async def observe(
    guard: QlooGuard, tenant_id: UUID, basis: Basis, candidate_ids: list[str]
) -> Scored:
    """One Qloo call per group scores every candidate at once: candidate affinities do not depend on what else is
    asked for (checked live: identical to single-candidate calls), so a batch costs the same as one candidate."""
    batch = candidate_ids[:BATCH]
    taken = set(batch)
    observations: dict[str, list[Observation]] = {c: [] for c in batch}
    seeds_used: dict[int, list[tuple[str, str]]] = {}
    traces: list[str] = []
    problems: list[str] = []

    async def one(group: Group) -> tuple[Group, list[tuple[str, str]], Any]:
        # An act the group already favours is measured against its other favourites: Qloo does not score a signal.
        pool_seeds = [(e, n) for e, n in basis.seed_pool.get(group.index, []) if e not in taken]
        seeds = await eligible_seeds(guard, tenant_id, pool_seeds)
        if len(seeds) < MIN_SEEDS:
            return group, seeds, None
        seed_ids = {e for e, _ in seeds}
        refs = [e for e, _, _ in basis.pool if e not in seed_ids and e not in taken][:REF_N]
        if len(refs) < WEIGHTS.min_references:
            return group, seeds, None
        trace = uuid4()
        traces.append(str(trace))
        ctx = CallContext(trace_id=trace, purpose="fit", tenant_id=tenant_id)
        req = ArtistInsights(
            signal_entities=tuple(e for e, _ in seeds),
            results_entities=tuple(batch) + tuple(refs),
            take=50,
        )
        res = await guard.insights(req, ctx)
        if not res.ok or _seed_dropped(res):
            problems.append(f"Qloo did not answer for {group.label}.")
            return group, seeds, None
        affinity = {e.entity_id: e.affinity for e in res.items if e.affinity is not None}
        return group, seeds, (affinity, set(refs))

    results = await asyncio.gather(*(one(g) for g in basis.groups))
    for group, seeds, got in results:
        seeds_used[group.index] = seeds
        for c in batch:
            if got is None:
                observations[c].append(Observation(group.index, None, ()))
                continue
            affinity, refs = got
            cand = affinity.get(c)
            ref_values = tuple(affinity[r] for r in sorted(refs) if r in affinity)
            observations[c].append(Observation(group.index, cand, ref_values))
    return Scored(observations, seeds_used, traces, problems)


def _groups_with_seeds(basis: Basis, seeds: dict[int, list[tuple[str, str]]]) -> list[Group]:
    """The groups as the Fit package sees them, with the seeds that were actually used."""
    out: list[Group] = []
    for g in basis.groups:
        used = seeds.get(g.index) or []
        out.append(
            Group(
                g.index,
                g.label,
                g.share,
                g.size,
                tuple(e for e, _ in used),
                tuple(n for _, n in used),
                g.weekday,
            )
        )
    return out


def fit_for(
    basis: Basis, candidate: Candidate, scored: Scored | None, constraints: list[Constraint]
) -> dict[str, Any]:
    """The verdict as a document. With no Qloo answers (a failed constraint stops the check before any call) the
    groups carry no observations, and the Fit package returns the failed constraint instead of a score."""
    if scored is None:
        scored = Scored({candidate.entity_id: []}, {}, [], [])
    groups = _groups_with_seeds(basis, scored.seeds)
    res = compute_fit(
        candidate.entity_id,
        groups,
        scored.observations[candidate.entity_id],
        basis.crowd,
        constraints,
        peer=None,
        weights=WEIGHTS,
        venue_weekday=basis.venue_weekday,
    )
    doc = to_dict(res)
    doc["candidate"] = {
        "entity_id": candidate.entity_id,
        "name": candidate.name,
        "genres": [n for _, n, t in candidate.tags if "genre" in t.split(":")][:5],
        "description": candidate.description,
        "year": candidate.release_year,
        "popularity": candidate.popularity,
    }
    doc["basis"] = {
        "kind": basis.kind,
        "ref": basis.ref,
        "label": basis.label,
        "groups": [
            {
                "index": g.index,
                "label": g.label,
                "share": g.share,
                "size": g.size,
                "seeds": list(g.seed_names),
            }
            for g in groups
        ],
    }
    favourite_of = [
        g.label
        for g in basis.groups
        if any(e == candidate.entity_id for e, _ in basis.seed_pool.get(g.index, []))
    ]
    if favourite_of:
        doc["notes"] = [
            *doc["notes"],
            f"{candidate.name} is already among the most-picked acts of {', '.join(favourite_of)}; "
            "for those groups it is measured against their other favourites.",
        ]
    doc["played_here"] = basis.played.get(candidate.entity_id)
    doc["problems"] = scored.problems
    doc["weights_version"] = WEIGHTS.version
    return doc


async def run(
    engine: AsyncEngine,
    guard: QlooGuard,
    tenant_id: UUID,
    business_id: UUID,
    entity_id: str,
    *,
    prefer: str | None = None,
) -> dict[str, Any]:
    """Soundcheck one act. Returns the stored verdict (with its id), computing and storing it when it is new."""
    candidate = await load_candidate(engine, entity_id)
    basis = await load_basis(engine, tenant_id, business_id, prefer)
    async with transaction(engine, tenant_id=tenant_id) as conn:
        location = await _location(conn, business_id)
    constraints = constraints_for(candidate, location, basis)
    failed = any(c.status == "fail" for c in constraints)
    scored = (
        None
        if failed or not basis.crowd.sufficient
        else await observe(guard, tenant_id, basis, [candidate.entity_id])
    )
    doc = fit_for(basis, candidate, scored, constraints)
    return await store(
        engine, tenant_id, business_id, candidate, basis, doc, scored.traces if scored else []
    )


async def store(
    engine: AsyncEngine,
    tenant_id: UUID,
    business_id: UUID,
    candidate: Candidate,
    basis: Basis,
    doc: dict[str, Any],
    traces: list[str],
) -> dict[str, Any]:
    async with transaction(engine, tenant_id=tenant_id) as conn:
        row = (
            await conn.execute(
                text(
                    "INSERT INTO soundcheck (tenant_id, business_id, candidate_entity_id, candidate_name, basis_kind,"
                    " basis_ref, input_hash, weights_version, result, trace_ids)"
                    " VALUES (:t, :b, :e, :n, :k, :r, :h, :w, CAST(:d AS jsonb), CAST(:tr AS jsonb))"
                    " ON CONFLICT (business_id, candidate_entity_id, input_hash) DO UPDATE"
                    "   SET trace_ids = soundcheck.trace_ids || EXCLUDED.trace_ids"
                    " RETURNING id, created_at"
                ),
                {
                    "t": tenant_id,
                    "b": business_id,
                    "e": candidate.entity_id,
                    "n": candidate.name,
                    "k": basis.kind,
                    "r": basis.ref,
                    "h": doc["input_hash"],
                    "w": WEIGHTS.version,
                    "d": json.dumps(doc),
                    "tr": json.dumps(traces),
                },
            )
        ).one()
    doc["id"] = str(row.id)
    doc["created_at"] = row.created_at.isoformat()
    return doc


async def get(
    engine: AsyncEngine, tenant_id: UUID, business_id: UUID, soundcheck_id: UUID
) -> dict[str, Any] | None:
    async with transaction(engine, tenant_id=tenant_id) as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT id, result, created_at FROM soundcheck WHERE id = :i AND business_id = :b"
                ),
                {"i": soundcheck_id, "b": business_id},
            )
        ).first()
    if row is None:
        return None
    doc: dict[str, Any] = dict(row.result)
    doc["id"] = str(row.id)
    doc["created_at"] = row.created_at.isoformat()
    return doc


async def recent(
    engine: AsyncEngine, tenant_id: UUID, business_id: UUID, limit: int = 12
) -> list[dict[str, Any]]:
    async with transaction(engine, tenant_id=tenant_id) as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT id, candidate_entity_id, candidate_name, basis_kind, result->>'status' AS status,"
                    " (result->>'score')::int AS score, result->'band' AS band, created_at FROM soundcheck"
                    " WHERE business_id = :b ORDER BY created_at DESC LIMIT :n"
                ),
                {"b": business_id, "n": limit},
            )
        ).all()
    return [
        {
            "id": str(r.id),
            "entity_id": r.candidate_entity_id,
            "name": r.candidate_name,
            "basis": r.basis_kind,
            "status": r.status,
            "score": r.score,
            "band": r.band,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


async def calls_for(
    engine: AsyncEngine, tenant_id: UUID, business_id: UUID, soundcheck_id: UUID
) -> list[dict[str, Any]] | None:
    """The Qloo calls behind a verdict, for the inspector: what was sent and how Qloo answered."""
    async with transaction(engine, tenant_id=tenant_id) as conn:
        sc = (
            await conn.execute(
                text("SELECT trace_ids FROM soundcheck WHERE id = :i AND business_id = :b"),
                {"i": soundcheck_id, "b": business_id},
            )
        ).first()
        if sc is None:
            return None
        traces = [UUID(t) for t in sc.trace_ids]
        if not traces:
            return []
        rows = (
            await conn.execute(
                text(
                    "SELECT id, created_at, purpose, endpoint, params, status, http_status, transport, cache,"
                    " latency_ms, coalesce(array_length(result_entity_ids, 1), 0) AS results, rule_events"
                    " FROM qloo_call WHERE trace_id = ANY(:t) ORDER BY created_at"
                ),
                {"t": traces},
            )
        ).all()
    return [
        {
            "id": str(r.id),
            "at": r.created_at.isoformat(),
            "purpose": r.purpose,
            "endpoint": r.endpoint,
            "params": r.params,
            "status": r.status,
            "http_status": r.http_status,
            "transport": r.transport,
            "cache": r.cache,
            "latency_ms": r.latency_ms,
            "results": r.results,
            "rules": [
                {"rule": e.get("rule"), "effect": e.get("effect"), "detail": e.get("detail")}
                for e in (r.rule_events or [])
                if e.get("effect") != "info"
            ],
        }
        for r in rows
    ]


# ----------------------------------------------------------------------------------------------- suggestions
NEIGHBOURS_PER_GROUP = 8
TOP = 3


def _best_group(doc: dict[str, Any]) -> dict[str, Any] | None:
    scored = [g for g in doc["groups"] if g["status"] == "scored"]
    return max(scored, key=lambda g: (g["fit"], g["share"])) if scored else None


def summary(doc: dict[str, Any]) -> dict[str, Any]:
    """What the suggestion list and the Booking Brief need from a verdict."""
    best = _best_group(doc)
    return {
        "soundcheck_id": doc.get("id"),
        "entity_id": doc["candidate"]["entity_id"],
        "name": doc["candidate"]["name"],
        "genres": doc["candidate"]["genres"],
        "popularity": doc["candidate"]["popularity"],
        "score": doc["score"],
        "band": doc["band"],
        "best_for": best["label"] if best else None,
        "watch": (doc["watch"] or [None])[0],
        "suits": doc["suits"],
        "provisional": doc["provisional"],
    }


def pool_entry(doc: dict[str, Any]) -> dict[str, Any]:
    """Everything the Sound plan needs from one scored act, and nothing from Qloo's answer itself: the act, our score and the
    rank it earned for each group (only groups it was scored for)."""
    return {
        "entity_id": doc["candidate"]["entity_id"],
        "name": doc["candidate"]["name"],
        "genres": doc["candidate"]["genres"],
        "popularity": doc["candidate"]["popularity"],
        "score": doc["score"],
        "fits": {
            str(g["index"]): g["fit"]
            for g in doc["groups"]
            if g["status"] == "scored" and g["fit"] is not None
        },
    }


def pick_wildcard(results: list[dict[str, Any]], taken: set[str]) -> dict[str, Any] | None:
    """A small act just outside the obvious: below the median popularity of what was considered, and ranked well
    (0.6 or more) for each of the crowd's two biggest scored groups. The highest score among those wins."""
    pops = sorted(
        d["candidate"]["popularity"] for d in results if d["candidate"]["popularity"] is not None
    )
    if not pops:
        return None
    median = pops[len(pops) // 2]
    best: dict[str, Any] | None = None
    for d in results:
        if d["candidate"]["entity_id"] in taken or d["status"] != "ok":
            continue
        pop = d["candidate"]["popularity"]
        if pop is None or pop > median:
            continue
        scored = sorted(
            (g for g in d["groups"] if g["status"] == "scored"), key=lambda g: -g["share"]
        )[:2]
        if len(scored) < 2 or any(g["fit"] < 0.6 for g in scored):
            continue
        if best is None or (d["score"], d["candidate"]["name"]) > (
            best["score"],
            best["candidate"]["name"],
        ):
            best = d
    return best


async def suggest(
    engine: AsyncEngine, guard: QlooGuard, tenant_id: UUID, business_id: UUID
) -> dict[str, Any]:
    """Acts worth a look for this crowd: Qloo's neighbours of each group's seeds, scored exactly like a Soundcheck."""
    basis = await load_basis(engine, tenant_id, business_id)
    async with transaction(engine, tenant_id=tenant_id) as conn:
        location = await _location(conn, business_id)

    pre: dict[str, float] = {}
    traces: list[str] = []

    async def neighbours(group: Group) -> list[Any]:
        seeds = await eligible_seeds(guard, tenant_id, basis.seed_pool.get(group.index, []))
        if len(seeds) < MIN_SEEDS:
            return []
        trace = uuid4()
        traces.append(str(trace))
        ctx = CallContext(trace_id=trace, purpose="board", tenant_id=tenant_id)
        res = await guard.insights(
            ArtistInsights(signal_entities=tuple(e for e, _ in seeds), take=20), ctx
        )
        if not res.ok or _seed_dropped(res):
            return []
        banned = set(basis.played) | {e for pool in basis.seed_pool.values() for e, _ in pool}
        found = [e for e in res.items if e.entity_id not in banned and e.affinity is not None]
        return found[:NEIGHBOURS_PER_GROUP]

    found = await asyncio.gather(*(neighbours(g) for g in basis.groups))
    for group, items in zip(basis.groups, found, strict=True):
        for e in items:
            pre[e.entity_id] = pre.get(e.entity_id, 0.0) + group.share * float(e.affinity or 0.0)
    cand_ids = [e for e, _ in sorted(pre.items(), key=lambda kv: (-kv[1], kv[0]))][:BATCH]
    if not cand_ids:
        raise SoundcheckError(
            "Qloo returned no neighbouring acts for your groups, so there is nothing to suggest yet.",
            404,
        )

    scored = await observe(guard, tenant_id, basis, cand_ids)
    results: list[dict[str, Any]] = []
    for cid in cand_ids:
        candidate = await load_candidate(engine, cid)
        results.append(
            fit_for(basis, candidate, scored, constraints_for(candidate, location, basis))
        )
    ok = sorted(
        (d for d in results if d["status"] == "ok"),
        key=lambda d: (-d["score"], d["candidate"]["name"]),
    )
    top_docs = ok[:TOP]
    wild = pick_wildcard(ok, {d["candidate"]["entity_id"] for d in top_docs})
    stored: dict[str, dict[str, Any]] = {}
    for d in [*top_docs, *([wild] if wild else [])]:
        candidate = await load_candidate(engine, d["candidate"]["entity_id"])
        stored[candidate.entity_id] = await store(
            engine, tenant_id, business_id, candidate, basis, d, [*traces, *scored.traces]
        )
    return {
        "basis": {"kind": basis.kind, "ref": basis.ref, "label": basis.label},
        "considered": len(results),
        "scored": len(ok),
        "top": [summary(stored[d["candidate"]["entity_id"]]) for d in top_docs],
        "wildcard": summary(stored[wild["candidate"]["entity_id"]]) if wild else None,
        "pool": [pool_entry(d) for d in ok],
        "generated_at": datetime.now(UTC).isoformat(),
    }


async def suggestions(
    engine: AsyncEngine, tenant_id: UUID, business_id: UUID
) -> dict[str, Any] | None:
    async with transaction(engine, tenant_id=tenant_id) as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT status, basis_kind, basis_ref, result, error, updated_at FROM act_suggestion"
                    " WHERE business_id = :b"
                ),
                {"b": business_id},
            )
        ).first()
    if row is None:
        return None
    # the wider pool of scored acts is for the Sound plan; the suggestion list shown to people does not carry it
    shown = (
        {k: v for k, v in row.result.items() if k != "pool"}
        if isinstance(row.result, dict)
        else row.result
    )
    return {
        "status": row.status,
        "basis": {"kind": row.basis_kind, "ref": row.basis_ref},
        "result": shown,
        "error": row.error,
        "updated_at": row.updated_at.isoformat(),
    }


async def suggestion_pool(
    engine: AsyncEngine, tenant_id: UUID, business_id: UUID
) -> dict[str, Any] | None:
    """The scored acts behind the last suggestion run, with what they were scored against, or None if there is none (or it
    was made before the pool was kept)."""
    async with transaction(engine, tenant_id=tenant_id) as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT status, basis_kind, basis_ref, result, updated_at FROM act_suggestion WHERE business_id = :b"
                ),
                {"b": business_id},
            )
        ).first()
    if row is None or row.status != "ready" or not isinstance(row.result, dict):
        return None
    pool = row.result.get("pool")
    if not isinstance(pool, list):
        return None
    return {
        "basis": {"kind": row.basis_kind, "ref": row.basis_ref},
        "pool": pool,
        "updated_at": row.updated_at.isoformat(),
    }


async def run_suggest_job(
    engine: AsyncEngine, guard: QlooGuard | None, tenant_id: UUID, business_id: UUID
) -> None:
    """The worker's side: mark the row running, compute, and store either the result or the reason it failed."""
    async with transaction(engine, tenant_id=tenant_id) as conn:
        await conn.execute(
            text(
                "INSERT INTO act_suggestion (business_id, tenant_id, status) VALUES (:b, :t, 'running')"
                " ON CONFLICT (business_id) DO UPDATE SET status = 'running', error = NULL, updated_at = now()"
            ),
            {"b": business_id, "t": tenant_id},
        )
    try:
        if guard is None:
            raise SoundcheckError(
                "Qloo is not configured on this server, so acts cannot be suggested.", 503
            )
        doc = await suggest(engine, guard, tenant_id, business_id)
    except SoundcheckError as exc:
        async with transaction(engine, tenant_id=tenant_id) as conn:
            await conn.execute(
                text(
                    "UPDATE act_suggestion SET status = 'failed', error = :e, result = NULL, updated_at = now()"
                    " WHERE business_id = :b"
                ),
                {"b": business_id, "e": str(exc)[:500]},
            )
        return
    async with transaction(engine, tenant_id=tenant_id) as conn:
        await conn.execute(
            text(
                "UPDATE act_suggestion SET status = 'ready', error = NULL, basis_kind = :k, basis_ref = :r,"
                " result = CAST(:d AS jsonb), updated_at = now() WHERE business_id = :b"
            ),
            {
                "b": business_id,
                "k": doc["basis"]["kind"],
                "r": doc["basis"]["ref"],
                "d": json.dumps(doc),
            },
        )
