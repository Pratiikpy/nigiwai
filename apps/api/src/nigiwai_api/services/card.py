"""The Taste Card a guest sees after sending (M15).

The simple card costs no Qloo call and answers at once: which group at this venue the guest's picks sit nearest, said as
"people who picked similar things here also pick", never as a statement about the person. The fill-in is up to three
Qloo calls (related tastes, places near the venue) and is skipped when Qloo is slow or the budget is spent; the simple
card then stays as it is. Everything listed was returned by Qloo for this request or sits in this venue's own results.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from nigiwai_tribes import Pick, Tag, TribeResult, TribesConfig, place
from qloo_guard import (
    INSIGHTS_BY_TYPE,
    AreaRef,
    CallContext,
    Entity,
    EntityType,
    GeoPoint,
    PlaceCategory,
    PlaceInsights,
    QlooGuard,
    RuleRejected,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from ..security import token_hash
from . import tribes as tribes_service

log = logging.getLogger("nigiwai.card")

# What counts as "near here" depends on what the venue is: a bar's guests are offered bars, a cafe's cafes. Anything else
# gets places of every kind, which in a city centre mostly means landmarks.
PLACE_CATEGORY: dict[str, PlaceCategory] = {
    "bar": PlaceCategory.BAR,
    "live_music_venue": PlaceCategory.BAR,
    "brewery": PlaceCategory.BAR,
    "festival": PlaceCategory.BAR,
    "promoter": PlaceCategory.BAR,
    "hotel_bar": PlaceCategory.COCKTAIL_BAR,
    "restaurant": PlaceCategory.RESTAURANT,
    "cafe": PlaceCategory.CAFE,
}

EXTRAS_TIMEOUT_S = 9.0
RELATED_TAKE = 5
NEAR_TAKE = 3


@dataclass
class CardContext:
    tenant_id: UUID
    business_id: UUID
    business_name: str
    business_type: str
    location_name: str
    lat: float | None
    lon: float | None
    radius_m: int
    entity_ids: list[str]
    entity_types: list[str]
    quality_flag: str
    reward: dict[str, Any] | None


async def load_context(engine: AsyncEngine, receipt: str) -> CardContext | None:
    async with engine.begin() as conn:
        row = (
            await conn.execute(
                text("SELECT * FROM public_card_context(:h)"), {"h": token_hash(receipt.strip())}
            )
        ).first()
    if row is None:
        return None
    return CardContext(
        tenant_id=row.tenant_id,
        business_id=row.business_id,
        business_name=row.business_name,
        business_type=row.business_type,
        location_name=row.location_name,
        lat=row.lat,
        lon=row.lon,
        radius_m=row.radius_m,
        entity_ids=list(row.entity_ids),
        entity_types=list(row.entity_types),
        quality_flag=row.quality_flag,
        reward=row.reward,
    )


async def _picks(engine: AsyncEngine, ctx: CardContext) -> list[tuple[Pick, bool | None]]:
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT entity_id, type, name_nfc, tags, insights_eligible FROM qloo_entity WHERE entity_id = ANY(:ids)"
                ),
                {"ids": ctx.entity_ids},
            )
        ).all()
    by_id = {r.entity_id: r for r in rows}
    out: list[tuple[Pick, bool | None]] = []
    for entity_id in ctx.entity_ids:
        r = by_id.get(entity_id)
        if r is None:
            continue
        tags = tuple(Tag(t[0], t[1], t[2]) for t in (r.tags or []))
        out.append((Pick(entity_id, r.type, r.name_nfc, tags), r.insights_eligible))
    return out


async def _latest_result(engine: AsyncEngine, business_id: UUID) -> TribeResult | None:
    async with engine.begin() as conn:
        doc = (
            await conn.execute(text("SELECT public_card_tribes(:b)"), {"b": business_id})
        ).scalar_one()
    return tribes_service._from_json(doc) if doc else None


def _strongest(
    picks: list[tuple[Pick, bool | None]], result: TribeResult | None, best: int | None
) -> list[Pick]:
    """The picks that sit closest to the matched group (by shared top tags), else the guest's own order."""
    if result is not None and best is not None and 0 <= best < len(result.tribes):
        wanted = {t["tag_id"] for t in result.tribes[best].top_tags}
        ranked = sorted(
            range(len(picks)),
            key=lambda i: (-len({t.tag_id for t in picks[i][0].tags} & wanted), i),
        )
        return [picks[i][0] for i in ranked]
    return [p for p, _ in picks]


def _tenths(share: float) -> str:
    n = max(1, min(9, round(share * 10)))
    return f"About {n} in 10 guests here pick like this."


async def simple_card(engine: AsyncEngine, ctx: CardContext) -> dict[str, Any]:
    picks = await _picks(engine, ctx)
    result = await _latest_result(engine, ctx.business_id)
    group: dict[str, Any]
    best: int | None = None
    placement = place(result, [p for p, _ in picks]) if result is not None else None
    if result is not None and placement is not None and result.tribes[placement.best].shown:
        tribe = result.tribes[placement.best]
        best = placement.best
        group = {
            "status": "matched",
            "label": tribe.label,
            "provisional": result.state != "named",
            "line": tribe.line,
            "share_text": _tenths(tribe.share),
            "share": tribe.share,
            "n": result.n,
        }
    else:
        n = result.n if result is not None else 0
        needed = TribesConfig().min_respondents
        group = {
            "status": "forming",
            "label": None,
            "provisional": True,
            "line": "",
            "share_text": "",
            "share": None,
            "n": n,
            "needed": needed,
        }
    strongest = _strongest(picks, result, best)[:3]
    return {
        "venue": ctx.business_name,
        "group": group,
        "picks": [{"entity_id": p.entity_id, "name": p.name, "type": p.type} for p in strongest],
        "reward": ctx.reward,
        "can_fill_in": bool(ctx.entity_ids),
    }


def _seed_dropped(res: Any) -> bool:
    """Qloo silently drops a seed it does not know and answers anyway, with popular results. Those must not be shown as
    taste-matched, so a dropped seed makes the whole section unavailable."""
    return any(e.rule == "T12-dropped-seed" for e in res.rule_events)


def _entity_out(e: Entity) -> dict[str, Any]:
    return {
        "entity_id": e.entity_id,
        "name": e.name,
        "type": e.primary_type,
        "year": e.release_year,
        "description": (e.description or "")[:120] or None,
    }


async def fill_in(engine: AsyncEngine, guard: QlooGuard | None, ctx: CardContext) -> dict[str, Any]:
    """Related tastes and places near the venue, at most three Qloo calls in total, all or nothing within a time limit."""
    out: dict[str, Any] = {"status": "ok", "related": [], "near": []}
    if guard is None:
        return {"status": "unavailable", "related": [], "near": []}
    picks = await _picks(engine, ctx)
    result = await _latest_result(engine, ctx.business_id)
    placement = place(result, [p for p, _ in picks]) if result is not None else None
    ordered = _strongest(picks, result, placement.best if placement else None)
    eligible = {p.entity_id for p, ok in picks if ok is True}
    strong = [p for p in ordered if p.entity_id in eligible]
    if not strong:
        return {"status": "unavailable", "related": [], "near": []}
    qctx: CallContext = guard.new_context("card", tenant_id=ctx.tenant_id)
    picked_ids = tuple(ctx.entity_ids)

    async def related(pick: Pick) -> dict[str, Any] | None:
        try:
            cls = INSIGHTS_BY_TYPE[EntityType(pick.type)]
            if cls is PlaceInsights:
                return None
            others = tuple(
                i for i in picked_ids if i != pick.entity_id
            )  # never suggest what they already picked
            req = cls(signal_entities=(pick.entity_id,), exclude_entities=others, take=RELATED_TAKE)
            res = await guard.insights(req, qctx)  # type: ignore[arg-type]
        except (RuleRejected, KeyError, ValueError):
            return None
        if not res.ok or not res.items or _seed_dropped(res):
            return None
        return {"because": pick.name, "items": [_entity_out(e) for e in res.items[:4]]}

    async def near(pick: Pick) -> list[dict[str, Any]]:
        if ctx.lat is None or ctx.lon is None:
            return []
        try:
            req = PlaceInsights(
                signal_entities=(pick.entity_id,),
                area=AreaRef(center=GeoPoint(lat=ctx.lat, lon=ctx.lon), radius_m=ctx.radius_m),
                category=PLACE_CATEGORY.get(ctx.business_type),
                take=NEAR_TAKE,
                sort_by_distance=False,
            )
            res = await guard.insights(req, qctx)
        except (RuleRejected, ValueError):
            return []
        if not res.ok or _seed_dropped(res):
            return []  # Qloo ignored the pick, so these would not be "because of" anything: say nothing
        return [
            {
                **_entity_out(e),
                "distance_m": round(e.distance_m) if e.distance_m is not None else None,
                "address": e.address,
            }
            for e in res.items[:NEAR_TAKE]
        ]

    tasks = [related(strong[0]), near(strong[0])]
    if len(strong) > 1 and strong[1].type != strong[0].type:
        tasks.append(related(strong[1]))
    try:
        gathered = await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True), EXTRAS_TIMEOUT_S
        )
    except TimeoutError:
        return {"status": "slow", "related": [], "near": []}
    first_related, places, *rest = gathered
    for item in (first_related, *rest):
        if isinstance(item, dict):
            out["related"].append(item)
    if isinstance(places, list):
        out["near"] = places
    for g in gathered:
        if isinstance(g, Exception):
            log.warning("card fill-in part failed: %r", g)
    if not out["related"] and not out["near"]:
        out["status"] = "unavailable"
    out["calls"] = qctx.budget.used if qctx.budget is not None else None
    return out
