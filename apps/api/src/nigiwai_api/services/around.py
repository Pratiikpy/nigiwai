"""Places around a venue, for the map's "Around you" layer (PRD M6) and the Booking Brief.

Qloo is asked for places of the venue's kind inside the venue's own radius (an exact area, so everything returned is
inside it), then each place is looked up once more for Qloo's closure flag, because place data can be stale: a place
marked closed is left off. The answer is labelled observed: it is what Qloo says is there, not something we measured.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from qloo_guard import (
    AreaRef,
    CallContext,
    EntitiesRequest,
    GeoPoint,
    PlaceInsights,
    QlooGuard,
)

from .card import PLACE_CATEGORY

log = logging.getLogger("nigiwai.around")

TAKE = 15


@dataclass
class Around:
    places: list[dict[str, Any]]
    dropped_closed: int
    trace_ids: list[str]
    status: str  # "ok" | "empty" | "unavailable"


async def places_around(
    guard: QlooGuard | None,
    tenant_id: UUID,
    business_type: str,
    lat: float,
    lon: float,
    radius_m: int,
) -> Around:
    if guard is None:
        return Around([], 0, [], "unavailable")
    trace = uuid4()
    ctx = CallContext(trace_id=trace, purpose="board", tenant_id=tenant_id)
    try:
        res = await guard.insights(
            PlaceInsights(
                area=AreaRef(center=GeoPoint(lat=lat, lon=lon), radius_m=radius_m),
                category=PLACE_CATEGORY.get(business_type),
                take=TAKE,
                sort_by_distance=True,
            ),
            ctx,
        )
    except ValueError:
        return Around([], 0, [str(trace)], "unavailable")
    if not res.ok:
        return Around([], 0, [str(trace)], "unavailable")
    found = [e for e in res.items if e.location is not None]
    if not found:
        return Around([], 0, [str(trace)], "empty")
    closed: set[str] = set()
    checked = await guard.entities(
        EntitiesRequest(entity_ids=tuple(e.entity_id for e in found)), ctx
    )
    if checked.ok:
        closed = {e.entity_id for e in checked.items if e.is_closed is True}
    places = [
        {
            "entity_id": e.entity_id,
            "name": e.name,
            "lat": e.location.lat,
            "lon": e.location.lon,
            "distance_m": round(e.distance_m) if e.distance_m is not None else None,
            "address": e.address,
        }
        for e in found
        if e.entity_id not in closed and e.location is not None
    ]
    return Around(places, len(closed), [str(trace)], "ok" if places else "empty")
