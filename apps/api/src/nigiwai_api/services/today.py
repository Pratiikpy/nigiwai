"""The Today board (PRD M5): up to three things to do this week, each with its reason, its evidence and a label on every
line, plus the venue's quietest hours.

Everything is computed from what is already stored (scans, opening hours, the crowd's groups and the suggested acts with
their Soundchecks), so opening the board costs no Qloo call and can never disagree with the screens it summarises. Only
the owner's decision about each action is kept (accepted or dismissed, per week), and an accepted action can be logged
as a move. Too little data produces "not enough data yet" and what would unlock it, never a guess.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from ..db import transaction
from . import hours as hrs
from . import soundcheck

HOURS_PICTURE_FROM = 10  # scans before the hours picture is drawn at all
SPARSE_BELOW = 10  # a stretch with fewer scans than this cannot say who comes
PROVISIONAL_GROUPS_FROM = 60
NAMED_GROUPS_FROM = 200
MUSIC_TYPES = ("live_music_venue", "bar", "festival", "promoter", "brewery", "hotel_bar")


class TodayError(Exception):
    def __init__(self, message: str, status: int = 404) -> None:
        super().__init__(message)
        self.status = status


def week_of(day: date) -> str:
    iso = day.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def daypart(hour: int) -> str:
    if hour < 5:
        return "late night"
    if hour < 12:
        return "morning"
    if hour < 17:
        return "afternoon"
    if hour < 22:
        return "evening"
    return "late night"


def unlock_for(scans: int) -> dict[str, Any] | None:
    """The next thing more scans would unlock, as a meter."""
    steps = (
        (HOURS_PICTURE_FROM, "Your first quiet-hours picture at 10 scans"),
        (hrs.MIN_SCANS_FOR_WINDOWS, "Your quietest hours named from 20 scans"),
        (PROVISIONAL_GROUPS_FROM, "Groups appear from 60 scans"),
        (NAMED_GROUPS_FROM, "Named groups unlock at 200 scans"),
    )
    for need, title in steps:
        if scans < need:
            more = need - scans
            return {
                "title": title,
                "v": scans,
                "max": need,
                "text": f"{more} more {'scan' if more == 1 else 'scans'}. Until then Nigiwai shows nothing here rather than guess.",
            }
    return None


async def _scans(conn: Any, business_id: UUID) -> list[Any]:
    return list(
        (
            await conn.execute(
                text(
                    "SELECT r.local_weekday AS wd, r.local_hour AS hr, r.local_date AS day FROM response r"
                    " JOIN survey s ON s.id = r.survey_id AND s.version = r.survey_version"
                    " WHERE s.business_id = :b AND r.quality_flag = 'ok'"
                ),
                {"b": business_id},
            )
        ).all()
    )


def _fit(doc: dict[str, Any], soundcheck_id: str) -> dict[str, Any]:
    return {
        "soundcheck_id": soundcheck_id,
        "score": doc.get("score"),
        "band": doc.get("band"),
        "provisional": bool(doc.get("provisional")),
        "groups": [
            {"label": g["label"], "share": g["share"], "fit": g["fit"]}
            for g in doc.get("groups", [])
            if g.get("status") == "scored"
        ],
    }


def _evidence(label: str, body: str, note: str | None = None) -> dict[str, Any]:
    return {"label": label, "text": body, "note": note}


def _fill_action(
    window: hrs.Window, total: int, act: dict[str, Any], fit: dict[str, Any] | None, music: bool
) -> dict[str, Any]:
    when = hrs.describe(window)
    best = act.get("best_for")
    title = f"Try {act['name']} on {hrs.WEEKDAYS[window.weekday]} {window.start:02d}:00 to {window.end:02d}:00"
    why = f"{when} is your quietest stretch. " + (
        f"An act that fits {best}, your crowd's best-matching group, could give it a reason to come."
        if best
        else "An act your crowd's groups should like could give it a reason to come."
    )
    evidence = [
        _evidence(
            "measured",
            f"{window.scans} of {total} scans came on {when}, well below an average three-hour stretch.",
            "Scans are guests who chose to answer, not a headcount.",
        ),
        _evidence(
            "modelled",
            f"{act['name']} scores {act['score']} out of 100 for your crowd"
            + (f" and fits {best} best." if best else "."),
            "Fit, not a sales forecast. The working is on Soundcheck.",
        ),
        _evidence(
            "observed", f"{act['name']} is a real act in Qloo's graph, not an invented name."
        ),
    ]
    if not music:
        evidence.append(
            _evidence(
                "modelled",
                "Played in the room rather than booked: Qloo recommends at artist level, not by song.",
            )
        )
    return {
        "key": f"fill:{window.weekday}:{window.start}:{act['entity_id']}",
        "kind": "Fill an empty chair",
        "icon": "clock",
        "title": title,
        "why": why,
        "evidence": evidence,
        "fit": fit,
        "prov": [f"n = {total} scans", "Your scans and Qloo's artist graph"],
        "act": {
            "name": act["name"],
            "entity_id": act["entity_id"],
            "soundcheck_id": act.get("soundcheck_id"),
        },
        "slot": {"weekdays": [window.weekday], "from": window.start, "to": window.end},
    }


def _book_slot(
    busy: list[hrs.Window], in_hours: int, nights: list[int], lineup_weekday: list[float] | None
) -> dict[str, Any] | None:
    """When an act would be booked for: the busiest stretch in the scans if there are enough to say, else the owner's
    own show night, else the day the room's public lineups skew to. None if none of them says anything."""
    if busy:
        w = busy[0]
        return {
            "when": f"{hrs.WEEKDAYS[w.weekday]} {daypart(w.start)}",
            "key": f"{w.weekday}:{w.start}",
            "reason": "is where your scans cluster",
            "measured": f"{w.scans} of {in_hours} scans came on {hrs.describe(w)}, your busiest stretch.",
            "window": {"weekdays": [w.weekday], "from": w.start, "to": w.end},
        }
    if nights:
        return {
            "when": f"{hrs.WEEKDAYS[nights[0]]} evening",
            "key": f"{nights[0]}",
            "reason": "is one of the nights you hold shows",
            "measured": None,
            "window": {"weekdays": [nights[0]], "from": 17, "to": 22},
        }
    if lineup_weekday and len(lineup_weekday) == 7 and max(lineup_weekday) > 0:
        day = max(range(7), key=lambda d: lineup_weekday[d])
        return {
            "when": f"{hrs.WEEKDAYS[day]} evening",
            "key": f"{day}",
            "reason": "is the day your past public lineups skew to",
            "measured": None,
            "window": {"weekdays": [day], "from": 17, "to": 22},
        }
    return None


def _book_action(
    slot: dict[str, Any], basis_note: str, act: dict[str, Any], fit: dict[str, Any] | None
) -> dict[str, Any]:
    when, key_when, measured = slot["when"], slot["key"], slot["measured"]
    best = act.get("best_for")
    evidence = []
    if measured:
        evidence.append(
            _evidence(
                "measured", measured, "Scans are guests who chose to answer, not a headcount."
            )
        )
    evidence.append(
        _evidence(
            "modelled",
            f"{act['name']} scores {act['score']} out of 100 for your crowd"
            + (f" and fits {best} best." if best else "."),
            basis_note,
        )
    )
    evidence.append(
        _evidence(
            "observed",
            f"{act['name']} is a real act in Qloo's graph.",
            "Qloo has no event listings, so dates and availability are not checked.",
        )
    )
    return {
        "key": f"book:{key_when}:{act['entity_id']}",
        "kind": "Book an act",
        "icon": "music",
        "title": f"Book {act['name']} for {when}",
        "why": (
            f"{when.capitalize()} {slot['reason']}"
            + (f", and {act['name']} sits close to what {best} loves." if best else ".")
        ),
        "evidence": evidence,
        "fit": fit,
        "prov": ["Your crowd's groups and Qloo's artist graph"],
        "act": {
            "name": act["name"],
            "entity_id": act["entity_id"],
            "soundcheck_id": act.get("soundcheck_id"),
        },
        "slot": slot["window"],
    }


async def build(
    engine: AsyncEngine, tenant_id: UUID, business_id: UUID, *, now: datetime | None = None
) -> dict[str, Any] | None:
    async with transaction(engine, tenant_id=tenant_id) as conn:
        venue = (
            await conn.execute(
                text(
                    "SELECT b.name AS business, b.type AS type, l.timezone AS tz, l.hours AS hours, l.show_nights AS nights"
                    " FROM business b LEFT JOIN LATERAL"
                    " (SELECT * FROM location WHERE business_id = b.id ORDER BY created_at, id LIMIT 1) l ON true"
                    " WHERE b.id = :b"
                ),
                {"b": business_id},
            )
        ).first()
        if venue is None:
            return None
        scans = await _scans(conn, business_id)
        sug_row = (
            await conn.execute(
                text(
                    "SELECT status, basis_kind, basis_ref, result FROM act_suggestion WHERE business_id = :b"
                ),
                {"b": business_id},
            )
        ).first()
    try:
        tz = ZoneInfo(venue.tz or "UTC")
    except Exception:
        tz = ZoneInfo("UTC")
    local_now = (now or datetime.now(UTC)).astimezone(tz)
    week = week_of(local_now.date())

    music = venue.type in MUSIC_TYPES
    total = len(scans)
    hours_set: list[dict[str, str] | None] = (
        list(venue.hours) if isinstance(venue.hours, list) else []
    )
    mask = hrs.open_mask(hours_set)
    cells = hrs.scan_grid([(int(s.wd), int(s.hr)) for s in scans], mask)
    drawn = hrs.span(mask)
    in_hours = sum(c or 0 for row in cells for c in row)
    quiet = hrs.quiet_windows(cells, in_hours)
    busy = hrs.busy_windows(cells, in_hours)
    sparse = hrs.sparse_windows(cells, SPARSE_BELOW) if total >= HOURS_PICTURE_FROM else []

    basis = await soundcheck.basis_status(engine, tenant_id, business_id)
    suggestions: dict[str, Any] | None = None
    stale = False
    lineup_weekday: list[float] | None = None
    if basis.get("use") is not None:
        try:
            loaded = await soundcheck.load_basis(engine, tenant_id, business_id)
        except soundcheck.SoundcheckError:
            loaded = None
        if loaded is not None:
            lineup_weekday = (
                [float(x) for x in loaded.venue_weekday] if loaded.venue_weekday else None
            )
            if sug_row is not None:
                stale = sug_row.basis_kind != loaded.kind or sug_row.basis_ref != loaded.ref
    if sug_row is not None and sug_row.status == "ready" and sug_row.result:
        suggestions = dict(sug_row.result)
    top: list[dict[str, Any]] = list(suggestions.get("top", [])) if suggestions else []
    verdicts: dict[str, dict[str, Any]] = {}
    ids = [UUID(t["soundcheck_id"]) for t in top if t.get("soundcheck_id")]
    if ids:
        async with transaction(engine, tenant_id=tenant_id) as conn:
            for row in (
                await conn.execute(
                    text(
                        "SELECT id, result FROM soundcheck WHERE id = ANY(:i) AND business_id = :b"
                    ),
                    {"i": ids, "b": business_id},
                )
            ).all():
                verdicts[str(row.id)] = dict(row.result)

    def fit_of(act: dict[str, Any]) -> dict[str, Any] | None:
        sid = act.get("soundcheck_id")
        return _fit(verdicts[sid], sid) if sid and sid in verdicts else None

    actions: list[dict[str, Any]] = []
    used: set[str] = set()
    if quiet and top:
        act = top[0]
        used.add(act["entity_id"])
        actions.append(_fill_action(quiet[0], in_hours, act, fit_of(act), music))
    book_note = (
        "Modelled from public lineups, not from your guests, so provisional."
        if basis.get("use") == "lineup"
        else "Modelled from your guests' groups."
    )
    rest = [t for t in top if t["entity_id"] not in used]
    if rest and basis.get("use") is not None:
        slot = _book_slot(busy, in_hours, [int(n) for n in (venue.nights or [])], lineup_weekday)
        if slot is not None:
            actions.append(_book_action(slot, book_note, rest[0], fit_of(rest[0])))

    hold: dict[str, Any] | None = None
    if sparse:
        w = sparse[0]
        more = SPARSE_BELOW - w.scans
        hold = {
            "title": f"What do {hrs.WEEKDAYS[w.weekday]} {daypart(w.start)} guests pick?",
            "scans": w.scans,
            "need": SPARSE_BELOW,
            "why": (
                f"Only {w.scans} scans came on {hrs.describe(w)}. Nigiwai shows a group only when {SPARSE_BELOW} or more "
                "people are in it, so nothing is shown here rather than a guess."
            ),
            "unlock": [
                f"{more} more {hrs.WEEKDAYS[w.weekday]} {daypart(w.start)} {'scan' if more == 1 else 'scans'}.",
                "A table tent where people sit at that time is the quickest way to get them.",
            ],
        }

    unlock = unlock_for(total)
    if total == 0 and basis.get("use") is None:
        state = "day0"
    elif not actions:
        state = "thin"
    else:
        state = "ready"

    decided: dict[str, str] = {}
    logged: set[str] = set()
    async with transaction(engine, tenant_id=tenant_id) as conn:
        for row in (
            await conn.execute(
                text(
                    "SELECT action_key, state FROM board_decision WHERE business_id = :b AND week = :w"
                ),
                {"b": business_id, "w": week},
            )
        ).all():
            decided[row.action_key] = row.state
        for row in (
            await conn.execute(
                text("SELECT source_key FROM move WHERE business_id = :b AND source = 'today'"),
                {"b": business_id},
            )
        ).all():
            logged.add(row.source_key)
    for a in actions:
        a["decision"] = decided.get(a["key"])
        a["logged"] = a["key"] in logged

    days = sorted({s.day for s in scans})
    last_days = (local_now.date() - days[-1]).days if days else None
    return {
        "week": week,
        "generated_at": local_now.isoformat(),
        "state": state,
        "venue": {"business": venue.business, "type": venue.type, "music": music},
        "status": {
            "scans": total,
            "since": days[0].isoformat() if days else None,
            "last_scan_days": last_days,
            "basis": basis.get("use"),
            "unlock": unlock,
        },
        "hours": {
            "set": bool(drawn),
            "from": drawn[0] if drawn else None,
            "to": drawn[1] if drawn else None,
            "cells": [row[drawn[0] : drawn[1]] for row in cells] if drawn else [],
            "scans_in_hours": in_hours,
            "early": total >= HOURS_PICTURE_FROM and in_hours < hrs.MIN_SCANS_FOR_WINDOWS,
            "picture": bool(drawn) and total >= HOURS_PICTURE_FROM,
            "quiet": [{**hrs.window_json(w), "text": hrs.describe(w)} for w in quiet],
        },
        "actions": actions,
        "hold": hold,
        "notes": (
            [
                "The suggested acts were scored against an earlier version of your crowd. Suggest again on Soundcheck."
            ]
            if stale
            else []
        ),
        "labels": {"hours": ["measured"], "actions": ["measured", "modelled", "observed"]},
    }


async def decide(
    engine: AsyncEngine,
    tenant_id: UUID,
    user_id: UUID,
    business_id: UUID,
    key: str,
    state: str | None,
) -> dict[str, Any]:
    """Accept or dismiss an action on this week's board, or undo (state None). An unknown key is refused: only an action
    the board is showing can be decided."""
    board = await build(engine, tenant_id, business_id)
    if board is None:
        raise TodayError("not found")
    if key not in {a["key"] for a in board["actions"]}:
        raise TodayError("That action is not on this week's board.", 404)
    async with transaction(engine, tenant_id=tenant_id, user_id=user_id) as conn:
        if state is None:
            await conn.execute(
                text(
                    "DELETE FROM board_decision WHERE business_id = :b AND week = :w AND action_key = :k"
                ),
                {"b": business_id, "w": board["week"], "k": key},
            )
        else:
            await conn.execute(
                text(
                    "INSERT INTO board_decision (tenant_id, business_id, week, action_key, state, decided_by)"
                    " VALUES (:t, :b, :w, :k, :s, :u)"
                    " ON CONFLICT (business_id, week, action_key)"
                    " DO UPDATE SET state = EXCLUDED.state, decided_by = EXCLUDED.decided_by, decided_at = now()"
                ),
                {
                    "t": tenant_id,
                    "b": business_id,
                    "w": board["week"],
                    "k": key,
                    "s": state,
                    "u": user_id,
                },
            )
    return {"key": key, "state": state}


async def log_move(
    engine: AsyncEngine, tenant_id: UUID, user_id: UUID, business_id: UUID, key: str
) -> dict[str, Any]:
    """Log an accepted action as a move. Only an accepted action can be logged, once."""
    board = await build(engine, tenant_id, business_id)
    if board is None:
        raise TodayError("not found")
    action = next((a for a in board["actions"] if a["key"] == key), None)
    if action is None:
        raise TodayError("That action is not on this week's board.", 404)
    if action["decision"] != "accepted":
        raise TodayError("Accept the action first, then log it as a move.", 409)
    started = datetime.fromisoformat(board["generated_at"]).date()
    slot_window = action.get("slot")
    async with transaction(engine, tenant_id=tenant_id, user_id=user_id) as conn:
        row = (
            await conn.execute(
                text(
                    "INSERT INTO move (tenant_id, business_id, kind, title, started_on, source, source_key, created_by,"
                    " weekdays, hour_from, hour_to) VALUES (:t, :b, 'act', :ti, :d, 'today', :k, :u,"
                    " CAST(:w AS smallint[]), :hf, :ht)"
                    " ON CONFLICT (business_id, source, source_key) DO NOTHING RETURNING id"
                ),
                {
                    "t": tenant_id,
                    "b": business_id,
                    "ti": action["title"][:160],
                    "d": started,
                    "k": key,
                    "u": user_id,
                    "w": list(slot_window.get("weekdays", [])) if slot_window else [],
                    "hf": slot_window.get("from") if slot_window else None,
                    "ht": slot_window.get("to") if slot_window else None,
                },
            )
        ).first()
    return {"key": key, "logged": True, "new": row is not None}
