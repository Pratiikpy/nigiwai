"""The people in an account: who is in it, what each may do, and the links that bring someone new in. Anyone in the account can read the
list; only an owner can invite, change a role or remove someone. The link itself is public in the way a secret link is: whoever holds
it may see the account's name and the role offered, and join with it once. The secret sits in the link's fragment (after the #), which
a browser never sends, and is passed to the API in a request body, so it reaches no access log, proxy log or referrer."""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import StringConstraints

from ..deps import Session, State, Tenant, TenantAccess
from ..schemas import Strict
from ..services import team as service
from .public import limit

router = APIRouter(prefix="/v1/tenants/{tenant_id}/team", tags=["team"])
public = APIRouter(prefix="/v1/invitations", tags=["team"])

Token = Annotated[
    str, StringConstraints(min_length=20, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
]


class InviteIn(Strict):
    role: Literal["manager", "viewer"]


class RoleIn(Strict):
    role: Literal["owner", "manager", "viewer"]


class AcceptIn(Strict):
    token: Token


async def _owner(access: Tenant) -> TenantAccess:
    if access.role != "owner":
        raise HTTPException(
            status_code=403, detail="only an owner can change who is in the account"
        )
    return access


def _refused(exc: service.TeamError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=str(exc))


@router.get("")
async def team(state: State, access: Tenant) -> dict[str, Any]:
    return await service.listing(
        state.engine, access.tenant_id, access.user_id, owner=access.role == "owner"
    )


@router.post("/invitations", status_code=201)
async def invite(body: InviteIn, state: State, access: Tenant) -> dict[str, Any]:
    await _owner(access)
    if await state.limiter.check_all([(f"invite:{access.user_id}", 30, 3600.0)]):
        raise HTTPException(
            status_code=429, detail="Too many invitations. Wait a little and try again."
        )
    try:
        made = await service.create_invitation(
            state.engine, access.tenant_id, access.user_id, body.role
        )
    except service.TeamError as exc:
        raise _refused(exc) from exc
    base = state.settings.public_base_url.rstrip("/")
    return {**made, "url": f"{base}/invite#{made['token']}"}


@router.delete("/invitations/{invitation_id}", status_code=204)
async def revoke(invitation_id: UUID, state: State, access: Tenant) -> Response:
    await _owner(access)
    if not await service.revoke_invitation(
        state.engine, access.tenant_id, access.user_id, invitation_id
    ):
        raise HTTPException(status_code=404, detail="not found")
    return Response(status_code=204)


@router.put("/members/{user_id}")
async def change_role(user_id: UUID, body: RoleIn, state: State, access: Tenant) -> dict[str, Any]:
    await _owner(access)
    try:
        await service.set_role(state.engine, access.tenant_id, access.user_id, user_id, body.role)
    except service.TeamError as exc:
        raise _refused(exc) from exc
    return await service.listing(state.engine, access.tenant_id, access.user_id, owner=True)


@router.delete("/members/{user_id}", status_code=204)
async def remove(user_id: UUID, state: State, access: Tenant) -> Response:
    await _owner(access)
    try:
        await service.remove(state.engine, access.tenant_id, access.user_id, user_id)
    except service.TeamError as exc:
        raise _refused(exc) from exc
    return Response(status_code=204)


@public.post("/peek")
async def peek(body: AcceptIn, request: Request, state: State) -> dict[str, Any]:
    await limit(state, request, [("invite-peek", 60, 600.0)])
    found = await service.peek(state.engine, body.token)
    if found is None:
        raise HTTPException(status_code=404, detail="This invitation link is not valid.")
    return {**found, "reason": service.REASONS.get(found["state"])}


@public.post("/accept")
async def accept(body: AcceptIn, state: State, session: Session) -> dict[str, Any]:
    if await state.limiter.check_all([(f"invite-accept:{session.user_id}", 10, 600.0)]):
        raise HTTPException(status_code=429, detail="Too many attempts. Wait a few minutes.")
    try:
        tenant_id = await service.accept(state.engine, session.user_id, body.token)
    except service.TeamError as exc:
        raise _refused(exc) from exc
    return {"tenant_id": str(tenant_id)}
