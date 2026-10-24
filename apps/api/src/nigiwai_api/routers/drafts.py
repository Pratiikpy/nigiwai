"""Drafts (PRD M17, M10): text prepared for the owner to review, approve or withdraw. Anyone in the account can read; only
someone who can change the account can make, edit or decide on one. Nothing is sent from here."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response
from pydantic import Field, StringConstraints

from ..deps import State, Tenant, Writer
from ..schemas import Strict
from ..services import drafts as service
from ..services import drafts_model as dm

router = APIRouter(prefix="/v1/tenants/{tenant_id}/businesses/{business_id}", tags=["drafts"])


class DraftsIn(Strict):
    # exactly one of the two
    from_action: Annotated[str, StringConstraints(min_length=1, max_length=120)] | None = None
    group_index: int | None = Field(default=None, ge=0, le=50)


class DraftEdit(Strict):
    subject: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    body: Annotated[str, StringConstraints(min_length=1, max_length=dm.MAX_BODY)]


def _refused(exc: service.DraftError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=str(exc))


@router.get("/drafts")
async def drafts(business_id: UUID, state: State, access: Tenant) -> dict[str, Any]:
    doc = await service.listing(state.engine, access.tenant_id, business_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="not found")
    return doc


@router.post("/drafts", status_code=201)
async def create(
    business_id: UUID, body: DraftsIn, state: State, access: Writer
) -> dict[str, list[str]]:
    try:
        made = await service.create(
            state.engine,
            access.tenant_id,
            access.user_id,
            business_id,
            from_action=body.from_action,
            group_index=body.group_index,
        )
    except service.DraftError as exc:
        raise _refused(exc) from exc
    return {"ids": made}


@router.get("/drafts/{draft_id}")
async def one(business_id: UUID, draft_id: UUID, state: State, access: Tenant) -> dict[str, Any]:
    try:
        return await service.get(state.engine, access.tenant_id, business_id, draft_id)
    except service.DraftError as exc:
        raise _refused(exc) from exc


@router.put("/drafts/{draft_id}")
async def edit(
    business_id: UUID, draft_id: UUID, body: DraftEdit, state: State, access: Writer
) -> dict[str, Any]:
    try:
        return await service.update(
            state.engine,
            access.tenant_id,
            access.user_id,
            business_id,
            draft_id,
            subject=body.subject,
            body=body.body,
        )
    except service.DraftError as exc:
        raise _refused(exc) from exc


@router.post("/drafts/{draft_id}/approve")
async def approve(
    business_id: UUID, draft_id: UUID, state: State, access: Writer
) -> dict[str, Any]:
    try:
        return await service.approve(
            state.engine, access.tenant_id, access.user_id, business_id, draft_id
        )
    except service.DraftError as exc:
        raise _refused(exc) from exc


@router.post("/drafts/{draft_id}/withdraw")
async def withdraw(
    business_id: UUID, draft_id: UUID, state: State, access: Writer
) -> dict[str, Any]:
    try:
        return await service.withdraw(
            state.engine, access.tenant_id, access.user_id, business_id, draft_id
        )
    except service.DraftError as exc:
        raise _refused(exc) from exc


@router.delete("/drafts/{draft_id}", status_code=204)
async def remove(business_id: UUID, draft_id: UUID, state: State, access: Writer) -> Response:
    try:
        await service.delete(state.engine, access.tenant_id, access.user_id, business_id, draft_id)
    except service.DraftError as exc:
        raise _refused(exc) from exc
    return Response(status_code=204)
