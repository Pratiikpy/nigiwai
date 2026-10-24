"""The crowd map (PRD M6): where a venue's guests scan, who they are, where they say they come from, and what is around.

Everything on the map is computed here, server-side, and the privacy rule is enforced here too: a place or a district
with fewer than ten guests behind it is reported only as "under 10", with no figures, so nothing in the browser can show
what the server did not send. Layers carry their honesty label: scans are measured, groups are modelled, places around
are observed (what Qloo says is there).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

import h3
import httpx
from nigiwai_tribes import place
from qloo_guard import QlooGuard
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from ..db import transaction
from . import around as around_service
from . import tribes
from .geocode import Geocoder, normalise_district

MIN_GROUP = 10  # nothing is shown about fewer guests than this
HEX_RESOLUTION = 8  # cells about 460 m along an edge: neighbourhood scale
GEOCODE_PER_REQUEST = 3
PERIODS = {"7d": 7, "4w": 28, "all": None}


def _since(period: str, today: date) -> date | None:
    days = PERIODS.get(period)
    return today - timedelta(days=days) if days else None


async def _responses(conn: Any, business_id: UUID) -> list[Any]:
    """Every clean response with its picks, where it was scanned, when, and the district if the guest gave one."""
    return list(
        (
            await conn.execute(
                text(
                    "SELECT r.id::text AS rid, r.local_weekday AS wd, r.local_hour AS hr, r.local_date AS day,"
                    "       r.district AS district, q.location_id::text AS loc, q.label AS qr_label,"
                    "       p.position, p.entity_id, p.entity_type, e.name_nfc AS name, e.tags AS tags"
                    " FROM response r"
                    " JOIN survey s ON s.id = r.survey_id AND s.version = r.survey_version"
                    " JOIN qr_point q ON q.id = r.qr_point_id"
                    " JOIN pick p ON p.response_id = r.id"
                    " LEFT JOIN qloo_entity e ON e.entity_id = p.entity_id"
                    " WHERE s.business_id = :b AND r.quality_flag = 'ok'"
                    " ORDER BY r.id, p.position"
                ),
                {"b": business_id},
            )
        ).all()
    )


def _hex(lat: float, lon: float) -> tuple[str, list[list[float]]]:
    cell = h3.latlng_to_cell(lat, lon, HEX_RESOLUTION)
    return cell, [[round(la, 6), round(lo, 6)] for la, lo in h3.cell_to_boundary(cell)]


def _mix(counts: list[float], labels: list[str], n: int) -> list[dict[str, Any]]:
    """Each group's share of `n`, with any group of fewer than ten guests folded into 'Other', never shown on its own."""
    out: list[dict[str, Any]] = []
    other = 0.0
    for k, c in enumerate(counts):
        if c >= MIN_GROUP:
            out.append({"group": k, "label": labels[k], "share": round(c / n, 3)})
        else:
            other += c
    if other > 0:
        out.append({"group": None, "label": "Other", "share": round(other / n, 3)})
    return out


async def build(
    engine: AsyncEngine,
    guard: QlooGuard | None,
    geocoder: Geocoder | None,
    tenant_id: UUID,
    business_id: UUID,
    period: str = "all",
) -> dict[str, Any] | None:
    if period not in PERIODS:
        period = "all"
    async with transaction(engine, tenant_id=tenant_id) as conn:
        business = (
            await conn.execute(
                text("SELECT name, type FROM business WHERE id = :b"), {"b": business_id}
            )
        ).first()
        if business is None:
            return None
        locations = (
            await conn.execute(
                text(
                    "SELECT id::text AS id, name, address, radius_m, timezone, ST_Y(geom::geometry) AS lat,"
                    " ST_X(geom::geometry) AS lon FROM location WHERE business_id = :b ORDER BY created_at, id"
                ),
                {"b": business_id},
            )
        ).all()
        prev = await tribes.latest(conn, business_id)
        rows = await _responses(conn, business_id)

    result = tribes._from_json(prev.result) if prev is not None else None
    grouped = result is not None and result.state in ("provisional", "named")
    shown = [t for t in (result.tribes if result else []) if t.shown] if grouped else []
    group_labels = [t.label for t in (result.tribes if result else [])]

    today = datetime.now(UTC).date()
    since = _since(period, today)

    # One entry per response: its location, date, district, and where it sits among the groups.
    meta: dict[str, dict[str, Any]] = {}
    for r in rows:
        meta.setdefault(
            r.rid, {"loc": r.loc, "day": r.day, "district": r.district, "qr": r.qr_label}
        )
    respondents = tribes._respondents(rows)
    members: dict[str, list[float] | None] = {}
    for resp in respondents:
        p = place(result, list(resp.picks)) if grouped and result is not None else None
        members[resp.id] = p.memberships if p else None

    def in_period(rid: str) -> bool:
        d = meta[rid]["day"]
        return since is None or (d is not None and d >= since)

    k = len(group_labels)
    per_loc: dict[str, dict[str, Any]] = {
        loc.id: {"n": 0, "soft": [0.0] * k, "qr": defaultdict(int)} for loc in locations
    }
    per_district: dict[str, dict[str, Any]] = {}
    weeks: dict[date, int] = defaultdict(int)
    placed_in = 0
    for rid, m in meta.items():
        if not in_period(rid):
            continue
        entry = per_loc.get(m["loc"])
        mem = members.get(rid)
        if entry is not None:
            entry["n"] += 1
            entry["qr"][m["qr"]] += 1
            if mem:
                for g in range(k):
                    entry["soft"][g] += mem[g]
        if m["district"]:
            key = normalise_district(m["district"])
            if key:
                d = per_district.setdefault(
                    key, {"n": 0, "soft": [0.0] * k, "names": defaultdict(int)}
                )
                d["n"] += 1
                d["names"][m["district"].strip()] += 1
                if mem:
                    for g in range(k):
                        d["soft"][g] += mem[g]
        if m["day"] is not None:
            bucket = m["day"] if period == "7d" else m["day"] - timedelta(days=m["day"].weekday())
            weeks[bucket] += 1
        placed_in += 1

    # Locations: a pin each. A place with fewer than ten guests is a pin and nothing more.
    out_locations: list[dict[str, Any]] = []
    for loc in locations:
        e = per_loc[loc.id]
        has_point = loc.lat is not None and loc.lon is not None
        if not has_point:
            continue
        visible = e["n"] >= MIN_GROUP
        out_locations.append(
            {
                "id": loc.id,
                "name": loc.name,
                "address": loc.address,
                "lat": loc.lat,
                "lon": loc.lon,
                "radius_m": loc.radius_m,
                "scans": e["n"] if visible else None,
                "hidden": not visible,
                "mix": _mix(e["soft"], group_labels, e["n"]) if visible and grouped else [],
                "qr_points": (
                    [{"label": q, "scans": c} for q, c in sorted(e["qr"].items()) if c >= MIN_GROUP]
                    if visible
                    else []
                ),
            }
        )

    # Catchment: a hex per district at least ten guests named; smaller districts are only counted.
    catchment: list[dict[str, Any]] = []
    hidden_districts = 0
    hidden_guests = 0
    asked = 0  # districts looked up on this request
    pending = 0  # districts that could not be placed yet: asked too many at once, or the service was unreachable
    anchor = next(((lo["lat"], lo["lon"]) for lo in out_locations), None)
    cells: dict[str, dict[str, Any]] = {}
    for _key, d in sorted(per_district.items(), key=lambda kv: -kv[1]["n"]):
        if d["n"] < MIN_GROUP:
            hidden_districts += 1
            hidden_guests += d["n"]
            continue
        if anchor is None or geocoder is None:
            continue
        name = max(d["names"], key=lambda n: d["names"][n])
        found = await geocoder.cached(name, anchor)
        if found is None and asked < GEOCODE_PER_REQUEST:
            asked += 1
            try:
                found = await geocoder.locate(name, anchor) or {"found": False}
            except httpx.HTTPError:
                found = None
        if found is None:
            pending += 1
            continue
        if not found.get("found"):
            continue  # Nominatim knows no such place near the venue: it is counted above, never guessed at
        cell, boundary = _hex(found["lat"], found["lon"])
        c = cells.setdefault(
            cell, {"cell": cell, "boundary": boundary, "n": 0, "soft": [0.0] * k, "names": []}
        )
        c["n"] += d["n"]
        c["names"].append(name)
        for g in range(k):
            c["soft"][g] += d["soft"][g]
    for c in cells.values():
        main = (
            max(range(k), key=lambda g: c["soft"][g])
            if grouped and k and sum(c["soft"]) > 0
            else None
        )
        catchment.append(
            {
                "cell": c["cell"],
                "boundary": c["boundary"],
                "guests": c["n"],
                "districts": sorted(c["names"]),
                "main_group": main,
                "main_label": group_labels[main] if main is not None else None,
                "mix": _mix(c["soft"], group_labels, c["n"]) if grouped else [],
            }
        )

    return {
        "business": business.name,
        "period": period,
        "computed_at": datetime.now(UTC).isoformat(),
        "locations": out_locations,
        "groups": [
            {
                "index": g,
                "label": group_labels[g],
                "share": round(result.tribes[g].share, 3) if result else None,
            }
            for g in range(k)
        ]
        if grouped and result
        else [],
        "grouping": {
            "state": result.state if result else "none",
            "n": result.n if result else 0,
            "shown": len(shown),
        },
        "catchment": catchment,
        "catchment_hidden": {"districts": hidden_districts, "guests": hidden_guests},
        "catchment_pending": pending,
        "timeline": {
            "unit": "day" if period == "7d" else "week",
            "buckets": [{"start": d.isoformat(), "scans": n} for d, n in sorted(weeks.items())][
                -26:
            ],
            "total": placed_in,
        },
        "min_group": MIN_GROUP,
    }


async def _calls(
    engine: AsyncEngine, tenant_id: UUID, trace_ids: list[str]
) -> list[dict[str, Any]]:
    async with transaction(engine, tenant_id=tenant_id) as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT id::text AS id, created_at, purpose, endpoint, params, status, transport, cache,"
                    " latency_ms, coalesce(array_length(result_entity_ids, 1), 0) AS results"
                    " FROM qloo_call WHERE trace_id = ANY(:t) ORDER BY created_at"
                ),
                {"t": [UUID(t) for t in trace_ids]},
            )
        ).all()
    return [
        {
            "id": r.id,
            "at": r.created_at.isoformat(),
            "purpose": r.purpose,
            "endpoint": r.endpoint,
            "params": r.params,
            "status": r.status,
            "transport": r.transport,
            "cache": r.cache,
            "latency_ms": r.latency_ms,
            "results": r.results,
        }
        for r in rows
    ]


async def around_for(
    engine: AsyncEngine, guard: QlooGuard | None, tenant_id: UUID, business_id: UUID
) -> dict[str, Any] | None:
    """What Qloo says is around the venue (its first located site), with the calls that drew it. Kept apart from the
    rest of the map because it is the one part that waits on Qloo: the map is on screen without it."""
    async with transaction(engine, tenant_id=tenant_id) as conn:
        business = (
            await conn.execute(text("SELECT type FROM business WHERE id = :b"), {"b": business_id})
        ).first()
        if business is None:
            return None
        home = (
            await conn.execute(
                text(
                    "SELECT radius_m, ST_Y(geom::geometry) AS lat, ST_X(geom::geometry) AS lon FROM location"
                    " WHERE business_id = :b AND geom IS NOT NULL ORDER BY created_at, id LIMIT 1"
                ),
                {"b": business_id},
            )
        ).first()
    if home is None:
        return {"status": "empty", "places": [], "dropped_closed": 0, "calls": []}
    got = await around_service.places_around(
        guard, tenant_id, business.type, home.lat, home.lon, home.radius_m
    )
    calls = await _calls(engine, tenant_id, got.trace_ids) if got.trace_ids else []
    return {
        "status": got.status,
        "places": got.places,
        "dropped_closed": got.dropped_closed,
        "calls": calls,
    }
