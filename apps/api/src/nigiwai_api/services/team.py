"""The people in an account (a gap the first pass left): who they are, what each may do, and how someone new joins.

Joining is by a link the owner passes on, so no email service is needed. A link works once, for the role it names (manager or
viewer, never owner), until it expires after a week or the owner revokes it; only its hash is stored. The owner can change a
person's role or remove them, and the database refuses to leave an account with no owner. Every one of these steps is written to
the audit log (what, who, when). A person's sign-in address is shown to the account's own members and to nobody else.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ..db import transaction
from ..security import new_token, token_hash

INVITE_DAYS = 7
MAX_OPEN_INVITATIONS = 20
ROLES = ("owner", "manager", "viewer")


class TeamError(Exception):
    def __init__(self, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.status = status


def _state(exc: DBAPIError) -> str | None:
    return getattr(exc.orig, "sqlstate", None)


async def _audit(
    conn: AsyncConnection, tenant_id: UUID, actor: UUID, action: str, target: str
) -> None:
    await conn.execute(
        text("INSERT INTO audit_log (tenant_id, actor, action, target) VALUES (:t, :a, :x, :g)"),
        {"t": tenant_id, "a": str(actor), "x": action, "g": target},
    )


async def listing(
    engine: AsyncEngine, tenant_id: UUID, user_id: UUID, *, owner: bool
) -> dict[str, Any]:
    """The members, and for an owner the invitations that are still open."""
    async with transaction(engine, tenant_id=tenant_id, user_id=user_id) as conn:
        members = (
            await conn.execute(
                text("SELECT user_id, email, role, joined_at FROM team_members(:t)"),
                {"t": tenant_id},
            )
        ).all()
        invitations = (
            (
                await conn.execute(
                    text(
                        "SELECT id, role, created_at, expires_at FROM invitation"
                        " WHERE tenant_id = :t AND accepted_at IS NULL AND revoked_at IS NULL AND expires_at > now()"
                        " ORDER BY created_at DESC"
                    ),
                    {"t": tenant_id},
                )
            ).all()
            if owner
            else []
        )
    return {
        "members": [
            {
                "user_id": str(m.user_id),
                "email": m.email,
                "role": m.role,
                "joined_at": m.joined_at.isoformat(),
                "you": m.user_id == user_id,
            }
            for m in members
        ],
        "invitations": [
            {
                "id": str(i.id),
                "role": i.role,
                "created_at": i.created_at.isoformat(),
                "expires_at": i.expires_at.isoformat(),
            }
            for i in invitations
        ],
        "limits": {"invite_days": INVITE_DAYS, "max_open": MAX_OPEN_INVITATIONS},
    }


async def create_invitation(
    engine: AsyncEngine, tenant_id: UUID, user_id: UUID, role: str
) -> dict[str, Any]:
    """A new link. The token is returned here and never again: only its hash is kept."""
    if role not in ("manager", "viewer"):
        raise TeamError("An invitation can offer manager or viewer.")
    token = new_token(32)
    expires = datetime.now(UTC) + timedelta(days=INVITE_DAYS)
    async with transaction(engine, tenant_id=tenant_id, user_id=user_id) as conn:
        open_now = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM invitation WHERE tenant_id = :t AND accepted_at IS NULL AND revoked_at IS NULL"
                    " AND expires_at > now()"
                ),
                {"t": tenant_id},
            )
        ).scalar_one()
        if int(open_now) >= MAX_OPEN_INVITATIONS:
            raise TeamError(
                f"There are already {MAX_OPEN_INVITATIONS} open invitations. Revoke one first.", 409
            )
        row = (
            await conn.execute(
                text(
                    "INSERT INTO invitation (tenant_id, role, token_hash, created_by, expires_at)"
                    " VALUES (:t, :r, :h, :u, :e) RETURNING id"
                ),
                {"t": tenant_id, "r": role, "h": token_hash(token), "u": user_id, "e": expires},
            )
        ).one()
        await _audit(conn, tenant_id, user_id, f"team.invite.{role}", str(row.id))
    return {"id": str(row.id), "role": role, "token": token, "expires_at": expires.isoformat()}


async def revoke_invitation(
    engine: AsyncEngine, tenant_id: UUID, user_id: UUID, invitation_id: UUID
) -> bool:
    async with transaction(engine, tenant_id=tenant_id, user_id=user_id) as conn:
        done = (
            await conn.execute(
                text(
                    "UPDATE invitation SET revoked_at = now() WHERE id = :i AND tenant_id = :t"
                    " AND accepted_at IS NULL AND revoked_at IS NULL RETURNING id"
                ),
                {"i": invitation_id, "t": tenant_id},
            )
        ).first()
        if done is not None:
            await _audit(conn, tenant_id, user_id, "team.revoke", str(invitation_id))
    return done is not None


async def set_role(
    engine: AsyncEngine, tenant_id: UUID, actor: UUID, member: UUID, role: str
) -> None:
    if role not in ROLES:
        raise TeamError("Choose owner, manager or viewer.")
    try:
        async with transaction(engine, tenant_id=tenant_id, user_id=actor) as conn:
            done = (
                await conn.execute(
                    text(
                        "UPDATE membership SET role = :r WHERE tenant_id = :t AND user_id = :u RETURNING user_id"
                    ),
                    {"r": role, "t": tenant_id, "u": member},
                )
            ).first()
            if done is None:
                raise TeamError("That person is not in this account.", 404)
            await _audit(conn, tenant_id, actor, f"team.role.{role}", str(member))
    except DBAPIError as exc:
        if _state(exc) == "P0001":
            raise TeamError("An account must keep at least one owner.", 409) from exc
        raise


async def remove(engine: AsyncEngine, tenant_id: UUID, actor: UUID, member: UUID) -> None:
    try:
        async with transaction(engine, tenant_id=tenant_id, user_id=actor) as conn:
            done = (
                await conn.execute(
                    text(
                        "DELETE FROM membership WHERE tenant_id = :t AND user_id = :u RETURNING user_id"
                    ),
                    {"t": tenant_id, "u": member},
                )
            ).first()
            if done is None:
                raise TeamError("That person is not in this account.", 404)
            await _audit(conn, tenant_id, actor, "team.remove", str(member))
    except DBAPIError as exc:
        if _state(exc) == "P0001":
            raise TeamError("An account must keep at least one owner.", 409) from exc
        raise


async def peek(engine: AsyncEngine, token: str) -> dict[str, Any] | None:
    """What the holder of a link may see before signing in: the account's name, the role offered, and whether it still works."""
    async with engine.begin() as conn:
        row = (
            await conn.execute(
                text("SELECT tenant_name, role, state FROM invitation_peek(:h)"),
                {"h": token_hash(token)},
            )
        ).first()
    return (
        None if row is None else {"account": row.tenant_name, "role": row.role, "state": row.state}
    )


REASONS = {
    "used": "This invitation has already been used. Ask the owner for a new one.",
    "revoked": "This invitation was withdrawn. Ask the owner for a new one.",
    "expired": "This invitation has expired. Ask the owner for a new one.",
}


async def accept_in(conn: AsyncConnection, user_id: UUID, token: str) -> UUID:
    """Join the account an invitation is for, inside the caller's transaction (which carries the user's identity)."""
    try:
        got = (
            await conn.execute(
                text("SELECT invitation_accept(:h, :u)"), {"h": token_hash(token), "u": user_id}
            )
        ).scalar_one()
    except DBAPIError as exc:
        code = _state(exc)
        if code == "P0002":
            raise TeamError("This invitation link is not valid.", 404) from exc
        if code == "P0001":
            raise TeamError(
                "This invitation is no longer open. Ask the owner for a new one.", 410
            ) from exc
        if code == "23505":
            raise TeamError("You are already in this account.", 409) from exc
        raise
    return UUID(str(got))


async def accept(engine: AsyncEngine, user_id: UUID, token: str) -> UUID:
    async with transaction(engine, user_id=user_id) as conn:
        return await accept_in(conn, user_id, token)
