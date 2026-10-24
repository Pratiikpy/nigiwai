"""Ask Nigiwai (PRD M12): the owner asks a question; a model with a fixed set of Qloo-backed tools answers it, and code
checks the answer before anyone sees it.

What the model writes is never trusted. Every item it lists must be an entity that a tool returned during this question,
and its name comes from that record, not from the model; where an item first appeared (surfaced by Qloo, or proposed by
the model and confirmed by a lookup) is read from the trace, not self-reported. Names in the sentences are checked the
same way and removed when no tool returned them. A model that cannot produce a valid answer, or runs out of time or budget,
gets a plain list of what Qloo returned instead. The answer is stored, with the Qloo calls behind it, so a refresh restores it.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from qloo_guard import QlooGuard
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from ..db import transaction
from . import ask_prompt
from . import ask_tools as tools
from .llm import LlmClient, LlmUnavailable

log = logging.getLogger("nigiwai.ask")

MAX_TURNS = 12
WALL_SECONDS = 70.0
QUESTION_MAX = 600
MODES = ("crowd", "culture")
STEPS = {
    "resolve_entity": "Looking the item up in Qloo",
    "related": "Asking Qloo what is linked to it",
    "places_nearby": "Looking for places near the venue",
    "verify_place": "Checking that Qloo knows the place",
    "fit_verdict": "Scoring the act against your crowd",
    "my_groups": "Reading your crowd's groups",
    "my_hours": "Reading your quietest hours",
    "my_moves": "Reading the changes you logged",
}
REDACTED = "[a name Qloo did not return]"


class AskError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


Emit = Callable[[str, dict[str, Any]], Awaitable[None]]


def clean_question(raw: str) -> str:
    q = "".join(
        ch for ch in raw if ch >= " " or ch in "\n\t"
    )  # control characters are dropped, not spaced
    return " ".join(q.split())[:QUESTION_MAX]


# ---------------------------------------------------------------------------------------------------- names in text
_CONNECTORS = {"of", "the", "and", "&", "de", "la", "von", "van", "del", "in", "on", "for"}
_OPENERS = {
    "a", "an", "the", "your", "you", "this", "that", "these", "those", "it", "its", "we", "i", "there", "here", "for",
    "with", "and", "but", "so", "if", "based", "most", "some", "many", "few", "not", "no", "yes", "our", "their", "his",
    "her", "when", "while", "as", "at", "in", "on", "by", "from", "to", "of", "is", "are", "was", "were", "be", "qloo",
    "nigiwai", "measured", "observed", "modelled", "consider", "try", "book", "ask", "check", "see", "use", "add",
    "start", "keep", "put", "make", "bring", "invite", "also", "then", "next", "first", "second", "third", "today",
    "tonight", "tomorrow", "yesterday", "both", "all", "each", "every", "one", "two", "three", "four", "five",
}  # fmt: skip
_CALENDAR = {
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "january", "february", "march",
    "april", "may", "june", "july", "august", "september", "october", "november", "december", "mondays", "tuesdays",
    "wednesdays", "thursdays", "fridays", "saturdays", "sundays",
}  # fmt: skip
_APOSTROPHE = chr(0x2019)
_WORD = re.compile(r"[^\W_][\w'" + _APOSTROPHE + r"&.\-]*")
_LQ, _RQ = chr(0x201C), chr(0x201D)
_QUOTED = re.compile('["' + _LQ + ']([^"' + _RQ + ']{3,60})["' + _RQ + "]")


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", s.casefold()).strip()


def _phrases(sentence: str) -> list[str]:
    """Runs of two or more capitalised words (with small connectors between them), and quoted strings: what a name looks
    like in a sentence. A sentence-opening word and calendar names do not count towards a run."""
    out = [m.group(1) for m in _QUOTED.finditer(sentence)]
    tokens = _WORD.findall(sentence)
    run: list[str] = []

    def flush() -> None:
        words = list(run)
        while words and (words[0].casefold() in _OPENERS or words[0].casefold() in _CALENDAR):
            words.pop(0)
        while words and (words[-1].casefold() in _CONNECTORS or words[-1].casefold() in _CALENDAR):
            words.pop()
        caps = [w for w in words if w[0].isupper() or w[0].isdigit()]
        if len(caps) >= 2:
            out.append(" ".join(words))
        run.clear()

    for tok in tokens:
        if tok[0].isupper() or tok[0].isdigit() or (tok.casefold() in _CONNECTORS and run):
            run.append(tok)
        else:
            flush()
    flush()
    return out


def redact(run: tools.Run, value: str, allowed: set[str]) -> tuple[str, int]:
    """Replace every name-like phrase that no tool returned (and that is not the venue or a plain label) with a marker."""
    known = (
        {_norm(s.name) for s in run.seen.values()} | {_norm(n) for n in run.known_names} | allowed
    )
    known.discard("")
    removed = 0
    for phrase in sorted(set(_phrases(value)), key=len, reverse=True):
        p = _norm(phrase)
        if not p or any(p in k or k in p for k in known):
            continue
        value = re.sub(re.escape(phrase), REDACTED, value)
        removed += 1
    return value, removed


# ---------------------------------------------------------------------------------------------------- validation
def _text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def validate(run: tools.Run, raw: dict[str, Any]) -> dict[str, Any]:
    """Turn what the model gave the answer tool into the answer shown: only items a tool returned, names from Qloo's
    records, labels the evidence can support, and no names in the text that no tool returned."""
    allowed = {_norm(run.venue)} | {_norm(w) for w in (run.address or "").split(",") if w.strip()}
    removed = 0

    def clean(value: Any, limit: int) -> str:
        nonlocal removed
        s, n = redact(run, _text(value, limit), allowed)
        removed += n
        return s

    items: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    used: set[str] = set()
    for it in (raw.get("items") or [])[:12] if isinstance(raw.get("items"), list) else []:
        entity_id = str(it.get("entity_id", "")) if isinstance(it, dict) else ""
        seen = run.seen.get(entity_id)
        if seen is None:
            rejected.append(
                {
                    "entity_id": entity_id[:60],
                    "reason": "No Qloo call returned this item, so it is not listed.",
                }
            )
            continue
        if entity_id in used or len(items) >= 8:
            continue
        used.add(entity_id)
        confirmed = seen.first_tool in ("resolve_entity", "verify_place")
        items.append(
            {
                "entity_id": entity_id,
                "rank": len(items) + 1,
                "name": seen.name,
                "type": seen.kind,
                "reason": clean(it.get("reason"), 200),
                "provenance": "confirmed" if confirmed else "surfaced",
                "label": "observed",
                "call": seen.first_call,
                "detail": seen.note,
            }
        )

    evidence: list[dict[str, str]] = []
    for e in (raw.get("evidence") or [])[:6] if isinstance(raw.get("evidence"), list) else []:
        if not isinstance(e, dict):
            continue
        label = str(e.get("label", "modelled"))
        # a label has to be earned: "measured" needs the owner's data to have been read, "observed" needs a Qloo call
        if label == "measured" and not run.owner_data_used:
            label = "modelled"
        if label == "observed" and not run.qloo_used:
            label = "modelled"
        if label not in ("measured", "observed", "modelled"):
            label = "modelled"
        body = clean(e.get("text"), 300)
        if body:
            evidence.append({"label": label, "text": body})

    nothing = raw.get("not_enough_data")
    not_enough: dict[str, Any] | None = None
    if isinstance(nothing, dict) and (nothing.get("reason") or nothing.get("unlock")):
        listed = nothing.get("unlock")
        unlock: list[Any] = listed if isinstance(listed, list) else []
        not_enough = {
            "reason": clean(nothing.get("reason"), 300),
            "unlock": [clean(u, 200) for u in unlock[:4] if u],
        }

    would = raw.get("what_would_change")
    answer: dict[str, Any] = {
        "verdict": clean(raw.get("verdict"), 400),
        "items": items,
        "rejected": rejected,
        "evidence": evidence,
        "what_would_change": [
            clean(w, 200) for w in (would if isinstance(would, list) else [])[:3] if w
        ],
        "not_enough_data": not_enough,
        "notes": [],
    }
    if removed:
        answer["notes"].append(
            f"{removed} name{'s' if removed != 1 else ''} in the written answer {'were' if removed != 1 else 'was'} removed because no Qloo call returned {'them' if removed != 1 else 'it'}."
        )
    if rejected:
        answer["notes"].append(
            f"{len(rejected)} item{'s' if len(rejected) != 1 else ''} the assistant proposed {'were' if len(rejected) != 1 else 'was'} left out because Qloo never returned {'them' if len(rejected) != 1 else 'it'}."
        )
    return answer


def template_answer(run: tools.Run, reason: str) -> dict[str, Any]:
    """What to show when the model could not give a valid answer: the items Qloo returned, plainly, unranked."""
    surfaced = [
        s for s in run.seen.values() if s.first_tool in ("related", "places_nearby", "fit_verdict")
    ]
    pool = surfaced or list(run.seen.values())
    items = [
        {
            "entity_id": s.entity_id,
            "rank": i + 1,
            "name": s.name,
            "type": s.kind,
            "reason": "",
            "provenance": "confirmed"
            if s.first_tool in ("resolve_entity", "verify_place")
            else "surfaced",
            "label": "observed",
            "call": s.first_call,
            "detail": s.note,
        }
        for i, s in enumerate(pool[:6])
    ]
    return {
        "verdict": (
            "Here is what Qloo returned for your question, unranked. " + reason
            if items
            else "Nothing could be found for that question. " + reason
        ),
        "items": items,
        "rejected": [],
        "evidence": [
            {
                "label": "observed",
                "text": f"{len(items)} item{'s' if len(items) != 1 else ''} came back from Qloo.",
            }
        ]
        if items
        else [],
        "what_would_change": ["Ask again, or ask in a narrower way."],
        "not_enough_data": None
        if items
        else {"reason": reason, "unlock": ["Try a more specific question."]},
        "notes": [],
    }


# ---------------------------------------------------------------------------------------------------- the loop
async def _venue(engine: AsyncEngine, tenant_id: UUID, business_id: UUID) -> Any:
    async with transaction(engine, tenant_id=tenant_id) as conn:
        return (
            await conn.execute(
                text(
                    "SELECT b.name AS business, b.type AS type, l.timezone AS tz, l.address AS address,"
                    " ST_Y(l.geom::geometry) AS lat, ST_X(l.geom::geometry) AS lon, l.radius_m AS radius"
                    " FROM business b LEFT JOIN LATERAL"
                    " (SELECT * FROM location WHERE business_id = b.id ORDER BY created_at, id LIMIT 1) l ON true"
                    " WHERE b.id = :b"
                ),
                {"b": business_id},
            )
        ).first()


async def preflight(
    engine: AsyncEngine,
    llm: LlmClient | None,
    limiter: Any,
    *,
    tenant_id: UUID,
    business_id: UUID,
    question: str,
    mode: str,
    daily_limit: int,
) -> tuple[str, Any]:
    """Everything that can be refused before the model is called: an empty question, an unknown mode, no AI service,
    an unknown venue, a spent daily allowance. Returns the cleaned question and the venue's row."""
    q = clean_question(question)
    if not q:
        raise AskError("Ask a question first.", 422)
    if mode not in MODES:
        raise AskError("Choose to ask about your crowd, or about the culture.", 422)
    if llm is None:
        raise AskError(
            "Ask Nigiwai needs an AI service, and none is connected to this server.", 503
        )
    venue = await _venue(engine, tenant_id, business_id)
    if venue is None:
        raise AskError("not found", 404)
    if await limiter.check_all([(f"ask:{tenant_id}", daily_limit, 86400.0)]):
        raise AskError(
            f"You have asked {daily_limit} questions today, which is the daily limit. Try again tomorrow.",
            429,
        )
    return q, venue


async def ask(
    engine: AsyncEngine,
    guard: QlooGuard | None,
    llm: LlmClient | None,
    limiter: Any,
    *,
    tenant_id: UUID,
    user_id: UUID,
    business_id: UUID,
    question: str,
    mode: str,
    daily_limit: int,
    emit: Emit,
    checked: tuple[str, Any] | None = None,
) -> dict[str, Any]:
    """Answer one question. Pass `checked` (from `preflight`) when the caller has already run the checks."""
    q, venue = checked or await preflight(
        engine,
        llm,
        limiter,
        tenant_id=tenant_id,
        business_id=business_id,
        question=question,
        mode=mode,
        daily_limit=daily_limit,
    )
    assert llm is not None  # preflight refuses without one

    from qloo_guard import AreaRef, GeoPoint  # noqa: F401  (kept local: only the area is built here)

    area = (
        tools.Area(GeoPoint(lat=float(venue.lat), lon=float(venue.lon)), int(venue.radius))
        if venue.lat is not None and venue.lon is not None and venue.radius
        else None
    )
    ctx = guard.new_context("ask", tenant_id=tenant_id) if guard is not None else None
    run = tools.Run(
        engine=engine,
        guard=guard,
        tenant_id=tenant_id,
        business_id=business_id,
        mode=mode,
        ctx=ctx,
        venue=venue.business,
        type=venue.type,
        timezone=venue.tz or "UTC",
        address=venue.address,
        area=area,
        emit=emit,
    )
    if ctx is not None:
        run.trace_ids.append(str(ctx.trace_id))
    system = ask_prompt.system_prompt(
        mode,
        venue=venue.business,
        type_=venue.type,
        today=tools.local_date_text(run.timezone),
        budget=tools.QLOO_BUDGET,
    )
    specs = tools.tools_for(mode)
    allowed_tools = {s["name"] for s in specs}
    messages: list[dict[str, Any]] = [{"role": "user", "content": f"Question from the owner: {q}"}]
    started = time.monotonic()
    turns = 0
    in_tok = out_tok = 0
    model_name = llm.model
    final: dict[str, Any] | None = None
    reason = ""
    repaired = False

    try:
        while turns < MAX_TURNS and final is None:
            if time.monotonic() - started > WALL_SECONDS:
                reason = "The assistant ran out of time, so it was stopped."
                break
            turn = await llm.converse(system, messages, specs)
            turns += 1
            in_tok += turn.input_tokens
            out_tok += turn.output_tokens
            model_name = turn.model
            if not turn.tool_calls:
                if repaired:
                    reason = "The assistant did not finish with an answer."
                    break
                repaired = True
                messages.append(
                    {
                        "role": "assistant",
                        "content": turn.content or [{"type": "text", "text": "(no text)"}],
                    }
                )
                messages.append(
                    {
                        "role": "user",
                        "content": "Finish by calling the answer tool with what you have.",
                    }
                )
                continue
            messages.append({"role": "assistant", "content": turn.content})
            results: list[dict[str, Any]] = []
            for call in turn.tool_calls:
                if call.name == "answer":
                    final = validate(run, call.input)
                    results.append(
                        {"type": "tool_result", "tool_use_id": call.id, "content": "recorded"}
                    )
                    break
                if call.name not in allowed_tools or call.name not in tools.HANDLERS:
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": call.id,
                            "content": json.dumps({"error": "unknown tool"}),
                            "is_error": True,
                        }
                    )
                    continue
                run.tools_called.append(call.name)
                await emit("step", {"text": STEPS.get(call.name, call.name), "tool": call.name})
                out = await tools.HANDLERS[call.name](run, call.input)
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": call.id,
                        "content": json.dumps(out)[:6000],
                    }
                )
            if final is None:
                messages.append({"role": "user", "content": results})
        if final is None and not reason:
            reason = "The assistant took too many steps, so it was stopped."
    except LlmUnavailable as exc:
        reason = f"The AI service had a problem ({str(exc).rstrip('.').lower()})."

    kind = "model"
    if final is None or (not final["verdict"] and not final["items"]):
        final = template_answer(run, reason or "The assistant gave no usable answer.")
        kind = "template"
    final["warnings"] = list(dict.fromkeys(run.warnings))
    if run.qloo_unavailable:
        final["notes"].append(
            "Qloo was slow or unavailable for part of this, so the answer may be thinner than usual."
        )
    final["stats"] = {
        "qloo_calls": tools.QLOO_BUDGET - run.qloo_left,
        "model_turns": turns,
        "tools": run.tools_called,
        "seconds": round(time.monotonic() - started, 1),
    }
    final["kind"] = kind
    final["mode"] = mode
    duration_ms = int((time.monotonic() - started) * 1000)
    async with transaction(engine, tenant_id=tenant_id, user_id=user_id) as conn:
        row = (
            await conn.execute(
                text(
                    "INSERT INTO ask_answer (tenant_id, business_id, created_by, mode, question, kind, answer, trace_ids,"
                    " model, prompt_hash, input_tokens, output_tokens, duration_ms)"
                    " VALUES (:t, :b, :u, :m, :q, :k, CAST(:a AS jsonb), CAST(:tr AS jsonb), :mo, :ph, :it, :ot, :d)"
                    " RETURNING id, created_at"
                ),
                {
                    "t": tenant_id,
                    "b": business_id,
                    "u": user_id,
                    "m": mode,
                    "q": q,
                    "k": kind,
                    "a": json.dumps(final),
                    "tr": json.dumps(run.trace_ids),
                    "mo": model_name,
                    "ph": ask_prompt.prompt_hash(),
                    "it": in_tok,
                    "ot": out_tok,
                    "d": duration_ms,
                },
            )
        ).one()
    stored = {"id": str(row.id), "question": q, "created_at": row.created_at.isoformat(), **final}
    await emit("answer", stored)
    return stored


async def recent(
    engine: AsyncEngine, tenant_id: UUID, business_id: UUID, limit: int = 20
) -> list[dict[str, Any]]:
    async with transaction(engine, tenant_id=tenant_id) as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT id, mode, question, kind, created_at, answer->>'verdict' AS verdict FROM ask_answer"
                    " WHERE business_id = :b ORDER BY created_at DESC LIMIT :n"
                ),
                {"b": business_id, "n": limit},
            )
        ).all()
    return [
        {
            "id": str(r.id),
            "mode": r.mode,
            "question": r.question,
            "kind": r.kind,
            "verdict": r.verdict,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


async def get(
    engine: AsyncEngine, tenant_id: UUID, business_id: UUID, answer_id: UUID
) -> dict[str, Any] | None:
    async with transaction(engine, tenant_id=tenant_id) as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT id, question, mode, created_at, answer FROM ask_answer WHERE id = :i AND business_id = :b"
                ),
                {"i": answer_id, "b": business_id},
            )
        ).first()
    if row is None:
        return None
    return {
        "id": str(row.id),
        "question": row.question,
        "created_at": row.created_at.isoformat(),
        **row.answer,
    }


async def trace(
    engine: AsyncEngine, tenant_id: UUID, business_id: UUID, answer_id: UUID
) -> list[dict[str, Any]] | None:
    """The Qloo calls behind a stored answer: what was sent and how Qloo answered, for the trace drawer."""
    async with transaction(engine, tenant_id=tenant_id) as conn:
        row = (
            await conn.execute(
                text("SELECT trace_ids FROM ask_answer WHERE id = :i AND business_id = :b"),
                {"i": answer_id, "b": business_id},
            )
        ).first()
        if row is None:
            return None
        ids = [UUID(t) for t in row.trace_ids]
        if not ids:
            return []
        calls = (
            await conn.execute(
                text(
                    "SELECT id, created_at, purpose, endpoint, params, status, http_status, transport, cache, latency_ms,"
                    " coalesce(array_length(result_entity_ids, 1), 0) AS results FROM qloo_call"
                    " WHERE trace_id = ANY(:t) ORDER BY created_at"
                ),
                {"t": ids},
            )
        ).all()
    return [
        {
            "id": str(c.id),
            "at": c.created_at.isoformat(),
            "purpose": c.purpose,
            "endpoint": c.endpoint,
            "params": c.params,
            "status": c.status,
            "http_status": c.http_status,
            "transport": c.transport,
            "cache": c.cache,
            "latency_ms": c.latency_ms,
            "results": c.results,
        }
        for c in calls
    ]
