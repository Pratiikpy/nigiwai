"""Booking Brief endpoints (PRD M22): the document, its PDF, and share links. Owners are tenant-scoped like every owner
route; the shared link is the one place a reader without an account gets in, by an unguessable token that expires."""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import text

from ..db import transaction
from ..deps import State, Tenant
from ..services import brief as service
from ..services.brief_pdf import render
from .public import limit

router = APIRouter(prefix="/v1/tenants/{tenant_id}/businesses/{business_id}", tags=["brief"])
public = APIRouter(prefix="/v1/public/brief", tags=["brief"])

GONE = "This brief is no longer available."
PDF_HEADERS = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}


def _filename(doc: dict[str, Any]) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", doc["venue"]["business"].lower()).strip("-") or "venue"
    return f"booking-brief-{slug}-{doc['date']}.pdf"


async def _doc(state: Any, access: Any, business_id: UUID) -> dict[str, Any]:
    doc = await service.build(state.engine, access.tenant_id, business_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="not found")
    return doc


@router.get("/brief")
async def get_brief(business_id: UUID, state: State, access: Tenant) -> dict[str, Any]:
    return await _doc(state, access, business_id)


@router.get("/brief.pdf")
async def get_brief_pdf(business_id: UUID, state: State, access: Tenant) -> Response:
    doc = await _doc(state, access, business_id)
    return Response(
        render(doc),
        media_type="application/pdf",
        headers={**PDF_HEADERS, "Content-Disposition": f'attachment; filename="{_filename(doc)}"'},
    )


@router.get("/brief/shares")
async def shares(business_id: UUID, state: State, access: Tenant) -> list[dict[str, Any]]:
    await _doc(state, access, business_id)
    return await service.list_shares(state.engine, access.tenant_id, business_id)


@router.post("/brief/shares", status_code=201)
async def create_share(business_id: UUID, state: State, access: Tenant) -> dict[str, Any]:
    """Freeze the brief as it is now behind a new link that expires in 30 days."""
    if await state.limiter.check_all([(f"brief-share:{access.user_id}", 10, 3600.0)]):
        raise HTTPException(status_code=429, detail="Too many links created. Wait a little.")
    doc = await _doc(state, access, business_id)
    if doc["status"] != "ok":
        raise HTTPException(
            status_code=422, detail="There is nothing to share yet: " + doc["reason"]
        )
    made = await service.create_share(state.engine, access.tenant_id, business_id, doc)
    async with transaction(
        state.engine, tenant_id=access.tenant_id, user_id=access.user_id
    ) as conn:
        await conn.execute(
            text(
                "INSERT INTO audit_log (tenant_id, actor, action, target) VALUES (:t, :a, 'brief.share', :g)"
            ),
            {"t": access.tenant_id, "a": str(access.user_id), "g": made["id"]},
        )
    url = f"{state.settings.public_base_url.rstrip('/')}/b/{made.pop('token')}"
    return {**made, "url": url}


@router.delete("/brief/shares/{share_id}", status_code=204)
async def revoke_share(business_id: UUID, share_id: UUID, state: State, access: Tenant) -> Response:
    if not await service.revoke_share(state.engine, access.tenant_id, business_id, share_id):
        raise HTTPException(status_code=404, detail="not found")
    return Response(status_code=204)


@public.get("/{token}")
async def public_brief(token: str, request: Request, state: State) -> dict[str, Any]:
    await limit(state, request, [("pub-brief", 120, 600.0)])
    doc = await service.resolve_share(state.engine, token[:80])
    if doc is None:
        raise HTTPException(status_code=404, detail=GONE)
    return doc


@public.get("/{token}/pdf")
async def public_brief_pdf(token: str, request: Request, state: State) -> Response:
    await limit(state, request, [("pub-brief", 120, 600.0)])
    doc = await service.resolve_share(state.engine, token[:80])
    if doc is None:
        raise HTTPException(status_code=404, detail=GONE)
    return Response(
        render(doc),
        media_type="application/pdf",
        headers={**PDF_HEADERS, "Content-Disposition": f'attachment; filename="{_filename(doc)}"'},
    )
