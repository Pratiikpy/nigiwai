"""The City Taste Atlas (PRD M16, the groundwork): what guests pick in a neighbourhood, pooled across venues that chose to take part.

The pooling is done inside the database by `atlas_rebuild()` (migration 0016), which is the only thing that reads across tenants and
the only thing that writes `atlas_cell`; the minimums are enforced there and restated as column checks. This module only switches a
venue in or out, asks for a rebuild, and reads the finished cell for a venue that has itself joined. Sharing is reciprocal: a venue
that has not joined sees nothing and contributes nothing.

What a reader is never told: how many venues have joined in their cell (below the minimum there is simply no row), which venue
supplied what, or any count under the group minimum. Counts are what guests chose to answer at participating venues, a
self-selected sample of the neighbourhood, and the page says so.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ..db import transaction

log = logging.getLogger("nigiwai.atlas")

# These restate what the SQL function enforces, for the page's wording and the tests. The database is the authority.
MIN_VENUES_IN_CELL = 5
MIN_RESPONSES_PER_VENUE = 10
MIN_RESPONSES_PER_ITEM = 10
MIN_VENUES_PER_ITEM = 3
MAX_SHARE_OF_ONE_VENUE = 0.5
PER_TYPE = 12
TYPE_ORDER = (
    "urn:entity:artist",
    "urn:entity:movie",
    "urn:entity:tv_show",
    "urn:entity:book",
    "urn:entity:brand",
    "urn:entity:place",
    "urn:entity:podcast",
    "urn:entity:videogame",
)
TYPE_LABEL = {
    "urn:entity:artist": "Artists",
    "urn:entity:movie": "Films",
    "urn:entity:tv_show": "TV shows",
    "urn:entity:book": "Books",
    "urn:entity:brand": "Brands",
    "urn:entity:place": "Places",
    "urn:entity:podcast": "Podcasts",
    "urn:entity:videogame": "Games",
}


class AtlasError(Exception):
    def __init__(self, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.status = status


def cell_of(lat: float, lon: float) -> tuple[int, int]:
    """The 0.01 degree square a point is in, the same way the SQL names it (floor of longitude and latitude times 100)."""
    import math

    return math.floor(lon * 100), math.floor(lat * 100)


async def _venue(conn: AsyncConnection, business_id: UUID) -> Any:
    return (
        await conn.execute(
            text("SELECT id, atlas_opt_in, atlas_opt_in_at FROM business WHERE id = :b"),
            {"b": business_id},
        )
    ).first()


async def _home(conn: AsyncConnection, business_id: UUID) -> Any:
    return (
        await conn.execute(
            text(
                "SELECT ST_Y(geom::geometry) AS lat, ST_X(geom::geometry) AS lon FROM location"
                " WHERE business_id = :b AND geom IS NOT NULL ORDER BY created_at, id LIMIT 1"
            ),
            {"b": business_id},
        )
    ).first()


def _fewer(n: int) -> int | None:
    """A count of the venue's own guests, or None when it is under the minimum a count may be shown at."""
    return n if n >= MIN_RESPONSES_PER_ITEM else None


async def get(engine: AsyncEngine, tenant_id: UUID, business_id: UUID) -> dict[str, Any] | None:
    """What the Atlas page shows for a venue. Makes no Qloo call."""
    async with transaction(engine, tenant_id=tenant_id) as conn:
        venue = await _venue(conn, business_id)
        if venue is None:
            return None
        home = await _home(conn, business_id)
        out: dict[str, Any] = {
            "opted_in": bool(venue.atlas_opt_in),
            "opted_in_at": venue.atlas_opt_in_at.isoformat() if venue.atlas_opt_in_at else None,
            "has_location": home is not None,
            "limits": {
                "venues_in_cell": MIN_VENUES_IN_CELL,
                "responses_per_venue": MIN_RESPONSES_PER_VENUE,
                "responses_per_item": MIN_RESPONSES_PER_ITEM,
                "venues_per_item": MIN_VENUES_PER_ITEM,
                "max_share_of_one_venue": MAX_SHARE_OF_ONE_VENUE,
            },
            "groups": [],
            "cell_responses": None,
            "built_at": None,
        }
        if home is None:
            out["state"] = "no_location"
            out["reason"] = (
                "Add your address on Your venue first: the Atlas groups venues by neighbourhood."
            )
            return out
        if not venue.atlas_opt_in:
            out["state"] = "not_joined"
            out["reason"] = (
                "You have not joined. Nothing of yours is shared, and nothing of the Atlas is shown to you."
            )
            return out
        cx, cy = cell_of(float(home.lat), float(home.lon))
        rows = (
            await conn.execute(
                text(
                    "SELECT a.entity_id, a.entity_type, coalesce(e.name_nfc, '') AS name, a.responses, a.venues,"
                    "       a.cell_responses, a.built_at"
                    " FROM atlas_cell a LEFT JOIN qloo_entity e ON e.entity_id = a.entity_id"
                    " WHERE a.cell_x = :x AND a.cell_y = :y"
                    " ORDER BY a.entity_type, a.responses DESC, a.entity_id"
                ),
                {"x": cx, "y": cy},
            )
        ).all()
        if not rows:
            out["state"] = "waiting"
            out["reason"] = (
                f"Not enough venues around you have joined yet. The Atlas opens for a neighbourhood once at least {MIN_VENUES_IN_CELL} "
                f"venues there have each collected {MIN_RESPONSES_PER_VENUE} guests' answers. It is rebuilt every six hours."
            )
            return out
        named = [r for r in rows if r.name]
        own = {
            r.entity_id: int(r.n)
            for r in (
                await conn.execute(
                    text(
                        "SELECT p.entity_id, count(DISTINCT r.id) AS n"
                        " FROM response r JOIN survey s ON s.id = r.survey_id AND s.version = r.survey_version"
                        " JOIN pick p ON p.response_id = r.id"
                        " WHERE s.business_id = :b AND r.quality_flag = 'ok' AND p.entity_id = ANY(:ids)"
                        " GROUP BY p.entity_id"
                    ),
                    {"b": business_id, "ids": [r.entity_id for r in named]},
                )
            ).all()
        }
    by_type: dict[str, list[dict[str, Any]]] = {}
    for r in named:
        bucket = by_type.setdefault(r.entity_type, [])
        if len(bucket) >= PER_TYPE:
            continue
        bucket.append(
            {
                "entity_id": r.entity_id,
                "name": r.name,
                "responses": int(r.responses),
                "share": round(int(r.responses) / int(r.cell_responses), 3),
                "venues": int(r.venues),
                "own": _fewer(own.get(r.entity_id, 0)),
            }
        )
    ordered = [t for t in TYPE_ORDER if t in by_type] + sorted(
        t for t in by_type if t not in TYPE_ORDER
    )
    out["state"] = "ready"
    out["reason"] = ""
    out["cell_responses"] = int(rows[0].cell_responses)
    out["built_at"] = max(r.built_at for r in rows).isoformat()
    out["groups"] = [
        {
            "type": t,
            "label": TYPE_LABEL.get(t, t.rsplit(":", 1)[-1].replace("_", " ").title()),
            "items": by_type[t],
        }
        for t in ordered
    ]
    return out


async def set_opt_in(
    engine: AsyncEngine, tenant_id: UUID, user_id: UUID, business_id: UUID, opt_in: bool
) -> bool:
    """Join or leave. Returns whether anything changed. Either way the owner's own action is written to the audit log, and a
    rebuild is queued at once so that leaving takes the venue's counts out of the Atlas promptly."""
    async with transaction(engine, tenant_id=tenant_id, user_id=user_id) as conn:
        venue = await _venue(conn, business_id)
        if venue is None:
            raise AtlasError("not found", 404)
        if opt_in and await _home(conn, business_id) is None:
            raise AtlasError(
                "Add your address on Your venue first: the Atlas groups venues by neighbourhood."
            )
        if bool(venue.atlas_opt_in) == opt_in:
            return False
        await conn.execute(
            text(
                "UPDATE business SET atlas_opt_in = :v, atlas_opt_in_at = CASE WHEN :v THEN now() ELSE NULL END"
                " WHERE id = :b"
            ),
            {"v": opt_in, "b": business_id},
        )
        await conn.execute(
            text(
                "INSERT INTO audit_log (tenant_id, actor, action, target) VALUES (:t, :a, :x, :g)"
            ),
            {
                "t": tenant_id,
                "a": str(user_id),
                "x": "atlas.join" if opt_in else "atlas.leave",
                "g": str(business_id),
            },
        )
        await conn.execute(
            text(
                "INSERT INTO job (kind, tenant_id, business_id) VALUES ('atlas_rebuild', :t, :b)"
                " ON CONFLICT (kind, business_id) WHERE state = 'pending' DO NOTHING"
            ),
            {"t": tenant_id, "b": business_id},
        )
    return True


async def rebuild(engine: AsyncEngine) -> int:
    """Rebuild the whole Atlas. The minimums are enforced by the function in the database, not here."""
    async with engine.begin() as conn:
        built = (await conn.execute(text("SELECT atlas_rebuild()"))).scalar_one()
    log.info("atlas rebuilt: %s rows", built)
    return int(built)
