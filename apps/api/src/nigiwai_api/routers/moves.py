"""Moves (PRD M11): what the owner changed, and what scans in the same slot did around it. Anyone in the account can read;
only someone who can change the account can log, edit or remove a move."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response
from pydantic import Field, StringConstraints

from ..deps import State, Tenant, Writer
from ..schemas import Strict
from ..services import moves as service

router = APIRouter(prefix="/v1/tenants/{tenant_id}/businesses/{business_id}", tags=["moves"])


class MoveIn(Strict):
    kind: Literal["act", "event", "menu", "ad", "price", "other"]
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
    # dates arrive as ISO text in JSON; the model is strict about everything else
    started_on: date = Field(strict=False)
    ended_on: date | None = Field(default=None, strict=False)
    weekdays: list[int] = Field(default_factory=list, max_length=7)
    hour_from: int | None = Field(default=None, ge=0, le=23)
    hour_to: int | None = Field(default=None, ge=1, le=24)
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=400)] | None = None


def _refused(exc: service.MoveError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=str(exc))


@router.get("/moves")
async def moves(business_id: UUID, state: State, access: Tenant) -> dict[str, Any]:
    doc = await service.listing(state.engine, access.tenant_id, business_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="not found")
    return doc


@router.post("/moves", status_code=201)
async def create(business_id: UUID, body: MoveIn, state: State, access: Writer) -> dict[str, str]:
    try:
        new = await service.create(
            state.engine,
            access.tenant_id,
            access.user_id,
            business_id,
            kind=body.kind,
            title=body.title,
            started_on=body.started_on,
            ended_on=body.ended_on,
            weekdays=body.weekdays,
            hour_from=body.hour_from,
            hour_to=body.hour_to,
            note=body.note or None,
        )
    except service.MoveError as exc:
        raise _refused(exc) from exc
    return {"id": new}


@router.put("/moves/{move_id}", status_code=204)
async def update(
    business_id: UUID, move_id: UUID, body: MoveIn, state: State, access: Writer
) -> Response:
    try:
        await service.update(
            state.engine,
            access.tenant_id,
            access.user_id,
            business_id,
            move_id,
            kind=body.kind,
            title=body.title,
            started_on=body.started_on,
            ended_on=body.ended_on,
            weekdays=body.weekdays,
            hour_from=body.hour_from,
            hour_to=body.hour_to,
            note=body.note or None,
        )
    except service.MoveError as exc:
        raise _refused(exc) from exc
    return Response(status_code=204)


@router.delete("/moves/{move_id}", status_code=204)
async def remove(business_id: UUID, move_id: UUID, state: State, access: Writer) -> Response:
    try:
        await service.delete(state.engine, access.tenant_id, access.user_id, business_id, move_id)
    except service.MoveError as exc:
        raise _refused(exc) from exc
    return Response(status_code=204)
