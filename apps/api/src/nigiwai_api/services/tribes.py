"""Computing and storing a business's tribes.

Reads the clean responses and the Qloo tags stored for each picked item, runs the pure model in a worker thread, and
writes an immutable `tribe_version`. Qloo is called for two things: one `/entities` batch for picks whose tags were never
stored (items that entered the index before tags were kept, or by a path that did not return them), and one audience
reading per shown group (services/audience.py).
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from nigiwai_tribes import Pick, Respondent, Tag, TribeResult, TribesConfig, carry_names, compute
from qloo_guard import CallContext, EntitiesRequest, QlooGuard
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from ..db import transaction
from . import audience

log = logging.getLogger("nigiwai.tribes")

RECOMPUTE_AFTER_NEW = 10  # new clean responses before the groups are refitted (ARCHITECTURE 5.2)
RECOMPUTE_AFTER_AGE = timedelta(hours=24)
BACKFILL_BATCH = 50


@dataclass
class Outcome:
    stored: bool
    version: int | None
    state: str
    n: int
    reason: str


async def _rows(conn: Any, business_id: UUID) -> list[Any]:
    return list(
        (
            await conn.execute(
                text(
                    "SELECT r.id::text AS rid, r.local_weekday AS wd, r.local_hour AS hr, p.position, p.entity_id,"
                    "       p.entity_type, e.name_nfc AS name, e.tags AS tags"
                    " FROM response r"
                    " JOIN survey s ON s.id = r.survey_id AND s.version = r.survey_version"
                    " JOIN pick p ON p.response_id = r.id"
                    " LEFT JOIN qloo_entity e ON e.entity_id = p.entity_id"
                    " WHERE s.business_id = :b AND r.quality_flag = 'ok'"
                    " ORDER BY r.id, p.position"
                ),
                {"b": business_id},
            )
        ).all()
    )


def _respondents(rows: list[Any]) -> list[Respondent]:
    grouped: dict[str, list[Any]] = {}
    for row in rows:
        grouped.setdefault(row.rid, []).append(row)
    out: list[Respondent] = []
    for rid, picks in grouped.items():
        built = tuple(
            Pick(
                entity_id=p.entity_id,
                type=p.entity_type,
                name=p.name or p.entity_id,
                tags=tuple(Tag(t[0], t[1], t[2]) for t in (p.tags or [])),
            )
            for p in picks
        )
        out.append(Respondent(id=rid, picks=built, weekday=picks[0].wd, hour=picks[0].hr))
    return out


async def backfill_tags(
    engine: AsyncEngine, guard: QlooGuard | None, tenant_id: UUID, rows: list[Any]
) -> int:
    """One batched `/entities` call per 50 picked items whose stored record has no tags. Returns how many were asked for."""
    if guard is None:
        return 0
    missing = sorted({r.entity_id for r in rows if not r.tags})
    asked = 0
    from uuid import uuid4

    for i in range(0, len(missing), BACKFILL_BATCH):
        batch = missing[i : i + BACKFILL_BATCH]
        ctx = CallContext(
            trace_id=uuid4(), purpose="tribes", tenant_id=tenant_id, allow_unregistered_ids=True
        )
        try:
            await guard.entities(EntitiesRequest(entity_ids=tuple(batch)), ctx)
        except Exception:
            log.warning("tag backfill failed for %d items", len(batch), exc_info=True)
            continue
        asked += len(batch)
    return asked


async def latest(conn: Any, business_id: UUID) -> Any | None:
    return (
        await conn.execute(
            text(
                "SELECT id, version, state, n, input_hash, created_at, result FROM tribe_version"
                " WHERE business_id = :b ORDER BY version DESC LIMIT 1"
            ),
            {"b": business_id},
        )
    ).first()


async def recompute(
    engine: AsyncEngine,
    guard: QlooGuard | None,
    tenant_id: UUID,
    business_id: UUID,
    *,
    force: bool = False,
    cfg: TribesConfig | None = None,
    now: datetime | None = None,
) -> Outcome:
    """Refit when it is time: 10 or more new clean responses since the last version, a day since it, or `force`."""
    cfg = cfg or TribesConfig()
    now = now or datetime.now(UTC)
    async with transaction(engine, tenant_id=tenant_id) as conn:
        rows = await _rows(conn, business_id)
        previous = await latest(conn, business_id)
    responses = len({r.rid for r in rows})
    if previous is not None and not force:
        seen = int((previous.result.get("meta") or {}).get("responses", 0))
        if (
            responses - seen < RECOMPUTE_AFTER_NEW
            and now - previous.created_at < RECOMPUTE_AFTER_AGE
            and responses >= seen
        ):
            return Outcome(False, previous.version, previous.state, previous.n, "not due")

    if await backfill_tags(engine, guard, tenant_id, rows):
        async with transaction(engine, tenant_id=tenant_id) as conn:
            rows = await _rows(conn, business_id)
    respondents = _respondents(rows)
    result: TribeResult = await asyncio.to_thread(compute, respondents, cfg)

    prev_result: TribeResult | None = None
    if previous is not None:
        prev_result = _from_json(previous.result)
        if prev_result is not None and prev_result.input_hash == result.input_hash:
            return Outcome(False, previous.version, previous.state, previous.n, "unchanged")
        if prev_result is not None:
            carry_names(prev_result, result)

    doc = result.to_dict()
    doc["meta"] = {"responses": responses, "computed_at": now.isoformat()}
    # Kept beside the groups, not inside them: a stored group is rebuilt as a `TribeCard` for name carry-over.
    doc["audience"] = (
        await audience.read(guard, tenant_id, doc["tribes"])
        if result.state in ("provisional", "named")
        else {}
    )
    async with transaction(engine, tenant_id=tenant_id) as conn:
        version = (
            await conn.execute(
                text(
                    "INSERT INTO tribe_version (tenant_id, business_id, version, state, n, input_hash, result)"
                    " VALUES (:t, :b, COALESCE((SELECT max(version) FROM tribe_version WHERE business_id = :b), 0) + 1,"
                    "         :s, :n, :h, CAST(:r AS jsonb)) RETURNING version"
                ),
                {
                    "t": tenant_id,
                    "b": business_id,
                    "s": result.state,
                    "n": result.n,
                    "h": result.input_hash,
                    "r": json.dumps(doc),
                },
            )
        ).scalar_one()
    return Outcome(True, version, result.state, result.n, result.reason)


def _from_json(doc: dict[str, Any]) -> TribeResult | None:
    """Rebuild just enough of a stored result for name carry-over. A document this code cannot read is ignored."""
    from nigiwai_tribes import TribeCard

    try:
        tribes = [TribeCard(**t) for t in doc.get("tribes", [])]
        return TribeResult(
            version=doc["version"],
            state=doc["state"],
            reason=doc.get("reason", ""),
            n=doc["n"],
            k=doc["k"],
            input_hash=doc["input_hash"],
            stability=doc.get("stability"),
            vocab=doc.get("vocab", []),
            h=doc.get("h", []),
            tribes=tribes,
            crowd_rhythm=doc.get("crowd_rhythm", []),
            timed=doc.get("timed", 0),
            dropped=doc.get("dropped", {}),
            config=doc.get("config", {}),
        )
    except (KeyError, TypeError):
        return None


def public_view(doc: dict[str, Any]) -> dict[str, Any]:
    """What an owner's browser receives: everything except the fitted profiles and the vocabulary weights, which only
    the server needs to place a new guest."""
    out = {k: v for k, v in doc.items() if k not in ("h", "vocab", "config")}
    out["vocab_size"] = len(doc.get("vocab", []))
    return out
