"""The City Taste Atlas (PRD M16, the groundwork). Anyone in the account can read what the venue's own cell shows once the venue has
joined; only someone who can change the account can join or leave, because joining shares counts with other venues."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException

from ..deps import State, Tenant, Writer
from ..schemas import Strict
from ..services import atlas as service

router = APIRouter(prefix="/v1/tenants/{tenant_id}/businesses/{business_id}", tags=["atlas"])


class AtlasIn(Strict):
    opt_in: bool


@router.get("/atlas")
async def atlas(business_id: UUID, state: State, access: Tenant) -> dict[str, Any]:
    doc = await service.get(state.engine, access.tenant_id, business_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="not found")
    return doc


@router.put("/atlas")
async def set_atlas(
    business_id: UUID, body: AtlasIn, state: State, access: Writer
) -> dict[str, Any]:
    try:
        await service.set_opt_in(
            state.engine, access.tenant_id, access.user_id, business_id, body.opt_in
        )
    except service.AtlasError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    doc = await service.get(state.engine, access.tenant_id, business_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="not found")
    return doc
