"""The signed-in person's own login, and deleting an account or a login. See services/account.py for what each step does."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import EmailStr, Field
from sqlalchemy import text

from ..db import transaction
from ..deps import Session, State, Tenant, client_ip_hash
from ..schemas import Name, Strict
from ..services import account as service
from ..services import account_export

router = APIRouter(prefix="/v1/account", tags=["account"])
tenant_router = APIRouter(prefix="/v1/tenants/{tenant_id}", tags=["account"])
public = APIRouter(prefix="/v1/auth", tags=["account"])

Secret = Field(min_length=1, max_length=200)


class PasswordIn(Strict):
    current_password: str = Secret
    new_password: str = Secret


class ConfirmIn(Strict):
    password: str = Secret


class DeleteAccountIn(Strict):
    password: str = Secret
    confirm_name: str = Field(min_length=1, max_length=200)


class NewAccountIn(Strict):
    business_name: Name


class RecoverIn(Strict):
    email: EmailStr
    recovery_code: str = Field(min_length=1, max_length=100)
    new_password: str = Secret


def _refused(exc: service.AccountError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=str(exc))


async def _guarded(state: State, user_key: str, count: int = 8, window: float = 600.0) -> None:
    """Everything that asks for the password again is limited per person, so it cannot be used to guess it."""
    if await state.limiter.check_all([(f"account:{user_key}", count, window)]):
        raise HTTPException(status_code=429, detail="Too many attempts. Wait a few minutes.")


@router.get("")
async def overview(state: State, session: Session) -> dict[str, Any]:
    return await service.overview(state.engine, session.user_id)


@router.put("/password", status_code=204)
async def change_password(body: PasswordIn, state: State, session: Session) -> Response:
    await _guarded(state, str(session.user_id))
    try:
        await service.change_password(
            state.engine,
            session.user_id,
            session.session_id,
            body.current_password,
            body.new_password,
        )
    except service.AccountError as exc:
        raise _refused(exc) from exc
    return Response(status_code=204)


@router.post("/recovery-code")
async def recovery_code(body: ConfirmIn, state: State, session: Session) -> dict[str, str]:
    await _guarded(state, str(session.user_id))
    try:
        return {
            "recovery_code": await service.make_recovery_code(
                state.engine, session.user_id, body.password
            )
        }
    except service.AccountError as exc:
        raise _refused(exc) from exc


@router.post("/accounts", status_code=201)
async def new_account(body: NewAccountIn, state: State, session: Session) -> dict[str, str]:
    await _guarded(state, f"new:{session.user_id}", 3, 3600.0)
    try:
        return await service.new_account(state.engine, session.user_id, body.business_name)
    except service.AccountError as exc:
        raise _refused(exc) from exc


@router.post("/sign-out-everywhere", status_code=204)
async def sign_out_everywhere(response: Response, state: State, session: Session) -> Response:
    await service.sign_out_everywhere(state.engine, session.user_id)
    response.delete_cookie(state.settings.session_cookie, path="/")
    response.status_code = 204
    return response


@router.post("/delete", status_code=204)
async def delete_login(
    body: ConfirmIn, response: Response, state: State, session: Session
) -> Response:
    await _guarded(state, str(session.user_id), 5, 3600.0)
    try:
        await service.delete_login(state.engine, session.user_id, body.password)
    except service.AccountError as exc:
        raise _refused(exc) from exc
    response.delete_cookie(state.settings.session_cookie, path="/")
    response.status_code = 204
    return response


@tenant_router.get("/export")
async def export_account(state: State, access: Tenant) -> Response:
    """A copy of the account's data as a ZIP, for an owner (what is in it and what is left out is in the file's README)."""
    if access.role != "owner":
        raise HTTPException(
            status_code=403, detail="Only an owner can download a copy of the account's data."
        )
    await _guarded(state, f"export:{access.user_id}", 5, 3600.0)
    data, name = await account_export.build(state.engine, access.tenant_id, access.user_id)
    async with transaction(
        state.engine, tenant_id=access.tenant_id, user_id=access.user_id
    ) as conn:
        await conn.execute(
            text(
                "INSERT INTO audit_log (tenant_id, actor, action, target) VALUES (:t, :a, 'account.export', :n)"
            ),
            {"t": access.tenant_id, "a": str(access.user_id), "n": name},
        )
    return Response(
        content=data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "Cache-Control": "private, no-store",
        },
    )


@tenant_router.post("/delete-account", status_code=204)
async def delete_account(body: DeleteAccountIn, state: State, access: Tenant) -> Response:
    if access.role != "owner":
        raise HTTPException(status_code=403, detail="Only an owner can delete an account.")
    await _guarded(state, str(access.user_id), 5, 3600.0)
    try:
        await service.delete_account(
            state.engine, access.tenant_id, access.user_id, body.confirm_name, body.password
        )
    except service.AccountError as exc:
        raise _refused(exc) from exc
    return Response(status_code=204)


@public.post("/recover")
async def recover(body: RecoverIn, request: Request, state: State) -> dict[str, str]:
    email = str(body.email).lower()
    blocked = await state.limiter.check_all(
        [
            (f"recover-acct:{email}", 5, 3600.0),
            (f"recover-ip:{client_ip_hash(request, state)}", 20, 3600.0),
        ]
    )
    if blocked:
        raise HTTPException(
            status_code=429, detail="Too many attempts. Wait a while and try again."
        )
    try:
        fresh = await service.recover(state.engine, email, body.recovery_code, body.new_password)
    except service.AccountError as exc:
        raise _refused(exc) from exc
    return {"recovery_code": fresh}
