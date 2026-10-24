"""The crowd map endpoint (PRD M6). Tenant-scoped like every owner route; everything it returns has already been through
the server's privacy rule (nothing about fewer than ten guests)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text

from ..db import transaction
from ..deps import State, Tenant
from ..services import mapdata

router = APIRouter(prefix="/v1/tenants/{tenant_id}/businesses/{business_id}", tags=["map"])


@router.get("/map")
async def crowd_map(
    business_id: UUID,
    state: State,
    access: Tenant,
    period: str = Query(default="all", pattern="^(7d|4w|all)$"),
) -> dict[str, Any]:
    async with transaction(
        state.engine, tenant_id=access.tenant_id, user_id=access.user_id
    ) as conn:
        found = (
            await conn.execute(text("SELECT 1 FROM business WHERE id = :b"), {"b": business_id})
        ).first()
    if found is None:
        raise HTTPException(status_code=404, detail="not found")
    if await state.limiter.check_all([(f"map:{access.user_id}", 60, 600.0)]):
        raise HTTPException(
            status_code=429, detail="Too many requests. Wait a moment and try again."
        )
    doc = await mapdata.build(
        state.engine, state.guard, state.geocoder, access.tenant_id, business_id, period
    )
    if doc is None:
        raise HTTPException(status_code=404, detail="not found")
    return doc


@router.get("/map/around")
async def around(business_id: UUID, state: State, access: Tenant) -> dict[str, Any]:
    """The "Around you" layer: places Qloo says are near the venue. Separate so the map never waits for Qloo."""
    async with transaction(
        state.engine, tenant_id=access.tenant_id, user_id=access.user_id
    ) as conn:
        found = (
            await conn.execute(text("SELECT 1 FROM business WHERE id = :b"), {"b": business_id})
        ).first()
    if found is None:
        raise HTTPException(status_code=404, detail="not found")
    if await state.limiter.check_all([(f"map-around:{access.user_id}", 30, 600.0)]):
        raise HTTPException(
            status_code=429, detail="Too many requests. Wait a moment and try again."
        )
    doc = await mapdata.around_for(state.engine, state.guard, access.tenant_id, business_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="not found")
    return doc
