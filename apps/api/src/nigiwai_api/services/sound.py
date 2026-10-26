"""The Sound plan (PRD M26), put together from what is already stored: the room's groups and when they scan, the acts the last
suggestion run scored for them, and the opening hours. Opening the page makes no Qloo call; the model of the plan itself is
`sound_model`.

The plan can be a few different things, and says which: ready, or why it is not (no crowd yet, no scored acts yet, acts scored
for an older crowd).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from ..db import transaction
from . import hours as hrs
from . import sound_model as sm
from . import soundcheck, tribes

NOTES = (
    "The acts are artists Qloo links to your groups, ranked for each stretch by who comes then. Qloo recommends artists, not songs: your own licensed music service supplies the tracks, and Nigiwai plays nothing.",
    "Who comes and how busy a stretch is are measured from when guests scanned. A scan is a guest who chose to answer, not a headcount. The acts are modelled.",
    "Nothing here says what music makes a person spend or stay. The weights are a starting design (v0), not calibrated against outcomes.",
)


def _state(state: str, reason: str, **extra: Any) -> dict[str, Any]:
    return {"state": state, "reason": reason, "plan": None, "notes": list(NOTES), **extra}


async def build(engine: AsyncEngine, tenant_id: UUID, business_id: UUID) -> dict[str, Any] | None:
    async with transaction(engine, tenant_id=tenant_id) as conn:
        biz = (
            await conn.execute(text("SELECT type FROM business WHERE id = :b"), {"b": business_id})
        ).first()
        loc = (
            await conn.execute(
                text(
                    "SELECT hours FROM location WHERE business_id = :b ORDER BY created_at, id LIMIT 1"
                ),
                {"b": business_id},
            )
        ).first()
        prev = await tribes.latest(conn, business_id)
    if biz is None:
        return None
    status = await soundcheck.basis_status(engine, tenant_id, business_id)
    if status["use"] is None:
        return _state(
            "no_crowd",
            "There is no crowd to plan for yet. Collect 60 guests, or start from public lineups on My people.",
        )
    pool = await soundcheck.suggestion_pool(engine, tenant_id, business_id)
    if pool is None:
        return _state(
            "needs_acts",
            "No acts have been scored for your crowd yet. Build the suggested acts, then this plan can rank them by time of week.",
            can_build=True,
        )
    try:
        basis = await soundcheck.load_basis(engine, tenant_id, business_id)
    except soundcheck.SoundcheckError as exc:
        return _state("no_crowd", str(exc))
    if pool["basis"]["kind"] != basis.kind or str(pool["basis"]["ref"]) != str(basis.ref):
        return _state(
            "stale",
            "The acts were scored for an earlier version of your crowd. Build the suggested acts again to match what your guests say now.",
            can_build=True,
        )
    acts = [
        sm.SoundAct(
            entity_id=a["entity_id"],
            name=a["name"],
            genres=tuple(a.get("genres") or ()),
            popularity=a.get("popularity"),
            fits={int(k): float(v) for k, v in (a.get("fits") or {}).items()},
        )
        for a in pool["pool"]
    ]
    base: dict[str, Any] = {
        "state": "ready",
        "reason": None,
        "basis": {
            "kind": basis.kind,
            "label": basis.label,
            "provisional": basis.crowd.provisional,
        },
        "business_type": biz.type,
        "acts_updated_at": pool["updated_at"],
        "notes": list(NOTES),
        # PRD M18: read from the same stored per-group ranks, no new Qloo call; always labelled an untested idea
        "dont_do": sm.dont_do([(g.index, g.label, g.share) for g in basis.groups], acts),
    }
    if basis.kind == "lineup":
        base["kind"] = "undated"
        base["plan"] = sm.undated_plan([(g.index, g.label, g.share) for g in basis.groups], acts)
        base["reason"] = (
            "Public lineups say who played, not when guests come, so this is one list for the whole week. Your own scans add the time of day."
        )
        return base
    result = tribes._from_json(prev.result) if prev is not None else None
    if result is None:
        return _state("no_crowd", "The stored groups could not be read. Refit them on My people.")
    rhythm = {t.index: t.rhythm for t in result.tribes if t.shown}
    groups = [
        sm.SoundGroup(
            g.index, g.label, tuple(tuple(float(x) for x in row) for row in rhythm[g.index])
        )
        for g in basis.groups
        if g.index in rhythm and len(rhythm[g.index]) == 7
    ]
    hours = loc.hours if loc is not None and isinstance(loc.hours, list) else []
    mask = hrs.open_mask(hours) if hours else None
    base["kind"] = "timed"
    base["has_hours"] = mask is not None
    base["plan"] = sm.build_plan(groups, acts, mask)
    return base
