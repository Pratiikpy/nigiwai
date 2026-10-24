"""Soundcheck endpoints (PRD M19, M9): check one act against the crowd, list suggested acts, and see the Qloo calls
behind any verdict. Tenant-scoped like every owner route."""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import StringConstraints
from sqlalchemy import text

from ..db import transaction
from ..deps import State, Tenant
from ..schemas import Strict
from ..services import compare as compare_service
from ..services import soundcheck as service

router = APIRouter(prefix="/v1/tenants/{tenant_id}/businesses/{business_id}", tags=["soundcheck"])

EntityId = Annotated[str, StringConstraints(min_length=36, max_length=36)]


class SoundcheckIn(Strict):
    entity_id: EntityId
    basis: Literal["guests", "lineup"] | None = None


async def _business(state: Any, access: Any, business_id: UUID) -> None:
    async with transaction(
        state.engine, tenant_id=access.tenant_id, user_id=access.user_id
    ) as conn:
        found = (
            await conn.execute(text("SELECT 1 FROM business WHERE id = :b"), {"b": business_id})
        ).first()
    if found is None:
        raise HTTPException(status_code=404, detail="not found")


def _guard(state: Any) -> Any:
    if state.guard is None:
        raise HTTPException(
            status_code=503,
            detail="Qloo is not configured on this server, so Soundcheck is unavailable.",
        )
    return state.guard


async def _limited(state: Any, access: Any, name: str, count: int, window: float) -> None:
    if await state.limiter.check_all([(f"{name}:{access.user_id}", count, window)]):
        raise HTTPException(
            status_code=429, detail="Too many requests. Wait a moment and try again."
        )


@router.get("/soundcheck/basis")
async def basis(business_id: UUID, state: State, access: Tenant) -> dict[str, Any]:
    """What Soundcheck would check against for this venue: guests, public lineups or nothing yet."""
    await _business(state, access, business_id)
    return await service.basis_status(state.engine, access.tenant_id, business_id)


@router.get("/soundcheck/search")
async def search(
    business_id: UUID, state: State, access: Tenant, q: str = Query(min_length=2, max_length=80)
) -> dict[str, Any]:
    """Find an artist: the local index first, then Qloo (shared with the survey picker, so the same Guard rules apply)."""
    await _business(state, access, business_id)
    await _limited(state, access, "sc-search", 40, 60.0)
    out = await state.picker.search(q, ["artist"], tenant_id=access.tenant_id, allow_live=True)
    found: dict[str, Any] = out.model_dump()
    return found


@router.post("/soundcheck")
async def run(
    business_id: UUID, body: SoundcheckIn, state: State, access: Tenant
) -> dict[str, Any]:
    """Soundcheck one act. The score is computed in code from Qloo's answers for each group; see /calls for them."""
    await _business(state, access, business_id)
    await _limited(state, access, "sc-run", 30, 600.0)
    try:
        return await service.run(
            state.engine,
            _guard(state),
            access.tenant_id,
            business_id,
            body.entity_id,
            prefer=body.basis,
        )
    except service.SoundcheckError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc


@router.get("/soundchecks")
async def recent(business_id: UUID, state: State, access: Tenant) -> list[dict[str, Any]]:
    await _business(state, access, business_id)
    return await service.recent(state.engine, access.tenant_id, business_id)


@router.get("/soundchecks/{soundcheck_id}")
async def one(
    business_id: UUID, soundcheck_id: UUID, state: State, access: Tenant
) -> dict[str, Any]:
    await _business(state, access, business_id)
    doc = await service.get(state.engine, access.tenant_id, business_id, soundcheck_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="not found")
    return doc


@router.get("/soundchecks/{soundcheck_id}/calls")
async def calls(
    business_id: UUID, soundcheck_id: UUID, state: State, access: Tenant
) -> list[dict[str, Any]]:
    await _business(state, access, business_id)
    found = await service.calls_for(state.engine, access.tenant_id, business_id, soundcheck_id)
    if found is None:
        raise HTTPException(status_code=404, detail="not found")
    return found


@router.get("/suggestions")
async def suggestions(business_id: UUID, state: State, access: Tenant) -> dict[str, Any] | None:
    await _business(state, access, business_id)
    return await service.suggestions(state.engine, access.tenant_id, business_id)


@router.post("/suggestions", status_code=202)
async def refresh_suggestions(business_id: UUID, state: State, access: Tenant) -> dict[str, bool]:
    """Queue the worker to build the suggested acts again. One waiting job per venue."""
    await _business(state, access, business_id)
    await _limited(state, access, "sc-suggest", 6, 600.0)
    async with transaction(
        state.engine, tenant_id=access.tenant_id, user_id=access.user_id
    ) as conn:
        await conn.execute(
            text(
                "INSERT INTO act_suggestion (business_id, tenant_id, status) VALUES (:b, :t, 'queued')"
                " ON CONFLICT (business_id) DO UPDATE SET status = 'queued', error = NULL, updated_at = now()"
                " WHERE act_suggestion.status <> 'running'"
            ),
            {"b": business_id, "t": access.tenant_id},
        )
        await conn.execute(
            text(
                "INSERT INTO job (kind, tenant_id, business_id) VALUES ('suggest_acts', :t, :b)"
                " ON CONFLICT (kind, business_id) WHERE state = 'pending' DO NOTHING"
            ),
            {"t": access.tenant_id, "b": business_id},
        )
    return {"queued": True}


@router.get("/soundchecks/{soundcheck_id}/compare")
async def compare(
    business_id: UUID, soundcheck_id: UUID, state: State, access: Tenant
) -> dict[str, Any]:
    """Qloo against an AI alone for this act: the same question to both, side by side. Computed once, then stored."""
    await _business(state, access, business_id)
    await _limited(state, access, "sc-compare", 20, 600.0)
    doc = await compare_service.build(
        state.engine,
        state.guard,
        state.llm,
        state.limiter,
        state.settings.llm_daily_limit,
        access.tenant_id,
        business_id,
        soundcheck_id,
    )
    if doc is None:
        raise HTTPException(status_code=404, detail="not found")
    return doc
