"""Database access. Every request runs in a transaction that sets the tenant and user for row-level security."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from .settings import Settings


def make_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.database_url, pool_size=10, max_overflow=10, pool_pre_ping=True
    )


@asynccontextmanager
async def transaction(
    engine: AsyncEngine, *, tenant_id: UUID | None = None, user_id: UUID | None = None
) -> AsyncIterator[AsyncConnection]:
    """One transaction with `app.tenant_id` and `app.user_id` set for its duration only (SET LOCAL semantics).

    The values are bound parameters of set_config, never interpolated, and are cleared when the transaction ends.
    """
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "SELECT set_config('app.tenant_id', :t, true), set_config('app.user_id', :u, true)"
            ),
            {"t": str(tenant_id) if tenant_id else "", "u": str(user_id) if user_id else ""},
        )
        yield conn


async def assert_rls_effective(engine: AsyncEngine) -> None:
    """Refuse to run as a role that would silently bypass row-level security: a superuser, a BYPASSRLS role, or
    the owner of the tenant tables."""
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT r.rolsuper, r.rolbypassrls, (c.relowner = r.oid) AS owns"
                    " FROM pg_roles r, pg_class c WHERE r.rolname = current_user AND c.relname = 'response'"
                )
            )
        ).first()
    if row is None:
        raise RuntimeError("schema is not migrated: table 'response' not found")
    if row.rolsuper or row.rolbypassrls or row.owns:
        raise RuntimeError(
            "database role bypasses row-level security (superuser, BYPASSRLS or table owner); "
            "connect the API as the non-owner application role"
        )
