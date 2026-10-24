"""The Today board (PRD M5): this week's actions, the quietest hours, and the owner's decisions. Tenant-scoped like every
owner route; anyone in the account can read the board, only someone who can change the account can decide on it."""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Path

from ..deps import State, Tenant, Writer
from ..schemas import Strict
from ..services import today as service

router = APIRouter(prefix="/v1/tenants/{tenant_id}/businesses/{business_id}", tags=["today"])

ActionKey = Annotated[str, Path(min_length=1, max_length=120, pattern=r"^[a-z]+:[0-9a-fA-F:-]+$")]


class DecisionIn(Strict):
    # null undoes an earlier decision
    state: Literal["accepted", "dismissed"] | None


def _refused(exc: service.TodayError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=str(exc))


@router.get("/today")
async def board(business_id: UUID, state: State, access: Tenant) -> dict[str, Any]:
    doc = await service.build(state.engine, access.tenant_id, business_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="not found")
    return doc


@router.put("/today/actions/{key}")
async def decide(
    business_id: UUID, key: ActionKey, body: DecisionIn, state: State, access: Writer
) -> dict[str, Any]:
    try:
        return await service.decide(
            state.engine, access.tenant_id, access.user_id, business_id, key, body.state
        )
    except service.TodayError as exc:
        raise _refused(exc) from exc


@router.post("/today/actions/{key}/log")
async def log_move(
    business_id: UUID, key: ActionKey, state: State, access: Writer
) -> dict[str, Any]:
    try:
        return await service.log_move(
            state.engine, access.tenant_id, access.user_id, business_id, key
        )
    except service.TodayError as exc:
        raise _refused(exc) from exc
