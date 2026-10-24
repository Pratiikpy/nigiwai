"""Accounts: signup, login, logout, whoami. First-party sessions (decision D2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from ..db import transaction
from ..deps import Session, State, client_ip_hash, load_session
from ..schemas import LoginIn, MeOut, SignupIn, TenantOut
from ..security import (
    WeakPassword,
    check_password_policy,
    csrf_token,
    hash_password,
    needs_rehash,
    new_token,
    token_hash,
    verify_password,
)
from ..services import account as account_service
from ..services import team as team_service

router = APIRouter(prefix="/v1/auth", tags=["auth"])


def _set_cookie(response: Response, state_settings, token: str, max_age: int) -> None:  # type: ignore[no-untyped-def]
    response.set_cookie(
        state_settings.session_cookie,
        token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=state_settings.cookie_secure,
        path="/",
    )


async def _create_session(state, response: Response, user_id) -> str:  # type: ignore[no-untyped-def]
    token = new_token(32)
    csrf_secret = new_token(16)
    ttl = timedelta(days=state.settings.session_ttl_days)
    async with state.engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO app_session (user_id, token_hash, csrf_secret, expires_at) VALUES (:u, :h, :c, :e)"
            ),
            {"u": user_id, "h": token_hash(token), "c": csrf_secret, "e": datetime.now(UTC) + ttl},
        )
    _set_cookie(response, state.settings, token, int(ttl.total_seconds()))
    return csrf_secret


@router.post("/signup", status_code=201)
async def signup(body: SignupIn, request: Request, response: Response, state: State) -> MeOut:
    blocked = await state.limiter.check_all(
        [(f"signup-ip:{client_ip_hash(request, state)}", 10, 3600.0)]
    )
    if blocked:
        raise HTTPException(
            status_code=429, detail="too many sign-ups from this network; try again later"
        )
    email = str(body.email).lower()
    try:
        check_password_policy(body.password, email)
    except WeakPassword as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if (body.business_name is None) == (body.invite_token is None):
        raise HTTPException(
            status_code=422,
            detail=[
                {
                    "field": "business_name",
                    "message": "Give the name of your business, or sign up from an invitation link, not both.",
                }
            ],
        )
    pw_hash = hash_password(body.password)
    user_id = uuid4()
    code = account_service.new_recovery_code()
    try:
        # The account and its tenant (or its place in the tenant it was invited to) are created in one transaction, so a failure
        # leaves nothing behind.
        async with transaction(state.engine, user_id=user_id) as conn:
            await conn.execute(
                text(
                    "INSERT INTO app_user (id, email, password_hash, recovery_hash, recovery_set_at)"
                    " VALUES (:i, :e, :p, :r, now())"
                ),
                {"i": user_id, "e": email, "p": pw_hash, "r": account_service.recovery_hash(code)},
            )
            if body.invite_token is not None:
                await team_service.accept_in(conn, user_id, body.invite_token)
            else:
                await conn.execute(
                    text("SELECT create_tenant(:n, :u)"), {"n": body.business_name, "u": user_id}
                )
    except team_service.TeamError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    except IntegrityError as exc:
        # Reported plainly: a duplicate address has to be fixable by the person who typed it.
        raise HTTPException(
            status_code=409, detail="an account with this email already exists"
        ) from exc
    csrf_secret = await _create_session(state, response, user_id)
    me = await _me(state, user_id, email, csrf_secret)
    return me.model_copy(update={"recovery_code": code})


@router.post("/login")
async def login(body: LoginIn, request: Request, response: Response, state: State) -> MeOut:
    email = str(body.email).lower()
    blocked = await state.limiter.check_all(
        [
            (f"login-acct:{email}", 8, 600.0),
            (f"login-ip:{client_ip_hash(request, state)}", 40, 600.0),
        ]
    )
    if blocked:
        raise HTTPException(status_code=429, detail="too many attempts; wait a few minutes")
    async with state.engine.begin() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT id, password_hash FROM app_user WHERE email = :e AND deleted_at IS NULL"
                ),
                {"e": email},
            )
        ).first()
    stored = row.password_hash if row else None
    if not verify_password(stored, body.password) or row is None:
        raise HTTPException(
            status_code=401, detail="email or password is wrong"
        )  # one answer for both cases
    if needs_rehash(row.password_hash):
        async with state.engine.begin() as conn:
            await conn.execute(
                text("UPDATE app_user SET password_hash = :p WHERE id = :i"),
                {"p": hash_password(body.password), "i": row.id},
            )
    csrf_secret = await _create_session(state, response, row.id)
    return await _me(state, row.id, email, csrf_secret)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response, state: State, session: Session) -> Response:
    async with state.engine.begin() as conn:
        await conn.execute(text("DELETE FROM app_session WHERE id = :i"), {"i": session.session_id})
    response.delete_cookie(state.settings.session_cookie, path="/")
    response.status_code = 204
    return response


@router.get("/me")
async def me(request: Request, state: State) -> MeOut:
    session = await load_session(request, state)
    if session is None:
        raise HTTPException(status_code=401, detail="sign in required")
    return await _me(state, session.user_id, session.email, session.csrf_secret)


async def _me(state, user_id, email: str, csrf_secret: str) -> MeOut:  # type: ignore[no-untyped-def]
    async with transaction(state.engine, user_id=user_id) as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT t.id, t.name, m.role FROM membership m JOIN tenant t ON t.id = m.tenant_id"
                    " WHERE m.user_id = :u AND t.deleted_at IS NULL ORDER BY t.created_at"
                ),
                {"u": user_id},
            )
        ).all()
    return MeOut(
        user_id=user_id,
        email=email,
        csrf_token=csrf_token(state.settings.secret_key, csrf_secret),
        tenants=[TenantOut(id=r.id, name=r.name, role=r.role) for r in rows],
    )
