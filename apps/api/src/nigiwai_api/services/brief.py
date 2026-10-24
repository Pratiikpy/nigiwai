"""The Booking Brief (PRD M22): one page an owner can forward to a booker or a partner.

The document is built from what is already stored (the crowd's groups, the suggested acts and their Soundchecks), so it
costs no Qloo call and can never disagree with the screens it summarises. It holds item names and our own scores only,
never a raw Qloo response, and every figure carries its label. A crowd or a Soundcheck that is too thin says "not enough
data yet" instead of showing a number. The page, the PDF and the shared link are all drawn from this one document.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import numpy as np
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from ..db import transaction
from ..security import new_token, token_hash
from . import soundcheck, tribes

SHARE_DAYS = 30
TITLE = "Who to book next, for the crowd you actually have"
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
PARTS = [
    ("mornings", range(6, 12)),
    ("afternoons", range(12, 17)),
    ("evenings", range(17, 22)),
    ("late nights", [22, 23, 0, 1, 2, 3, 4, 5]),
]


def day_list(days: list[int]) -> str:
    names = [DAYS[d] for d in days]
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def _runs(days: list[int]) -> list[tuple[int, int]]:
    """Consecutive weekdays as (first, last) runs, Monday first, without wrapping Sunday into Monday."""
    out: list[tuple[int, int]] = []
    for d in sorted(days):
        if out and d == out[-1][1] + 1:
            out[-1] = (out[-1][0], d)
        else:
            out.append((d, d))
    return out


def describe_when(rhythm: list[list[float]], minimum: float = 10.0) -> str | None:
    """Where a group's scans cluster, in words: the days well above an even spread and the part of the day that
    dominates. None when there are too few scans to say."""
    if len(rhythm) != 7 or any(len(r) != 24 for r in rhythm):
        return None
    total = sum(sum(r) for r in rhythm)
    if total < minimum:
        return None
    day_total = [sum(r) for r in rhythm]
    busy = [d for d, t in enumerate(day_total) if t / total >= 1.25 / 7]
    parts = [
        (name, sum(sum(rhythm[d][h] for h in hours) for d in range(7)) / total)
        for name, hours in PARTS
    ]
    lead = max(parts, key=lambda p: p[1])
    bits: list[str] = []
    if busy and len(busy) < 7:
        runs = [DAYS[a] if a == b else f"{DAYS[a]} to {DAYS[b]}" for a, b in _runs(busy)]
        bits.append("Skews to " + " and ".join(runs))
    if lead[1] >= 0.45:
        bits.append(f"mostly {lead[0]}")
    return ", ".join(bits) if bits else "Spread across the week"


def _pct(x: float) -> int:
    return round(100 * x)


async def _venue(conn: Any, business_id: UUID) -> Any:
    return (
        await conn.execute(
            text(
                "SELECT b.name AS business, l.name AS place, l.timezone, l.capacity, l.curfew FROM business b"
                " LEFT JOIN LATERAL (SELECT * FROM location WHERE business_id = b.id ORDER BY created_at, id LIMIT 1) l"
                " ON true WHERE b.id = :b"
            ),
            {"b": business_id},
        )
    ).first()


async def build(engine: AsyncEngine, tenant_id: UUID, business_id: UUID) -> dict[str, Any] | None:
    async with transaction(engine, tenant_id=tenant_id) as conn:
        venue = await _venue(conn, business_id)
        if venue is None:
            return None
        prev = await tribes.latest(conn, business_id)
        sug_row = (
            await conn.execute(
                text(
                    "SELECT status, basis_kind, basis_ref, result FROM act_suggestion WHERE business_id = :b"
                ),
                {"b": business_id},
            )
        ).first()
    sug: dict[str, Any] | None = dict(sug_row._mapping) if sug_row is not None else None
    status = await soundcheck.basis_status(engine, tenant_id, business_id)
    try:
        tz = ZoneInfo(venue.timezone or "UTC")
    except Exception:
        tz = ZoneInfo("UTC")
    doc: dict[str, Any] = {
        "title": TITLE,
        "venue": {"business": venue.business, "place": venue.place},
        "date": datetime.now(tz).date().isoformat(),
        "status": "thin",
        "reason": "",
        "basis": None,
        "groups": [],
        "acts": [],
        "wildcard": None,
        "nights": None,
        "notes": [],
        "labels": {"crowd": ["measured", "modelled"], "acts": ["modelled"], "nights": ["modelled"]},
        "how": "",
    }
    if status["use"] is None:
        doc["reason"] = (
            "There is no crowd yet. Collect 60 guests with your poster, or start from public lineups, "
            "then Soundcheck some acts."
        )
        return doc

    basis = await soundcheck.load_basis(engine, tenant_id, business_id)
    if basis.kind == "guests" and prev is not None:
        result = tribes._from_json(prev.result)
        by_index = {t.index: t for t in (result.tribes if result else [])}
        doc["basis"] = {
            "kind": "guests",
            "label": basis.label,
            "provisional": basis.crowd.provisional,
            "n": basis.crowd.n,
            "unit": "guests",
        }
        for g in basis.groups:
            card = by_index.get(g.index)
            doc["groups"].append(
                {
                    "label": g.label,
                    "share": _pct(g.share),
                    "size": round(g.size),
                    "when": describe_when(card.rhythm) if card else None,
                }
            )
        if basis.crowd.provisional:
            doc["notes"].append("Groups are working names until 200 guests have answered.")
    else:
        doc["basis"] = {
            "kind": "lineup",
            "label": basis.label,
            "provisional": True,
            "n": basis.crowd.n,
            "unit": "events",
        }
        wd = basis.venue_weekday
        when = None
        if wd:
            busy = [d for d, w in enumerate(wd) if w >= 1.25 / 7]
            when = (
                "Past events skew to "
                + " and ".join(
                    DAYS[a] if a == b else f"{DAYS[a]} to {DAYS[b]}" for a, b in _runs(busy)
                )
                if busy and len(busy) < 7
                else None
            )
        for g in basis.groups:
            doc["groups"].append(
                {"label": g.label, "share": _pct(g.share), "size": round(g.size), "when": when}
            )
        doc["notes"].append(
            "Modelled from public lineups (MusicBrainz, public domain), not from your own guests. "
            "It will be replaced as your guests answer."
        )

    if sug is None or sug["status"] != "ready" or not sug["result"]:
        doc["reason"] = (
            "Soundcheck has not suggested acts yet. Open Soundcheck, then come back."
            if sug is None or sug["status"] in ("queued", "running")
            else "Soundcheck could not suggest acts for this crowd."
        )
        return doc
    if sug["basis_kind"] != basis.kind or sug["basis_ref"] != basis.ref:
        doc["notes"].append(
            "The suggested acts were scored against an earlier version of this crowd. Suggest again on Soundcheck to refresh them."
        )

    suggested: dict[str, Any] = sug["result"]
    top: list[dict[str, Any]] = list(suggested.get("top", []))
    wildcard: dict[str, Any] | None = suggested.get("wildcard")
    ids = [UUID(t["soundcheck_id"]) for t in top if t.get("soundcheck_id")]
    if wildcard and wildcard.get("soundcheck_id"):
        ids.append(UUID(wildcard["soundcheck_id"]))
    async with transaction(engine, tenant_id=tenant_id) as conn:
        rows = (
            await conn.execute(
                text("SELECT id, result FROM soundcheck WHERE id = ANY(:i) AND business_id = :b"),
                {"i": ids, "b": business_id},
            )
        ).all()
    verdicts = {str(r.id): r.result for r in rows}

    def act(s: dict[str, Any]) -> dict[str, Any] | None:
        v = verdicts.get(s["soundcheck_id"])
        if v is None or v.get("status") != "ok":
            return None
        return {
            "name": s["name"],
            "genres": s["genres"][:3],
            "score": s["score"],
            "band": s["band"],
            "best_for": s["best_for"],
            "watch": s["watch"],
            "groups": [
                {"label": g["label"], "fit": _pct(g["fit"])}
                for g in v["groups"]
                if g["status"] == "scored" and g["fit"] is not None
            ],
            "provisional": bool(v.get("provisional")),
        }

    doc["acts"] = [a for a in (act(s) for s in top) if a]
    doc["wildcard"] = act(wildcard) if wildcard else None
    if not doc["acts"]:
        doc["reason"] = "No suggested act could be scored against this crowd yet."
        return doc

    total = np.zeros(7)
    for s in [*top, *([wildcard] if wildcard else [])]:
        v = verdicts.get(s["soundcheck_id"])
        if v and v.get("nights"):
            total += np.array(v["nights"]) * (s["score"] or 0)
    if total.max() > 0:
        norm = total / total.max()
        days = sorted(int(d) for d in np.argsort(-norm, kind="stable") if norm[d] >= 0.6)[:3]
        noun = "scans" if basis.kind == "guests" else "past events"
        doc["nights"] = {"days": days, "text": f"{day_list(days)} carry the most {noun}."}
    doc["status"] = "ok"
    doc["how"] = (
        "Each score is 100 x group fit x (1 - 0.5 x clash risk). Group fit is how an act ranks, within the acts "
        "your own crowd picks, for what each group favours (Qloo's taste graph); clash risk is the share of the "
        "crowd it ranks poorly for. Scores describe fit with your crowd, not sales. The working and the Qloo calls "
        "behind every number are in the app."
    )
    doc["weights_version"] = soundcheck.WEIGHTS.version
    return doc


# ---------------------------------------------------------------------------------------------- share links
async def create_share(
    engine: AsyncEngine, tenant_id: UUID, business_id: UUID, doc: dict[str, Any]
) -> dict[str, Any]:
    """Freeze this document behind a new unguessable link that expires in 30 days."""
    token = new_token(24)
    expires = datetime.now(UTC) + timedelta(days=SHARE_DAYS)
    async with transaction(engine, tenant_id=tenant_id) as conn:
        row = (
            await conn.execute(
                text(
                    "INSERT INTO brief_share (tenant_id, business_id, token_hash, snapshot, expires_at)"
                    " VALUES (:t, :b, :h, CAST(:s AS jsonb), :e) RETURNING id, created_at"
                ),
                {
                    "t": tenant_id,
                    "b": business_id,
                    "h": token_hash(token),
                    "s": json.dumps(doc),
                    "e": expires,
                },
            )
        ).one()
    return {
        "id": str(row.id),
        "token": token,
        "created_at": row.created_at.isoformat(),
        "expires_at": expires.isoformat(),
    }


async def list_shares(
    engine: AsyncEngine, tenant_id: UUID, business_id: UUID
) -> list[dict[str, Any]]:
    async with transaction(engine, tenant_id=tenant_id) as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT id, created_at, expires_at, revoked_at FROM brief_share WHERE business_id = :b"
                    " ORDER BY created_at DESC LIMIT 20"
                ),
                {"b": business_id},
            )
        ).all()
    now = datetime.now(UTC)
    return [
        {
            "id": str(r.id),
            "created_at": r.created_at.isoformat(),
            "expires_at": r.expires_at.isoformat(),
            "live": r.revoked_at is None and r.expires_at > now,
        }
        for r in rows
    ]


async def revoke_share(
    engine: AsyncEngine, tenant_id: UUID, business_id: UUID, share_id: UUID
) -> bool:
    async with transaction(engine, tenant_id=tenant_id) as conn:
        done = (
            await conn.execute(
                text(
                    "UPDATE brief_share SET revoked_at = now() WHERE id = :i AND business_id = :b"
                    " AND revoked_at IS NULL RETURNING id"
                ),
                {"i": share_id, "b": business_id},
            )
        ).first()
    return done is not None


async def resolve_share(engine: AsyncEngine, token: str) -> dict[str, Any] | None:
    """The frozen document behind a live link, or None for anything unknown, expired or revoked."""
    async with engine.begin() as conn:
        row = (
            await conn.execute(
                text("SELECT snapshot, expires_at FROM public_resolve_brief(:h)"),
                {"h": token_hash(token)},
            )
        ).first()
    if row is None:
        return None
    doc: dict[str, Any] = dict(row.snapshot)
    doc["expires_at"] = row.expires_at.isoformat()
    return doc
