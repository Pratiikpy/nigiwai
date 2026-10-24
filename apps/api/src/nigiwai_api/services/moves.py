"""Moves and their results (PRD M11, M20): what an owner changed, and what the scans in the same slot did around it.

Everything shown is worked out from stored scans each time it is asked for, so it cannot drift from the data and it makes no
Qloo call. The arithmetic and its honesty rules are in `moves_model`.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from nigiwai_tribes import place
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ..db import transaction
from . import hours as hrs
from . import moves_model as mm
from . import tribes

KINDS = ("act", "event", "menu", "ad", "price", "other")
MAX_PAST_DAYS = 366
MAX_FUTURE_DAYS = 60


class MoveError(Exception):
    def __init__(self, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.status = status


def _slot(row: Any) -> mm.Slot:
    return mm.Slot(tuple(int(d) for d in row.weekdays), row.hour_from, row.hour_to)


async def _scans(
    conn: AsyncConnection, business_id: UUID, since: date
) -> list[tuple[date, int, int, int]]:
    """Scans since a date as one row per hour that had any, with how many: the size of the answer is bounded by the days and
    hours in the window, not by how many guests answered."""
    rows = (
        await conn.execute(
            text(
                "SELECT r.local_date AS d, r.local_weekday AS wd, r.local_hour AS hr, count(*) AS n FROM response r"
                " JOIN survey s ON s.id = r.survey_id AND s.version = r.survey_version"
                " WHERE s.business_id = :b AND r.quality_flag = 'ok' AND r.local_date >= :since"
                " GROUP BY r.local_date, r.local_weekday, r.local_hour"
            ),
            {"b": business_id, "since": since},
        )
    ).all()
    return [(r.d, int(r.wd), int(r.hr), int(r.n)) for r in rows]


async def _placed(
    conn: AsyncConnection, business_id: UUID, since: date
) -> tuple[list[tuple[date, int, int, list[float]]], list[tuple[int, str]]] | None:
    """Each scan with where its guest sits among the groups, and the shown groups as (position, label); None when there
    are no groups to place anyone in."""
    prev = await tribes.latest(conn, business_id)
    if prev is None or prev.state not in ("provisional", "named"):
        return None
    result = tribes._from_json(prev.result)
    if result is None:
        return None
    shown = [(k, t.label) for k, t in enumerate(result.tribes) if t.shown]
    if not shown:
        return None
    rows = await tribes._rows(conn, business_id)
    dates = {
        r.rid: r.d
        for r in (
            await conn.execute(
                text(
                    "SELECT r.id::text AS rid, r.local_date AS d FROM response r"
                    " JOIN survey s ON s.id = r.survey_id AND s.version = r.survey_version"
                    " WHERE s.business_id = :b AND r.local_date >= :since"
                ),
                {"b": business_id, "since": since},
            )
        ).all()
    }
    out: list[tuple[date, int, int, list[float]]] = []
    for r in tribes._respondents(rows):
        d = dates.get(r.id)
        if d is None or r.weekday is None or r.hour is None:
            continue
        p = place(result, list(r.picks))
        if p is not None:
            out.append((d, int(r.weekday), int(r.hour), list(p.memberships)))
    return out, shown


def _mix(
    placed: list[tuple[date, int, int, list[float]]],
    shown: list[tuple[int, str]],
    slot: mm.Slot,
    start: date,
    end: date,
) -> dict[str, Any]:
    inside = [
        m
        for d, wd, hr, m in placed
        if start <= d < end and slot.covers_day(wd) and slot.covers_hour(hr)
    ]
    if len(inside) < mm.MIX_MIN:
        return {"scans": len(inside), "shown": False, "groups": []}
    totals = [sum(m[k] for m in inside) for k, _ in shown]
    whole = sum(totals) or 1.0
    groups = [
        {"label": label, "share": round(t / whole, 3)}
        for (_, label), t in sorted(zip(shown, totals, strict=True), key=lambda x: -x[1])
    ]
    return {"scans": len(inside), "shown": True, "groups": groups}


def _open_days(mask: list[list[bool]] | None, slot: mm.Slot) -> set[int] | None:
    if mask is None or not any(any(day) for day in mask):
        return None
    hours = (
        range(24)
        if slot.hour_from is None or slot.hour_to is None
        else range(slot.hour_from, slot.hour_to)
    )
    return {d for d in range(7) if any(mask[d][h] for h in hours)}


def _out(row: Any, result: dict[str, Any]) -> dict[str, Any]:
    slot = _slot(row)
    return {
        "id": str(row.id),
        "kind": row.kind,
        "title": row.title,
        "started_on": row.started_on.isoformat(),
        "ended_on": row.ended_on.isoformat() if row.ended_on else None,
        "source": row.source,
        "note": row.note,
        "slot": {
            "weekdays": [int(d) for d in row.weekdays],
            "from": row.hour_from,
            "to": row.hour_to,
            "text": slot.text(),
        },
        "result": result,
    }


_SELECT = (
    "SELECT id, kind, title, started_on, ended_on, source, note, weekdays, hour_from, hour_to, created_at"
    " FROM move WHERE business_id = :b ORDER BY started_on DESC, created_at DESC"
)


async def listing(
    engine: AsyncEngine, tenant_id: UUID, business_id: UUID, *, today: date | None = None
) -> dict[str, Any] | None:
    today = today or datetime.now(UTC).date()
    async with transaction(engine, tenant_id=tenant_id) as conn:
        biz = (
            await conn.execute(text("SELECT 1 FROM business WHERE id = :b"), {"b": business_id})
        ).first()
        if biz is None:
            return None
        moves = (await conn.execute(text(_SELECT), {"b": business_id})).all()
        loc = (
            await conn.execute(
                text(
                    "SELECT hours FROM location WHERE business_id = :b ORDER BY created_at, id LIMIT 1"
                ),
                {"b": business_id},
            )
        ).first()
        since = min((m.started_on for m in moves), default=today) - timedelta(weeks=mm.WEEKS)
        scans = await _scans(conn, business_id, since) if moves else []
        placed = await _placed(conn, business_id, since) if moves else None
    hours = loc.hours if loc is not None and isinstance(loc.hours, list) else []
    mask = hrs.open_mask(hours) if hours else None
    items: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    for m in moves:
        slot = _slot(m)
        r = mm.evaluate(scans, slot, m.started_on, m.ended_on, today, _open_days(mask, slot))
        if placed is not None:
            (b0, b1), (a0, a1) = mm.periods(m.started_on, m.ended_on, today)
            groups, shown = placed
            r["mix"] = {
                "before": _mix(groups, shown, slot, b0, b1),
                "after": _mix(groups, shown, slot, a0, a1),
            }
        else:
            r["mix"] = None
        items.append(_out(m, r))
        results.append({"kind": m.kind, "verdict": r["verdict"]})
    return {
        "today": today.isoformat(),
        "moves": items,
        "ledger": mm.ledger(results),
        "weeks": mm.WEEKS,
    }


def _check(
    started: date,
    ended: date | None,
    weekdays: list[int],
    hour_from: int | None,
    hour_to: int | None,
    today: date,
) -> None:
    if started < today - timedelta(days=MAX_PAST_DAYS):
        raise MoveError("That start date is more than a year ago. Scans that old are not compared.")
    if started > today + timedelta(days=MAX_FUTURE_DAYS):
        raise MoveError(f"A move can be logged up to {MAX_FUTURE_DAYS} days before it starts.")
    if ended is not None and ended < started:
        raise MoveError("The end date cannot be before the start date.")
    if len(set(weekdays)) != len(weekdays) or any(not 0 <= d <= 6 for d in weekdays):
        raise MoveError("Choose each day of the week once.")
    if (hour_from is None) != (hour_to is None):
        raise MoveError("Give both the first and last hour of the slot, or neither.")
    if hour_from is not None and hour_to is not None and not 0 <= hour_from < hour_to <= 24:
        raise MoveError("The slot must end after it starts, between 00:00 and 24:00.")


async def create(
    engine: AsyncEngine,
    tenant_id: UUID,
    user_id: UUID,
    business_id: UUID,
    *,
    kind: str,
    title: str,
    started_on: date,
    ended_on: date | None,
    weekdays: list[int],
    hour_from: int | None,
    hour_to: int | None,
    note: str | None,
    today: date | None = None,
) -> str:
    _check(started_on, ended_on, weekdays, hour_from, hour_to, today or datetime.now(UTC).date())
    async with transaction(engine, tenant_id=tenant_id, user_id=user_id) as conn:
        if (
            await conn.execute(text("SELECT 1 FROM business WHERE id = :b"), {"b": business_id})
        ).first() is None:
            raise MoveError("not found", 404)
        new = (
            await conn.execute(
                text(
                    "INSERT INTO move (tenant_id, business_id, kind, title, started_on, ended_on, source, weekdays,"
                    " hour_from, hour_to, note, created_by) VALUES (:t, :b, :k, :ti, :s, :e, 'manual',"
                    " CAST(:w AS smallint[]), :hf, :ht, :n, :u) RETURNING id"
                ),
                {
                    "t": tenant_id,
                    "b": business_id,
                    "k": kind,
                    "ti": title,
                    "s": started_on,
                    "e": ended_on,
                    "w": sorted(weekdays),
                    "hf": hour_from,
                    "ht": hour_to,
                    "n": note,
                    "u": user_id,
                },
            )
        ).scalar_one()
        await conn.execute(
            text(
                "INSERT INTO audit_log (tenant_id, actor, action, target) VALUES (:t, :a, 'move.create', :g)"
            ),
            {"t": tenant_id, "a": str(user_id), "g": str(new)},
        )
    return str(new)


async def update(
    engine: AsyncEngine,
    tenant_id: UUID,
    user_id: UUID,
    business_id: UUID,
    move_id: UUID,
    *,
    kind: str,
    title: str,
    started_on: date,
    ended_on: date | None,
    weekdays: list[int],
    hour_from: int | None,
    hour_to: int | None,
    note: str | None,
    today: date | None = None,
) -> None:
    _check(started_on, ended_on, weekdays, hour_from, hour_to, today or datetime.now(UTC).date())
    async with transaction(engine, tenant_id=tenant_id, user_id=user_id) as conn:
        result = await conn.execute(
            text(
                "UPDATE move SET kind = :k, title = :ti, started_on = :s, ended_on = :e, weekdays = CAST(:w AS smallint[]),"
                " hour_from = :hf, hour_to = :ht, note = :n WHERE id = :i AND business_id = :b"
            ),
            {
                "k": kind,
                "ti": title,
                "s": started_on,
                "e": ended_on,
                "w": sorted(weekdays),
                "hf": hour_from,
                "ht": hour_to,
                "n": note,
                "i": move_id,
                "b": business_id,
            },
        )
        if result.rowcount == 0:
            raise MoveError("not found", 404)
        await conn.execute(
            text(
                "INSERT INTO audit_log (tenant_id, actor, action, target) VALUES (:t, :a, 'move.update', :g)"
            ),
            {"t": tenant_id, "a": str(user_id), "g": str(move_id)},
        )


async def delete(
    engine: AsyncEngine, tenant_id: UUID, user_id: UUID, business_id: UUID, move_id: UUID
) -> None:
    async with transaction(engine, tenant_id=tenant_id, user_id=user_id) as conn:
        result = await conn.execute(
            text("DELETE FROM move WHERE id = :i AND business_id = :b"),
            {"i": move_id, "b": business_id},
        )
        if result.rowcount == 0:
            raise MoveError("not found", 404)
        await conn.execute(
            text(
                "INSERT INTO audit_log (tenant_id, actor, action, target) VALUES (:t, :a, 'move.delete', :g)"
            ),
            {"t": tenant_id, "a": str(user_id), "g": str(move_id)},
        )
