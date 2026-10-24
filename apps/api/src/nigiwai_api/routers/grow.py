"""Grow (PRD M8): ghost customers, who serves the crowd nearby, and lookalike places further out. Anyone in the account can read the
last run; only someone who can change the account can ask for a new one, because a run spends Qloo calls."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from ..db import transaction
from ..deps import State, Tenant, Writer
from ..services import grow as service

router = APIRouter(prefix="/v1/tenants/{tenant_id}/businesses/{business_id}", tags=["grow"])


async def _business(state: Any, access: Any, business_id: UUID) -> None:
    async with transaction(
        state.engine, tenant_id=access.tenant_id, user_id=access.user_id
    ) as conn:
        found = (
            await conn.execute(text("SELECT 1 FROM business WHERE id = :b"), {"b": business_id})
        ).first()
    if found is None:
        raise HTTPException(status_code=404, detail="not found")


@router.get("/grow")
async def grow(business_id: UUID, state: State, access: Tenant) -> dict[str, Any]:
    """The last Grow run for this venue, and whether it still matches the groups. Makes no Qloo call."""
    await _business(state, access, business_id)
    return await service.get(state.engine, access.tenant_id, business_id)


@router.get("/grow/calls")
async def grow_calls(business_id: UUID, state: State, access: Tenant) -> list[dict[str, Any]]:
    """The Qloo calls behind the last run, for the inspector."""
    await _business(state, access, business_id)
    got = await service.calls(state.engine, access.tenant_id, business_id)
    if got is None:
        raise HTTPException(status_code=404, detail="There is no finished run yet.")
    return got


@router.post("/grow", status_code=202)
async def run_grow(business_id: UUID, state: State, access: Writer) -> dict[str, bool]:
    """Queue the worker to look things up again. One waiting job per venue; at most six requests in ten minutes."""
    await _business(state, access, business_id)
    if state.guard is None:
        raise HTTPException(
            status_code=503, detail="Qloo is not configured on this server, so Grow is unavailable."
        )
    if await state.limiter.check_all([(f"grow:{access.user_id}", 6, 600.0)]):
        raise HTTPException(
            status_code=429, detail="Too many requests. Wait a moment and try again."
        )
    current = await service.get(state.engine, access.tenant_id, business_id)
    if not current["can_build"]:
        raise HTTPException(status_code=422, detail=current["reason"])
    async with transaction(
        state.engine, tenant_id=access.tenant_id, user_id=access.user_id
    ) as conn:
        await conn.execute(
            text(
                "INSERT INTO grow_run (business_id, tenant_id, status) VALUES (:b, :t, 'queued')"
                " ON CONFLICT (business_id) DO UPDATE SET status = 'queued', error = NULL, updated_at = now()"
                " WHERE grow_run.status <> 'running'"
            ),
            {"b": business_id, "t": access.tenant_id},
        )
        await conn.execute(
            text(
                "INSERT INTO job (kind, tenant_id, business_id) VALUES ('grow', :t, :b)"
                " ON CONFLICT (kind, business_id) WHERE state = 'pending' DO NOTHING"
            ),
            {"t": access.tenant_id, "b": business_id},
        )
    return {"queued": True}
