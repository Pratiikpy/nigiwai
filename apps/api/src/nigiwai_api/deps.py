"""Shared application state and request dependencies: sessions, CSRF, tenant membership."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request
from qloo_guard import QlooGuard
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from .db import transaction
from .ratelimit import RateLimiter
from .security import check_csrf, ip_hash, token_hash
from .services.guard_stores import PgBackedLedger
from .settings import Settings

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


@dataclass
class AppState:
    settings: Settings
    engine: AsyncEngine
    redis: Any
    limiter: RateLimiter
    guard: QlooGuard | None
    ledger: PgBackedLedger | None
    picker: Any  # PickerService; typed loosely to avoid an import cycle
    musicbrainz: Any = (
        None  # MusicBrainz client (services.lineup); typed loosely for the same reason
    )
    llm: Any = None  # LlmClient (services.llm), or None when no model key is configured
    geocoder: Any = None  # Geocoder (services.geocode)


def state_of(request: Request) -> AppState:
    state = request.app.state.nigiwai
    assert isinstance(state, AppState)
    return state


State = Annotated[AppState, Depends(state_of)]


@dataclass(frozen=True)
class SessionInfo:
    session_id: UUID
    user_id: UUID
    email: str
    csrf_secret: str


def client_ip(request: Request, settings: Settings) -> str:
    if settings.trust_proxy:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def client_ip_hash(request: Request, state: AppState) -> str:
    return ip_hash(state.settings.secret_key, client_ip(request, state.settings))


async def load_session(request: Request, state: AppState) -> SessionInfo | None:
    token = request.cookies.get(state.settings.session_cookie)
    if not token:
        return None
    async with state.engine.begin() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT s.id, s.user_id, s.csrf_secret, u.email FROM app_session s JOIN app_user u ON u.id = s.user_id"
                    " WHERE s.token_hash = :h AND s.expires_at > now() AND u.deleted_at IS NULL"
                ),
                {"h": token_hash(token)},
            )
        ).first()
        if row is None:
            return None
        # Touch at most once a minute so reads stay cheap.
        await conn.execute(
            text(
                "UPDATE app_session SET last_seen_at = now() WHERE id = :i AND last_seen_at < now() - interval '1 minute'"
            ),
            {"i": row.id},
        )
    return SessionInfo(
        session_id=row.id, user_id=row.user_id, email=str(row.email), csrf_secret=row.csrf_secret
    )


async def require_session(request: Request, state: State) -> SessionInfo:
    session = await load_session(request, state)
    if session is None:
        raise HTTPException(status_code=401, detail="sign in required")
    if request.method not in SAFE_METHODS:
        presented = request.headers.get("x-csrf-token")
        if not check_csrf(state.settings.secret_key, session.csrf_secret, presented):
            raise HTTPException(status_code=403, detail="missing or invalid CSRF token")
    return session


Session = Annotated[SessionInfo, Depends(require_session)]


@dataclass(frozen=True)
class TenantAccess:
    tenant_id: UUID
    user_id: UUID
    role: str

    @property
    def can_write(self) -> bool:
        return self.role in ("owner", "manager")


async def require_tenant(tenant_id: UUID, state: State, session: Session) -> TenantAccess:
    """The caller must be a member of the tenant in the URL. Membership is read under the user's own RLS scope."""
    async with transaction(state.engine, user_id=session.user_id) as conn:
        role = (
            await conn.execute(
                text("SELECT role FROM membership WHERE tenant_id = :t AND user_id = :u"),
                {"t": tenant_id, "u": session.user_id},
            )
        ).scalar_one_or_none()
    if role is None:
        raise HTTPException(
            status_code=404, detail="not found"
        )  # same answer as a tenant that does not exist
    return TenantAccess(tenant_id=tenant_id, user_id=session.user_id, role=role)


Tenant = Annotated[TenantAccess, Depends(require_tenant)]


async def require_writer(access: Tenant) -> TenantAccess:
    if not access.can_write:
        raise HTTPException(status_code=403, detail="your role cannot change this")
    return access


Writer = Annotated[TenantAccess, Depends(require_writer)]

__all__ = [
    "AppState",
    "Header",
    "Session",
    "SessionInfo",
    "State",
    "Tenant",
    "TenantAccess",
    "Writer",
    "client_ip",
    "client_ip_hash",
    "state_of",
]
