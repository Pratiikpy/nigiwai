"""Drafts (PRD M17, M10): outreach, event page, post and ad-angle text prepared from stored facts, reviewed and approved by
the owner. Nothing is sent, posted or booked here, and every step is written to the audit log (what, who, when). The text and
its rules are in `drafts_model`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ..db import transaction
from . import drafts_model as dm
from . import moves_model as mm
from . import soundcheck, today

ACTION_KINDS = ("outreach", "event_page", "social_post")
MAX_PER_BUSINESS = 200


class DraftError(Exception):
    def __init__(self, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.status = status


def _reward_words(title: str | None) -> str | None:
    if not title:
        return None
    t = title.strip()
    return t if t[:2].isupper() else t[:1].lower() + t[1:]


async def _venue(conn: AsyncConnection, business_id: UUID) -> Any:
    return (
        await conn.execute(
            text(
                "SELECT b.name AS name, l.address AS address, l.capacity AS capacity,"
                " (SELECT s.reward->>'title' FROM survey s WHERE s.business_id = b.id AND s.status = 'published'"
                "  ORDER BY s.version DESC LIMIT 1) AS reward"
                " FROM business b LEFT JOIN LATERAL"
                " (SELECT * FROM location WHERE business_id = b.id ORDER BY created_at, id LIMIT 1) l ON true"
                " WHERE b.id = :b"
            ),
            {"b": business_id},
        )
    ).first()


async def _groups(engine: AsyncEngine, tenant_id: UUID, business_id: UUID) -> list[dict[str, Any]]:
    try:
        basis = await soundcheck.load_basis(engine, tenant_id, business_id)
    except soundcheck.SoundcheckError:
        return []
    return [{"index": g.index, "label": g.label, "loves": list(g.seed_names)} for g in basis.groups]


async def sources(engine: AsyncEngine, tenant_id: UUID, business_id: UUID) -> dict[str, Any]:
    """What a draft can be made from right now: this week's accepted Today actions, and the crowd's groups."""
    board = await today.build(engine, tenant_id, business_id)
    actions = [
        {"key": a["key"], "title": a["title"], "act": a["act"]["name"]}
        for a in (board or {}).get("actions", [])
        if a.get("decision") == "accepted" and a.get("act")
    ]
    return {"actions": actions, "groups": await _groups(engine, tenant_id, business_id)}


def _slot_text(slot: dict[str, Any] | None) -> str | None:
    if not slot:
        return None
    return mm.Slot(
        tuple(int(d) for d in slot.get("weekdays", [])), slot.get("from"), slot.get("to")
    ).text()


async def _facts_for_action(
    engine: AsyncEngine, tenant_id: UUID, business_id: UUID, venue: Any, key: str
) -> dm.Facts:
    board = await today.build(engine, tenant_id, business_id)
    action = next((a for a in (board or {}).get("actions", []) if a["key"] == key), None)
    if action is None or not action.get("act"):
        raise DraftError("That action is not on this week's board.", 404)
    if action.get("decision") != "accepted":
        raise DraftError("Accept the action on Today first, then prepare drafts for it.", 409)
    best: str | None = None
    sc_id = action["act"].get("soundcheck_id")
    if sc_id:
        doc = await soundcheck.get(engine, tenant_id, business_id, UUID(str(sc_id)))
        group = soundcheck._best_group(doc) if doc else None
        best = group["label"] if group else None
    loves: tuple[str, ...] = ()
    if best:
        for g in await _groups(engine, tenant_id, business_id):
            if g["label"] == best:
                loves = tuple(g["loves"])
    return dm.Facts(
        venue=venue.name,
        area=venue.address,
        act=action["act"]["name"],
        slot=_slot_text(action.get("slot")),
        group=best,
        loves=loves,
        capacity=venue.capacity,
        reward=_reward_words(venue.reward),
    )


async def _facts_for_group(
    engine: AsyncEngine, tenant_id: UUID, business_id: UUID, venue: Any, index: int
) -> dm.Facts:
    group = next(
        (g for g in await _groups(engine, tenant_id, business_id) if g["index"] == index), None
    )
    if group is None:
        raise DraftError("That group is not in your crowd.", 404)
    if not group["loves"]:
        raise DraftError(
            "Nothing is known about what this group picks, so there is nothing to write from.", 409
        )
    return dm.Facts(
        venue=venue.name,
        area=venue.address,
        act=None,
        slot=None,
        group=group["label"],
        loves=tuple(group["loves"]),
        capacity=venue.capacity,
        reward=_reward_words(venue.reward),
    )


def _out(row: Any) -> dict[str, Any]:
    why = dm.approvable(row.body) if row.status == "draft" else None
    return {
        "id": str(row.id),
        "kind": row.kind,
        "subject": row.subject,
        "body": row.body,
        "status": row.status,
        "facts": row.facts,
        "source_key": row.source_key,
        "created_at": row.created_at.isoformat(),
        "edited_at": row.edited_at.isoformat() if row.edited_at else None,
        "decided_at": row.decided_at.isoformat() if row.decided_at else None,
        "gaps": dm.placeholders(row.body),
        "can_approve": row.status == "draft" and why is None,
        "why_not": why,
        "mailto": dm.mailto(row.subject, row.body)
        if row.status == "approved" and row.kind == "outreach"
        else None,
    }


_COLUMNS = "id, kind, subject, body, status, facts, source_key, created_at, edited_at, decided_at"
_SELECT_ALL = f"SELECT {_COLUMNS} FROM draft WHERE business_id = :b ORDER BY created_at DESC, id"  # noqa: S608
_SELECT_ONE = f"SELECT {_COLUMNS} FROM draft WHERE id = :i AND business_id = :b"  # noqa: S608


async def _audit(
    conn: AsyncConnection, tenant_id: UUID, user_id: UUID, action: str, draft_id: UUID | str
) -> None:
    await conn.execute(
        text("INSERT INTO audit_log (tenant_id, actor, action, target) VALUES (:t, :a, :x, :g)"),
        {"t": tenant_id, "a": str(user_id), "x": action, "g": str(draft_id)},
    )


async def listing(engine: AsyncEngine, tenant_id: UUID, business_id: UUID) -> dict[str, Any] | None:
    async with transaction(engine, tenant_id=tenant_id) as conn:
        if (await _venue(conn, business_id)) is None:
            return None
        rows = (await conn.execute(text(_SELECT_ALL), {"b": business_id})).all()
    return {
        "drafts": [_out(r) for r in rows],
        "sources": await sources(engine, tenant_id, business_id),
    }


async def create(
    engine: AsyncEngine,
    tenant_id: UUID,
    user_id: UUID,
    business_id: UUID,
    *,
    from_action: str | None,
    group_index: int | None,
) -> list[str]:
    """Prepare drafts from an accepted Today action (outreach, event page, post) or an ad angle for one group."""
    if (from_action is None) == (group_index is None):
        raise DraftError("Choose an accepted action, or a group, to draft from.")
    async with transaction(engine, tenant_id=tenant_id) as conn:
        venue = await _venue(conn, business_id)
        count = (
            await conn.execute(
                text("SELECT count(*) FROM draft WHERE business_id = :b"), {"b": business_id}
            )
        ).scalar_one()
    if venue is None:
        raise DraftError("not found", 404)
    if count >= MAX_PER_BUSINESS:
        raise DraftError(
            f"You have {MAX_PER_BUSINESS} drafts. Delete some before making more.", 409
        )
    if from_action is not None:
        facts = await _facts_for_action(engine, tenant_id, business_id, venue, from_action)
        kinds: tuple[str, ...] = ACTION_KINDS
    else:
        assert group_index is not None
        facts = await _facts_for_group(engine, tenant_id, business_id, venue, group_index)
        kinds = ("ad_copy",)
    made: list[str] = []
    async with transaction(engine, tenant_id=tenant_id, user_id=user_id) as conn:
        for kind in kinds:
            d = dm.build(kind, facts)
            new = (
                await conn.execute(
                    text(
                        "INSERT INTO draft (tenant_id, business_id, kind, subject, body, facts, source_key, created_by)"
                        " VALUES (:t, :b, :k, :s, :bo, CAST(:f AS jsonb), :sk, :u) RETURNING id"
                    ),
                    {
                        "t": tenant_id,
                        "b": business_id,
                        "k": d["kind"],
                        "s": d["subject"][:200],
                        "bo": d["body"],
                        "f": json.dumps(dm.facts_json(facts)),
                        "sk": from_action,
                        "u": user_id,
                    },
                )
            ).scalar_one()
            await _audit(conn, tenant_id, user_id, "draft.create", new)
            made.append(str(new))
    return made


async def _get(
    conn: AsyncConnection, business_id: UUID, draft_id: UUID, *, lock: bool = False
) -> Any:
    sql = _SELECT_ONE + (" FOR UPDATE" if lock else "")
    row = (await conn.execute(text(sql), {"i": draft_id, "b": business_id})).first()
    if row is None:
        raise DraftError("not found", 404)
    return row


async def get(
    engine: AsyncEngine, tenant_id: UUID, business_id: UUID, draft_id: UUID
) -> dict[str, Any]:
    async with transaction(engine, tenant_id=tenant_id) as conn:
        return _out(await _get(conn, business_id, draft_id))


async def update(
    engine: AsyncEngine,
    tenant_id: UUID,
    user_id: UUID,
    business_id: UUID,
    draft_id: UUID,
    *,
    subject: str,
    body: str,
) -> dict[str, Any]:
    """Edit the text. An approved draft goes back to draft: the approval was of the words that were there."""
    async with transaction(engine, tenant_id=tenant_id, user_id=user_id) as conn:
        row = await _get(conn, business_id, draft_id, lock=True)
        if row.status == "withdrawn":
            raise DraftError("A withdrawn draft cannot be edited. Make a new one instead.", 409)
        if body == row.body and subject == row.subject:
            return _out(row)
        await conn.execute(
            text(
                "UPDATE draft SET subject = :s, body = :b, status = 'draft', edited_at = :n, decided_by = NULL,"
                " decided_at = NULL WHERE id = :i"
            ),
            {"s": subject, "b": body, "n": datetime.now(UTC), "i": draft_id},
        )
        await _audit(conn, tenant_id, user_id, "draft.edit", draft_id)
        return _out(await _get(conn, business_id, draft_id))


async def approve(
    engine: AsyncEngine, tenant_id: UUID, user_id: UUID, business_id: UUID, draft_id: UUID
) -> dict[str, Any]:
    async with transaction(engine, tenant_id=tenant_id, user_id=user_id) as conn:
        row = await _get(conn, business_id, draft_id, lock=True)
        if row.status != "draft":
            raise DraftError("Only a draft can be approved.", 409)
        why = dm.approvable(row.body)
        if why:
            raise DraftError(why, 409)
        await conn.execute(
            text(
                "UPDATE draft SET status = 'approved', decided_by = :u, decided_at = now() WHERE id = :i"
            ),
            {"u": user_id, "i": draft_id},
        )
        await _audit(conn, tenant_id, user_id, "draft.approve", draft_id)
        return _out(await _get(conn, business_id, draft_id))


async def withdraw(
    engine: AsyncEngine, tenant_id: UUID, user_id: UUID, business_id: UUID, draft_id: UUID
) -> dict[str, Any]:
    async with transaction(engine, tenant_id=tenant_id, user_id=user_id) as conn:
        row = await _get(conn, business_id, draft_id, lock=True)
        if row.status == "withdrawn":
            return _out(row)
        await conn.execute(
            text(
                "UPDATE draft SET status = 'withdrawn', decided_by = :u, decided_at = now() WHERE id = :i"
            ),
            {"u": user_id, "i": draft_id},
        )
        await _audit(conn, tenant_id, user_id, "draft.withdraw", draft_id)
        return _out(await _get(conn, business_id, draft_id))


async def delete(
    engine: AsyncEngine, tenant_id: UUID, user_id: UUID, business_id: UUID, draft_id: UUID
) -> None:
    async with transaction(engine, tenant_id=tenant_id, user_id=user_id) as conn:
        await _get(conn, business_id, draft_id, lock=True)
        await conn.execute(text("DELETE FROM draft WHERE id = :i"), {"i": draft_id})
        await _audit(conn, tenant_id, user_id, "draft.delete", draft_id)
