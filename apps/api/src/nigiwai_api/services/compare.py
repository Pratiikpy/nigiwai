"""Qloo against an AI alone (PRD M23): the same question put to Qloo and to a language model with no tools, side by side.

The question is "which acts are closest to this one?". Qloo answers from its graph, so every act it names is a real entity.
The model answers from memory and is told to say so when it does not recognise the act; each act it names is then looked
up in Qloo by exact name, so the panel can show which ones exist. Neither side is ranked above the other: agreement and
disagreement are both reported as they are. The model's answer is cached per question, and nothing about a venue or a
guest is ever sent to it: only the act's public name.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from qloo_guard import ArtistInsights, CallContext, EntityType, QlooGuard, SearchRequest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from ..db import transaction
from .llm import LlmClient, LlmUnavailable

log = logging.getLogger("nigiwai.compare")

LIST_SIZE = 6
CACHE_VERSION = "v1"

SYSTEM = (
    "You answer from your own knowledge only. You have no tools, no search and no data about any venue or person. "
    "If you do not recognise the act, say so plainly instead of guessing. Reply with JSON only."
)
USER = (
    "The act is: {name}\n"
    "List up to 6 acts that are most similar to it, most similar first.\n"
    'Reply with JSON only, in exactly this shape: {{"recognised": true, "similar": ["act name", "act name"]}}. '
    'If you do not recognise the act, reply {{"recognised": false, "similar": []}}.'
)


def clean_name(name: str) -> str:
    """An act's name as it is put in a prompt or a search: one line, no control characters, at most 100 characters."""
    cleaned = "".join(
        " " if c.isspace() else c for c in name if c.isspace() or unicodedata.category(c)[0] != "C"
    )
    return " ".join(cleaned.split())[:100]


def normalise(name: str) -> str:
    base = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().casefold()
    return re.sub(r"[^a-z0-9]+", " ", base).strip()


def parse_answer(raw: str) -> tuple[bool, list[str]]:
    """The model's JSON, read defensively: a code fence or a sentence around it is tolerated, nothing else is."""
    match = re.search(r"\{.*\}", raw, flags=re.S)
    if match is None:
        raise LlmUnavailable("The AI service answered in a form that could not be read.")
    try:
        doc = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise LlmUnavailable("The AI service answered in a form that could not be read.") from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("recognised"), bool):
        raise LlmUnavailable("The AI service answered in a form that could not be read.")
    names: list[str] = []
    seen: set[str] = set()
    similar = doc.get("similar")
    for item in similar if isinstance(similar, list) else []:
        if not isinstance(item, str):
            continue
        n = clean_name(item)
        key = normalise(n)
        if n and key and key not in seen:
            seen.add(key)
            names.append(n)
    return doc["recognised"], names[:LIST_SIZE]


def summary(name: str, qloo_n: int, llm: dict[str, Any]) -> str:
    real = f"Qloo returned {qloo_n} real {'neighbour' if qloo_n == 1 else 'neighbours'}."
    if not llm["available"]:
        return f"There is no AI answer to compare: {llm['reason']} {real}"
    if llm["recognised"] is False:
        return f"The AI alone did not know {name} and gave no list. {real}"
    items = llm["items"]
    agree = sum(1 for i in items if i["in_qloo_list"])
    missing = sum(1 for i in items if not i["verified"])
    out = f"Both lists agree on {agree} of {len(items)} acts."
    out += (
        f" {missing} of the AI's acts could not be found in Qloo."
        if missing
        else " Every act the AI named exists in Qloo."
    )
    return (
        out
        + " Neither list is ranked above the other: the check only shows which acts Qloo can resolve."
    )


async def _cached(engine: AsyncEngine, key: str) -> dict[str, Any] | None:
    async with engine.begin() as conn:
        row = (
            await conn.execute(text("SELECT answer FROM llm_cache WHERE key = :k"), {"k": key})
        ).first()
    return dict(row.answer) if row else None


async def _store(engine: AsyncEngine, key: str, model: str, answer: dict[str, Any]) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO llm_cache (key, model, answer) VALUES (:k, :m, CAST(:a AS jsonb))"
                " ON CONFLICT (key) DO NOTHING"
            ),
            {"k": key, "m": model, "a": json.dumps(answer)},
        )


async def exists(engine: AsyncEngine, tenant_id: UUID, soundcheck_id: UUID) -> bool:
    """Whether the comparison for this Soundcheck is already stored, so opening it again costs nothing."""
    async with transaction(engine, tenant_id=tenant_id) as conn:
        found = (
            await conn.execute(
                text("SELECT 1 FROM soundcheck_comparison WHERE soundcheck_id = :i"),
                {"i": soundcheck_id},
            )
        ).first()
    return found is not None


async def build(
    engine: AsyncEngine,
    guard: QlooGuard | None,
    llm: LlmClient | None,
    limiter: Any,
    daily_limit: int,
    tenant_id: UUID,
    business_id: UUID,
    soundcheck_id: UUID,
) -> dict[str, Any] | None:
    """The comparison for a stored Soundcheck, computed once and stored beside it."""
    async with transaction(engine, tenant_id=tenant_id) as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT s.candidate_entity_id, s.candidate_name, c.result AS done FROM soundcheck s"
                    " LEFT JOIN soundcheck_comparison c ON c.soundcheck_id = s.id"
                    " WHERE s.id = :i AND s.business_id = :b"
                ),
                {"i": soundcheck_id, "b": business_id},
            )
        ).first()
    if row is None:
        return None
    if row.done is not None:
        return dict(row.done)
    name = clean_name(row.candidate_name)

    # Qloo's side: the act's neighbours in its graph, every one a real entity.
    qloo: dict[str, Any] = {"available": False, "reason": None, "items": []}
    if guard is None:
        qloo["reason"] = "Qloo is not configured on this server."
    else:
        ctx = CallContext(trace_id=uuid4(), purpose="board", tenant_id=tenant_id)
        verdicts = await guard.ensure_eligible((row.candidate_entity_id,), ctx)
        if verdicts.get(row.candidate_entity_id) is not True:
            qloo["reason"] = "Qloo cannot use this act as a starting point."
        else:
            res = await guard.insights(
                ArtistInsights(signal_entities=(row.candidate_entity_id,), take=LIST_SIZE), ctx
            )
            if res.ok:
                qloo = {
                    "available": True,
                    "reason": None,
                    "items": [
                        {"name": e.name, "entity_id": e.entity_id} for e in res.items[:LIST_SIZE]
                    ],
                }
            else:
                qloo["reason"] = "Qloo did not answer."

    # The model's side, with each act it names looked up in Qloo by exact name.
    ai: dict[str, Any] = {
        "available": False,
        "reason": None,
        "model": None,
        "recognised": None,
        "items": [],
    }
    if llm is None:
        ai["reason"] = "no AI service is configured on this server."
    else:
        try:
            if await limiter.check_all([(f"llm:{tenant_id}", daily_limit, 86400.0)]):
                raise LlmUnavailable("the daily limit for AI answers has been reached.")
            answer = await _answer(engine, llm, name)
        except LlmUnavailable as exc:
            ai["reason"] = (
                str(exc).rstrip(".").lower().replace("the ai service", "the AI service") + "."
            )
        else:
            ai.update(available=True, model=answer["model"], recognised=answer["recognised"])
            in_qloo = {normalise(i["name"]): i["entity_id"] for i in qloo["items"]}
            ctx = CallContext(trace_id=uuid4(), purpose="board", tenant_id=tenant_id)
            for n in answer["similar"]:
                entity_id = in_qloo.get(normalise(n))
                found_in_list = entity_id is not None
                if entity_id is None and guard is not None:
                    entity_id = await _exact(guard, ctx, n)
                ai["items"].append(
                    {
                        "name": n,
                        "verified": entity_id is not None,
                        "entity_id": entity_id,
                        "in_qloo_list": found_in_list,
                    }
                )
    doc = {
        "question": f"Which acts are closest to {name}?",
        "qloo": qloo,
        "ai": ai,
        "summary": summary(name, len(qloo["items"]), ai),
        "created_at": datetime.now(UTC).isoformat(),
    }
    async with transaction(engine, tenant_id=tenant_id) as conn:
        await conn.execute(
            text(
                "INSERT INTO soundcheck_comparison (soundcheck_id, tenant_id, result)"
                " VALUES (:i, :t, CAST(:r AS jsonb)) ON CONFLICT (soundcheck_id) DO NOTHING"
            ),
            {"i": soundcheck_id, "t": tenant_id, "r": json.dumps(doc)},
        )
    return doc


async def _answer(engine: AsyncEngine, llm: LlmClient, name: str) -> dict[str, Any]:
    key = hashlib.sha256(f"{CACHE_VERSION}|{llm.model}|{normalise(name)}".encode()).hexdigest()
    found = await _cached(engine, key)
    if found is not None:
        return found
    answer = await llm.complete(SYSTEM, USER.format(name=name), max_tokens=300)
    recognised, names = parse_answer(answer.text)
    doc = {"recognised": recognised, "similar": names, "model": answer.model}
    await _store(engine, key, llm.model, doc)
    return doc


async def _exact(guard: QlooGuard, ctx: CallContext, name: str) -> str | None:
    """The entity id of an act Qloo holds under exactly this name (ignoring case, accents and punctuation), else None.
    A near miss is never accepted: the top hit for a name that does not exist is usually a different artist."""
    res = await guard.search(
        SearchRequest(query=name, types=(EntityType.ARTIST,), take=3),
        CallContext(trace_id=ctx.trace_id, purpose="board", tenant_id=ctx.tenant_id),
    )
    if not res.ok:
        return None
    for e in res.items:
        if normalise(e.name) == normalise(name):
            return e.entity_id
    return None
