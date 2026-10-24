"""Looking after a login, and the promises the privacy page makes about it.

No email service is authorised (HUMAN H2), so there is no emailed reset link. What stands in its place is a recovery code: made when
someone signs up, shown once, kept only as a hash, and able to set a new password without signing in. Beyond that: change the
password (which signs every other session out), sign out everywhere, make a new recovery code, delete an account and everything in
it (owners), and delete a login (refused while the person alone holds up an account, so no account is left without an owner).
"""

from __future__ import annotations

import hmac
import secrets
from collections.abc import Sequence
from hashlib import sha256
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from ..db import transaction
from ..security import (
    WeakPassword,
    check_password_policy,
    hash_password,
    verify_password,
)

# No 0, O, 1, I, L or U: a code read off paper or typed from a phone cannot be misread. 20 characters is about 98 bits.
ALPHABET = "ABCDEFGHJKMNPQRSTVWXYZ23456789"
CODE_LENGTH = 20
GROUP = 5


class AccountError(Exception):
    def __init__(self, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.status = status


def new_recovery_code() -> str:
    raw = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
    return "-".join(raw[i : i + GROUP] for i in range(0, CODE_LENGTH, GROUP))


def normalise(code: str) -> str:
    """What was typed, reduced to letters and digits in capitals, so spaces, dashes and case do not matter."""
    return "".join(ch for ch in code.upper() if ch.isascii() and ch.isalnum())


def recovery_hash(code: str) -> bytes:
    return sha256(normalise(code).encode("ascii")).digest()


def _state(exc: DBAPIError) -> str | None:
    return getattr(exc.orig, "sqlstate", None)


async def _credentials(engine: AsyncEngine, user_id: UUID) -> Any:
    async with transaction(engine, user_id=user_id) as conn:
        return (
            await conn.execute(
                text(
                    "SELECT email, password_hash FROM app_user WHERE id = :u AND deleted_at IS NULL"
                ),
                {"u": user_id},
            )
        ).first()


async def _check_password(engine: AsyncEngine, user_id: UUID, password: str) -> str:
    """The person's current password, asked again before anything that cannot be undone. Returns their email."""
    row = await _credentials(engine, user_id)
    if row is None or not verify_password(row.password_hash, password):
        raise AccountError("That password is not right.", 403)
    return str(row.email)


async def overview(engine: AsyncEngine, user_id: UUID) -> dict[str, Any]:
    async with transaction(engine, user_id=user_id) as conn:
        user = (
            await conn.execute(
                text("SELECT email, created_at, recovery_set_at FROM app_user WHERE id = :u"),
                {"u": user_id},
            )
        ).one()
        accounts = (
            await conn.execute(
                text(
                    "SELECT t.id, t.name, m.role FROM membership m JOIN tenant t ON t.id = m.tenant_id"
                    " WHERE m.user_id = :u AND t.deleted_at IS NULL ORDER BY t.created_at"
                ),
                {"u": user_id},
            )
        ).all()
        sole = {
            r.tenant_id: r.others
            for r in (
                await conn.execute(
                    text("SELECT tenant_id, others FROM sole_owner_of(:u)"), {"u": user_id}
                )
            ).all()
        }
    return {
        "email": str(user.email),
        "created_at": user.created_at.isoformat(),
        "recovery_set_at": user.recovery_set_at.isoformat() if user.recovery_set_at else None,
        "accounts": [
            {
                "id": str(a.id),
                "name": a.name,
                "role": a.role,
                # set when the person alone holds this account up; `others` is how many other people are in it
                "sole_owner": a.id in sole,
                "others": sole.get(a.id),
            }
            for a in accounts
        ],
    }


async def change_password(
    engine: AsyncEngine, user_id: UUID, session_id: UUID, current: str, new: str
) -> None:
    email = await _check_password(engine, user_id, current)
    try:
        check_password_policy(new, email)
    except WeakPassword as exc:
        raise AccountError(str(exc)) from exc
    if new == current:
        raise AccountError("Choose a password you have not been using.")
    async with transaction(engine, user_id=user_id) as conn:
        await conn.execute(
            text("UPDATE app_user SET password_hash = :p WHERE id = :u"),
            {"p": hash_password(new), "u": user_id},
        )
        # a changed password ends every other sign-in, so a stolen session does not outlive it; this one stays
        await conn.execute(
            text("DELETE FROM app_session WHERE user_id = :u AND id <> :s"),
            {"u": user_id, "s": session_id},
        )


async def make_recovery_code(engine: AsyncEngine, user_id: UUID, password: str) -> str:
    """A new code, replacing any earlier one. It is returned here and never again."""
    await _check_password(engine, user_id, password)
    code = new_recovery_code()
    async with transaction(engine, user_id=user_id) as conn:
        await conn.execute(
            text("UPDATE app_user SET recovery_hash = :h, recovery_set_at = now() WHERE id = :u"),
            {"h": recovery_hash(code), "u": user_id},
        )
    return code


# Verified against when the address is unknown, so the answer takes the same time and says the same thing.
_NO_CODE = sha256(b"no recovery code").digest()
_MISMATCH = "That email and recovery code do not match."


async def recover(engine: AsyncEngine, email: str, code: str, new_password: str) -> str:
    """Set a new password from a recovery code. Signs every session out and returns a fresh code (the old one is spent)."""
    try:
        check_password_policy(new_password, email)
    except WeakPassword as exc:
        raise AccountError(str(exc)) from exc
    async with engine.begin() as conn:
        row = (
            await conn.execute(
                text("SELECT id, recovery_hash FROM auth_user_by_email(:e)"),
                {"e": email},
            )
        ).first()
    stored = (
        bytes(row.recovery_hash) if row is not None and row.recovery_hash is not None else _NO_CODE
    )
    right = hmac.compare_digest(stored, recovery_hash(code))
    if row is None or row.recovery_hash is None or not right:
        raise AccountError(_MISMATCH, 401)
    fresh = new_recovery_code()
    async with transaction(engine, user_id=row.id) as conn:
        # the old code is spent in the same statement that checks it, so two people racing with it cannot both succeed
        done = (
            await conn.execute(
                text(
                    "UPDATE app_user SET password_hash = :p, recovery_hash = :n, recovery_set_at = now()"
                    " WHERE id = :u AND recovery_hash = :o RETURNING id"
                ),
                {
                    "p": hash_password(new_password),
                    "n": recovery_hash(fresh),
                    "u": row.id,
                    "o": recovery_hash(code),
                },
            )
        ).first()
        if done is None:
            raise AccountError(_MISMATCH, 401)
        await conn.execute(text("DELETE FROM app_session WHERE user_id = :u"), {"u": row.id})
    return fresh


async def sign_out_everywhere(engine: AsyncEngine, user_id: UUID) -> None:
    async with transaction(engine, user_id=user_id) as conn:
        await conn.execute(text("DELETE FROM app_session WHERE user_id = :u"), {"u": user_id})


async def delete_account(
    engine: AsyncEngine, tenant_id: UUID, user_id: UUID, confirm_name: str, password: str
) -> None:
    """Delete an account and everything in it. The caller has typed its name and their password."""
    await _check_password(engine, user_id, password)
    async with transaction(engine, user_id=user_id) as conn:
        name = (
            await conn.execute(
                text(
                    "SELECT t.name FROM tenant t JOIN membership m ON m.tenant_id = t.id"
                    " WHERE t.id = :t AND m.user_id = :u AND m.role = 'owner'"
                ),
                {"t": tenant_id, "u": user_id},
            )
        ).scalar_one_or_none()
        if name is None:
            raise AccountError("Only an owner can delete an account.", 403)
        if confirm_name.strip().casefold() != str(name).strip().casefold():
            raise AccountError("The name typed does not match this account's name.")
        try:
            await conn.execute(text("SELECT delete_tenant(:t, :u)"), {"t": tenant_id, "u": user_id})
        except DBAPIError as exc:
            if _state(exc) == "42501":
                raise AccountError("This account cannot be deleted.", 403) from exc
            raise


def _holds_up(rows: Sequence[Any]) -> str:
    names = ", ".join(f"“{r.tenant_name}”" for r in rows)
    return (
        f"You are the only owner of {names}. Make someone else an owner, or delete "
        f"{'it' if len(rows) == 1 else 'them'}, before deleting your login."
    )


MAX_OWNED = 5


async def new_account(engine: AsyncEngine, user_id: UUID, name: str) -> dict[str, str]:
    """Start another venue from a login that already exists: a new account with the person as its owner. A person can own a handful, so
    the number of accounts cannot be multiplied without a limit."""
    async with transaction(engine, user_id=user_id) as conn:
        owned = (
            await conn.execute(
                text("SELECT count(*) FROM membership WHERE user_id = :u AND role = 'owner'"),
                {"u": user_id},
            )
        ).scalar_one()
        if int(owned) >= MAX_OWNED:
            raise AccountError(
                f"You already own {MAX_OWNED} accounts. Delete one you no longer use before starting another.",
                409,
            )
        tenant_id = (
            await conn.execute(text("SELECT create_tenant(:n, :u)"), {"n": name, "u": user_id})
        ).scalar_one()
    async with transaction(engine, tenant_id=tenant_id, user_id=user_id) as conn:
        await conn.execute(
            text(
                "INSERT INTO audit_log (tenant_id, actor, action, target) VALUES (:t, :a, 'account.create', :t2)"
            ),
            {"t": tenant_id, "a": str(user_id), "t2": str(tenant_id)},
        )
    return {"id": str(tenant_id), "name": name, "role": "owner"}


async def delete_login(engine: AsyncEngine, user_id: UUID, password: str) -> None:
    """Delete the person: their sign-in and their place in every account. Refused while they alone hold up an account."""
    await _check_password(engine, user_id, password)
    try:
        async with transaction(engine, user_id=user_id) as conn:
            sole = (
                await conn.execute(
                    text("SELECT tenant_name FROM sole_owner_of(:u)"), {"u": user_id}
                )
            ).all()
            if sole:
                raise AccountError(_holds_up(sole), 409)
            await conn.execute(text("DELETE FROM app_user WHERE id = :u"), {"u": user_id})
    except DBAPIError as exc:
        if (
            _state(exc) == "P0001"
        ):  # the database's own guard: another owner left between the check and the delete
            raise AccountError(
                "An account would be left without an owner. Try again.", 409
            ) from exc
        raise
