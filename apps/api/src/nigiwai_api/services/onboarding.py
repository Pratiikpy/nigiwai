"""Onboarding (PRD M1): an interview that learns what Nigiwai needs to know about a business, shows it back for the owner
to correct, and only then writes it down.

Two modes share one state machine. In `form` mode the next question is the next unanswered field of the checklist. In
`agent` mode a model reads what the owner wrote, may record answers (each needs a quote that really is in the owner's own
words, and a value the same validators accept as a typed one), and chooses which field to ask about next. It cannot ask
about a field outside the checklist, cannot ask a ninth question, cannot write anything the owner sees except the question,
and cannot record a value the code would refuse. When it is unavailable, slow, or over its daily allowance, the session
carries on in `form` mode from where it was. Nothing touches the business until the owner confirms.
"""

from __future__ import annotations

import asyncio
import json
import logging
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ..db import transaction
from . import onboarding_model as om
from . import onboarding_prompt as prompt
from .llm import LlmClient, LlmUnavailable

log = logging.getLogger("nigiwai.onboarding")

MODEL_TURNS = 6
WALL_SECONDS = 45.0
OWNER_TEXT_MAX = 600
QUESTION_MAX = 300
GREETING = (
    "Hello. A few quick questions and Nigiwai is set up for your business. "
    "Everything you tell me is shown back to you to check before it is saved."
)
GREETING_AGENT = (
    GREETING
    + " You can answer one at a time, or just tell me about your business in your own words."
)
UNDERSTOOD = "Here is what I understood. Check it, change anything that is wrong, then confirm."
# Modules the owner may switch: not part of the core, and built.
SWITCHABLE = frozenset(m.id for m in om.MODULES if not m.core and m.built)


class OnboardingError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class Deps:
    engine: AsyncEngine
    llm: LlmClient | None
    limiter: Any
    daily_limit: int


@dataclass
class Session:
    id: UUID
    mode: str
    status: str
    known: dict[str, Any]
    skipped: list[str]
    asked: list[dict[str, Any]]
    pending: str | None
    messages: list[dict[str, Any]]
    notice: str | None
    model: str | None
    input_tokens: int
    output_tokens: int
    updated_at: datetime
    context: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------------------------------- state machine
def _say(s: Session, words: str, field_id: str | None = None) -> None:
    s.messages.append({"role": "assistant", "text": words, "field": field_id})


def _hear(s: Session, words: str, field_id: str | None = None) -> None:
    s.messages.append({"role": "owner", "text": words, "field": field_id})


def _ask(s: Session, field_id: str, words: str | None = None) -> None:
    """Put a question to the owner. Asking about the same field again (a new wording) does not count as a new question."""
    asked_text = " ".join((words or om.CHECKLIST[field_id].text).split())[:QUESTION_MAX]
    earlier = next((a for a in s.asked if a["field"] == field_id), None)
    if earlier is None:
        s.asked.append({"field": field_id, "text": asked_text})
    else:
        earlier["text"] = asked_text
    s.pending = field_id
    _say(s, asked_text, field_id)


def _finish(s: Session) -> None:
    s.pending = None
    if not s.messages or s.messages[-1]["text"] != UNDERSTOOD:
        _say(s, UNDERSTOOD)


def advance(s: Session) -> None:
    """Ask the next question of the fixed checklist, or finish when nothing more is worth asking."""
    for fid in om.remaining(s.known, skipped=set(s.skipped)):
        if om.may_ask(fid, s.known, len(s.asked)):
            _ask(s, fid)
            return
    _finish(s)


def _store(s: Session, field_id: str, accepted: Any, picked: Any = None) -> None:
    """Keep an accepted value. A new address drops the old position, which no longer belongs to it."""
    if field_id == "area":
        if picked is not None:
            s.known["place"] = picked
        elif s.known.get("area") != accepted:
            s.known.pop("place", None)
    s.known[field_id] = accepted
    if field_id in s.skipped:
        s.skipped.remove(field_id)


def _resolved(s: Session, field_id: str) -> bool:
    """Whether this answer settles the question being asked; if so, nothing is pending any more."""
    if field_id != s.pending:
        return False
    s.pending = None
    return True


def apply_answer(s: Session, field_id: str, value: Any, place: Any = None) -> bool:
    """Record an answer the owner gave. Returns whether it resolved the question that was pending."""
    if s.status != "open":
        raise OnboardingError("This interview is closed. Start a new one.", 409)
    if field_id not in om.CHECKLIST:
        raise OnboardingError("That is not something I asked about.", 422)
    try:
        accepted = om.normalise(field_id, value)
        picked = om.normalise("place", place) if place is not None else None
    except om.AnswerError as exc:
        raise OnboardingError(str(exc), 422) from exc
    _store(s, field_id, accepted, picked)
    _hear(s, om.describe_answer(field_id, accepted), field_id)
    return _resolved(s, field_id)


def apply_skip(s: Session, field_id: str) -> bool:
    if s.status != "open":
        raise OnboardingError("This interview is closed. Start a new one.", 409)
    spec = om.CHECKLIST.get(field_id)
    if spec is None or field_id == "place":
        raise OnboardingError("That is not something I asked about.", 422)
    if spec.required:
        raise OnboardingError("This one is needed to set things up, so it cannot be skipped.", 422)
    if field_id in s.known:
        raise OnboardingError("You have already answered this one. Change the answer instead.", 422)
    if field_id not in s.skipped:
        s.skipped.append(field_id)
    _hear(s, "Skip this one", field_id)
    return _resolved(s, field_id)


def to_form(s: Session, notice: str | None) -> None:
    """Carry on with the fixed questions from where the interview is."""
    s.mode = "form"
    if notice:
        s.notice = notice
    if s.pending is None:
        advance(s)


def _fold(words: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", words).casefold().split())


def grounded(quote: Any, owner_words: str) -> bool:
    """Whether a quote really is in what the owner wrote: case, spacing and edge punctuation do not matter."""
    if not isinstance(quote, str):
        return False
    q = _fold(quote).strip(" .,;:!?\"'")
    return len(q) >= 2 and q in _fold(owner_words)


# ---------------------------------------------------------------------------------------------------- the model's turn
def _handle(s: Session, name: str, args: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Run one tool the model asked for. Returns the result it is shown and whether its turn is over."""
    if name == "record_answer":
        fid = args.get("field")
        if not isinstance(fid, str) or fid not in om.CHECKLIST or fid == "place":
            return {"error": "unknown field"}, False
        owner_words = " ".join(m["text"] for m in s.messages if m["role"] == "owner")
        if not grounded(args.get("quote"), owner_words):
            return {
                "error": "the quote is not in the owner's own words; quote exactly what they wrote"
            }, False
        try:
            accepted = om.normalise(fid, args.get("value"))
        except om.AnswerError as exc:
            return {"error": str(exc)}, False
        _store(s, fid, accepted)
        _resolved(s, fid)
        return {"recorded": fid}, False
    if name == "ask_owner":
        fid = args.get("field")
        words = args.get("text")
        if not isinstance(fid, str) or fid not in om.FORM_ORDER:
            return {"error": "unknown field"}, False
        if fid not in om.remaining(s.known, skipped=set(s.skipped)):
            return {"error": "that field is known, skipped, or not relevant here"}, False
        if not om.may_ask(fid, s.known, len(s.asked)) and not any(
            a["field"] == fid for a in s.asked
        ):
            return {"error": "the question limit is reached; call finish"}, False
        if not isinstance(words, str) or not words.strip():
            return {"error": "give the question in words"}, False
        _ask(s, fid, words)
        return {"asked": fid}, True
    if name == "finish":
        missing = om.missing_required(s.known)
        if missing:
            return {"error": "required fields are still missing", "missing": missing}, False
        _finish(s)
        return {"finished": True}, True
    return {"error": "unknown tool"}, False


async def _agent_step(deps: Deps, s: Session, event: str) -> None:
    """Let the model choose what happens next: record what the owner said, ask one more question, or finish."""
    if deps.llm is None:
        to_form(s, "No assistant is connected, so the questions come one at a time.")
        return
    if await deps.limiter.check_all(
        [(f"onboard-model:{s.context['tenant_id']}", deps.daily_limit, 86400.0)]
    ):
        to_form(s, "The assistant has reached today's limit, so the questions come one at a time.")
        return
    system = prompt.system_prompt(
        business=s.context["business"], today=datetime.now(UTC).date().isoformat()
    )
    left = om.remaining(s.known, skipped=set(s.skipped))
    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": prompt.context_message(
                known=s.known,
                skipped=s.skipped,
                asked=len(s.asked),
                left=left,
                transcript=s.messages,
                event=event,
            ),
        }
    ]
    nudged = False
    try:
        async with asyncio.timeout(WALL_SECONDS):
            for _ in range(MODEL_TURNS):
                turn = await deps.llm.converse(system, messages, prompt.TOOLS, max_tokens=800)
                s.input_tokens += turn.input_tokens
                s.output_tokens += turn.output_tokens
                s.model = turn.model
                if not turn.tool_calls:
                    if nudged:
                        break
                    nudged = True
                    messages.append(
                        {
                            "role": "assistant",
                            "content": turn.content or [{"type": "text", "text": "(no text)"}],
                        }
                    )
                    messages.append(
                        {
                            "role": "user",
                            "content": "Call record_answer, ask_owner or finish.",
                        }
                    )
                    continue
                messages.append({"role": "assistant", "content": turn.content})
                results: list[dict[str, Any]] = []
                for call in turn.tool_calls:
                    out, over = _handle(s, call.name, call.input)
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": call.id,
                            "content": json.dumps(out),
                            **({"is_error": True} if "error" in out else {}),
                        }
                    )
                    if over:
                        return
                messages.append({"role": "user", "content": results})
    except TimeoutError:
        to_form(s, "The assistant took too long, so the questions come one at a time.")
        return
    except LlmUnavailable as exc:
        to_form(
            s,
            f"The assistant is unavailable ({str(exc).rstrip('.').lower()}), so the questions come one at a time.",
        )
        return
    if s.pending is None:  # the model gave no usable next step; ask the next fixed question
        advance(s)


# ---------------------------------------------------------------------------------------------------- storage
_SELECT_OPEN = (
    "SELECT id, mode, status, known, skipped, asked, pending, messages, notice, model, input_tokens,"
    " output_tokens, updated_at FROM onboarding_session WHERE status = 'open'"
)


def _session(row: Any, context: dict[str, Any]) -> Session:
    return Session(
        id=row.id,
        mode=row.mode,
        status=row.status,
        known=dict(row.known),
        skipped=list(row.skipped),
        asked=[dict(a) for a in row.asked],
        pending=row.pending,
        messages=[dict(m) for m in row.messages],
        notice=row.notice,
        model=row.model,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        updated_at=row.updated_at,
        context=context,
    )


async def _context(conn: AsyncConnection, tenant_id: UUID) -> dict[str, Any]:
    row = (
        await conn.execute(
            text(
                "SELECT coalesce((SELECT name FROM business ORDER BY created_at, id LIMIT 1),"
                " (SELECT name FROM tenant WHERE id = :t)) AS name"
            ),
            {"t": tenant_id},
        )
    ).first()
    return {"tenant_id": tenant_id, "business": row.name if row and row.name else "this business"}


async def _open(conn: AsyncConnection, tenant_id: UUID, *, lock: bool = False) -> Session | None:
    row = (await conn.execute(text(_SELECT_OPEN + (" FOR UPDATE" if lock else "")))).first()
    return None if row is None else _session(row, await _context(conn, tenant_id))


async def _save(conn: AsyncConnection, s: Session) -> None:
    result = await conn.execute(
        text(
            "UPDATE onboarding_session SET mode = :m, known = CAST(:k AS jsonb), skipped = CAST(:sk AS jsonb),"
            " asked = CAST(:a AS jsonb), pending = :p, messages = CAST(:ms AS jsonb), notice = :n, model = :mo,"
            " input_tokens = :it, output_tokens = :ot, updated_at = now()"
            " WHERE id = :i AND status = 'open' AND updated_at = :u"
        ),
        {
            "m": s.mode,
            "k": json.dumps(s.known),
            "sk": json.dumps(s.skipped),
            "a": json.dumps(s.asked),
            "p": s.pending,
            "ms": json.dumps(s.messages),
            "n": s.notice,
            "mo": s.model,
            "it": s.input_tokens,
            "ot": s.output_tokens,
            "i": s.id,
            "u": s.updated_at,
        },
    )
    if result.rowcount == 0:
        raise OnboardingError(
            "This interview changed in another window. Reload the page to carry on.", 409
        )


def view(s: Session, *, agent_available: bool) -> dict[str, Any]:
    """The interview as the page needs it: the conversation, the question being asked, what was understood so far and,
    once the required answers are in, the profile and plan that would be saved."""
    question = None
    if s.status == "open" and s.pending:
        question = om.question_for(s.pending, s.known)
        spoken = next((a["text"] for a in reversed(s.asked) if a["field"] == s.pending), None)
        question["text"] = spoken or question["text"]
    ready = not om.missing_required(s.known)
    profile = plan = None
    if ready:
        try:
            built = om.build_profile(s.context.get("business", ""), s.known)
            profile = built.model_dump()
            plan = om.plan_for(built).to_json()
        except ValueError:
            profile = plan = None
    return {
        "id": str(s.id),
        "mode": s.mode,
        "status": s.status,
        "agent_available": agent_available,
        "messages": s.messages,
        "question": question,
        "asked": len(s.asked),
        "max_questions": om.MAX_QUESTIONS,
        "known": s.known,
        "understood": om.understood(s.known),
        "ready": ready,
        "business_name": s.context.get("business"),
        "profile": profile,
        "plan": plan,
        "notice": s.notice,
    }


async def _prefill(conn: AsyncConnection) -> dict[str, Any]:
    """What is already on record for this business, so a second interview starts from it and asks only what is missing."""
    biz = (
        await conn.execute(
            text("SELECT id, type, currency FROM business ORDER BY created_at, id LIMIT 1")
        )
    ).first()
    if biz is None:
        return {}
    raw: dict[str, Any] = {"type": biz.type, "currency": biz.currency}
    loc = (
        await conn.execute(
            text(
                "SELECT address, ST_Y(geom::geometry) AS lat, ST_X(geom::geometry) AS lon, hours, capacity,"
                " show_nights, excluded_genres FROM location WHERE business_id = :b ORDER BY created_at, id LIMIT 1"
            ),
            {"b": biz.id},
        )
    ).first()
    if loc is not None:
        if loc.address:
            raw["area"] = loc.address
        if loc.lat is not None and loc.lon is not None:
            raw["place"] = {
                "lat": loc.lat,
                "lon": loc.lon,
                "label": loc.address or "Saved position",
            }
        if isinstance(loc.hours, list) and any(loc.hours):
            raw["hours"] = loc.hours
        if loc.capacity:
            raw["capacity"] = loc.capacity
        if loc.show_nights:
            raw["show_nights"] = [int(n) for n in loc.show_nights]
        if loc.excluded_genres:
            raw["excluded_genres"] = list(loc.excluded_genres)
    last = (
        await conn.execute(
            text(
                "SELECT profile FROM business_profile WHERE business_id = :b ORDER BY version DESC LIMIT 1"
            ),
            {"b": biz.id},
        )
    ).first()
    if last is not None:
        for key in ("goals", "hosts_live_music"):
            if key in last.profile:
                raw[key] = last.profile[key]
    known: dict[str, Any] = {}
    for fid, value in raw.items():
        try:
            known[fid] = om.normalise(fid, value)
        except om.AnswerError:
            continue  # something on record that would not be accepted today is asked again, not carried over
    return known


# ---------------------------------------------------------------------------------------------------- operations
async def get(deps: Deps, tenant_id: UUID) -> dict[str, Any]:
    async with transaction(deps.engine, tenant_id=tenant_id) as conn:
        s = await _open(conn, tenant_id)
        plan = await current_plan(conn)
    return {
        "agent_available": deps.llm is not None,
        "session": None if s is None else view(s, agent_available=deps.llm is not None),
        "plan": plan,
    }


async def start(
    deps: Deps, tenant_id: UUID, user_id: UUID, *, mode: str, restart: bool
) -> dict[str, Any]:
    """Open an interview, or return the one already open. `restart` abandons the open one first."""
    agent = deps.llm is not None
    try:
        async with transaction(deps.engine, tenant_id=tenant_id, user_id=user_id) as conn:
            s = await _open(conn, tenant_id, lock=True)
            if s is not None and not restart:
                return view(s, agent_available=agent)
            if s is not None:
                await conn.execute(
                    text(
                        "UPDATE onboarding_session SET status = 'abandoned', updated_at = now() WHERE id = :i"
                    ),
                    {"i": s.id},
                )
            context = await _context(conn, tenant_id)
            fresh = Session(
                id=UUID(int=0),
                mode="agent" if agent and mode == "auto" else "form",
                status="open",
                known=await _prefill(conn),
                skipped=[],
                asked=[],
                pending=None,
                messages=[],
                notice=None,
                model=None,
                input_tokens=0,
                output_tokens=0,
                updated_at=datetime.now(UTC),
                context=context,
            )
            _say(fresh, GREETING_AGENT if fresh.mode == "agent" else GREETING)
            advance(fresh)
            row = (
                await conn.execute(
                    text(
                        "INSERT INTO onboarding_session (tenant_id, created_by, mode, known, skipped, asked, pending,"
                        " messages) VALUES (:t, :u, :m, CAST(:k AS jsonb), '[]'::jsonb, CAST(:a AS jsonb), :p,"
                        " CAST(:ms AS jsonb)) RETURNING id, updated_at"
                    ),
                    {
                        "t": tenant_id,
                        "u": user_id,
                        "m": fresh.mode,
                        "k": json.dumps(fresh.known),
                        "a": json.dumps(fresh.asked),
                        "p": fresh.pending,
                        "ms": json.dumps(fresh.messages),
                    },
                )
            ).one()
            fresh.id, fresh.updated_at = row.id, row.updated_at
            return view(fresh, agent_available=agent)
    except IntegrityError:  # two tabs started at once; the other one won
        async with transaction(deps.engine, tenant_id=tenant_id) as conn:
            s = await _open(conn, tenant_id)
        if s is None:
            raise OnboardingError("Could not start the interview. Try again.", 409) from None
        return view(s, agent_available=agent)


def _event(s: Session) -> str:
    """What just happened, in the words the model is told: the owner's last message."""
    last = s.messages[-1]
    if last.get("field"):
        return f"The owner answered the question about {last['field']}: {last['text']}"
    return f'The owner has just written: "{last["text"]}"'


async def _step(
    deps: Deps,
    tenant_id: UUID,
    session_id: UUID,
    change: Callable[[Session], bool],
) -> dict[str, Any]:
    """Load the open interview, apply the owner's change, let the next step happen (the model's, or the fixed form's),
    and save, refusing if the interview changed meanwhile. The database is not held open while the model thinks."""
    async with transaction(deps.engine, tenant_id=tenant_id) as conn:
        s = await _open(conn, tenant_id)
    if s is None or s.id != session_id:
        raise OnboardingError("not found", 404)
    if change(s):
        if s.mode == "agent":
            await _agent_step(deps, s, _event(s))
        else:
            advance(s)
    async with transaction(deps.engine, tenant_id=tenant_id) as conn:
        await _save(conn, s)
    return view(s, agent_available=deps.llm is not None)


async def answer(
    deps: Deps, tenant_id: UUID, session_id: UUID, field_id: str, value: Any, place: Any = None
) -> dict[str, Any]:
    return await _step(
        deps, tenant_id, session_id, lambda s: apply_answer(s, field_id, value, place)
    )


async def say(deps: Deps, tenant_id: UUID, session_id: UUID, words: str) -> dict[str, Any]:
    """The owner wrote in their own words (agent mode only): the model reads it."""
    clean = " ".join(words.split())
    if not clean or len(clean) > OWNER_TEXT_MAX or any(ord(c) < 32 for c in clean):
        raise OnboardingError("Write between one and 600 characters, on one line or several.", 422)

    def change(s: Session) -> bool:
        if s.mode != "agent":
            raise OnboardingError(
                "Writing in your own words needs the assistant. Answer the questions instead.", 409
            )
        if s.status != "open":
            raise OnboardingError("This interview is closed. Start a new one.", 409)
        _hear(s, clean)
        return True

    return await _step(deps, tenant_id, session_id, change)


async def skip(deps: Deps, tenant_id: UUID, session_id: UUID, field_id: str) -> dict[str, Any]:
    return await _step(deps, tenant_id, session_id, lambda s: apply_skip(s, field_id))


async def abandon(deps: Deps, tenant_id: UUID, user_id: UUID, session_id: UUID) -> None:
    async with transaction(deps.engine, tenant_id=tenant_id, user_id=user_id) as conn:
        result = await conn.execute(
            text(
                "UPDATE onboarding_session SET status = 'abandoned', updated_at = now()"
                " WHERE id = :i AND status = 'open'"
            ),
            {"i": session_id},
        )
        if result.rowcount == 0:
            raise OnboardingError("not found", 404)


# ---------------------------------------------------------------------------------------------------- confirming
def clean_overrides(overrides: dict[str, bool]) -> dict[str, bool]:
    for module_id in overrides:
        if module_id not in SWITCHABLE:
            raise OnboardingError(f"{module_id} cannot be switched on or off.", 422)
    return dict(overrides)


async def _first_business(conn: AsyncConnection) -> UUID | None:
    row = (
        await conn.execute(text("SELECT id FROM business ORDER BY created_at, id LIMIT 1"))
    ).first()
    return None if row is None else row.id


async def current_plan(conn: AsyncConnection) -> dict[str, Any] | None:
    business_id = await _first_business(conn)
    if business_id is None:
        return None
    row = (
        await conn.execute(
            text(
                "SELECT d.version, d.profile_version, d.plan, d.overrides, d.confirmed_at, p.profile"
                " FROM dashboard_plan d JOIN business_profile p"
                " ON p.business_id = d.business_id AND p.version = d.profile_version"
                " WHERE d.business_id = :b ORDER BY d.version DESC LIMIT 1"
            ),
            {"b": business_id},
        )
    ).first()
    if row is None:
        return None
    return {
        "version": row.version,
        "profile_version": row.profile_version,
        "confirmed_at": row.confirmed_at.isoformat(),
        "modules": row.plan["modules"],
        "overrides": row.overrides,
        "profile": row.profile,
    }


async def _write_versions(
    conn: AsyncConnection,
    tenant_id: UUID,
    user_id: UUID,
    business_id: UUID,
    profile: om.Profile,
    overrides: dict[str, bool],
    session_id: UUID | None,
    *,
    new_profile: bool,
) -> tuple[int, int]:
    if new_profile:
        version = (
            await conn.execute(
                text(
                    "INSERT INTO business_profile (business_id, version, tenant_id, profile, session_id, confirmed_by)"
                    " SELECT CAST(:b AS uuid), coalesce(max(version), 0) + 1, CAST(:t AS uuid), CAST(:p AS jsonb),"
                    " CAST(:s AS uuid), CAST(:u AS uuid)"
                    " FROM business_profile WHERE business_id = :b RETURNING version"
                ),
                {
                    "b": business_id,
                    "t": tenant_id,
                    "p": profile.model_dump_json(),
                    "s": session_id,
                    "u": user_id,
                },
            )
        ).scalar_one()
    else:
        version = (
            await conn.execute(
                text("SELECT max(version) FROM business_profile WHERE business_id = :b"),
                {"b": business_id},
            )
        ).scalar_one()
    plan = om.plan_for(profile, overrides)
    kept = {e.id: e.on for e in plan.entries if e.changed}
    plan_version = (
        await conn.execute(
            text(
                "INSERT INTO dashboard_plan (business_id, version, tenant_id, profile_version, plan, overrides,"
                " confirmed_by) SELECT CAST(:b AS uuid), coalesce(max(version), 0) + 1, CAST(:t AS uuid),"
                " CAST(:pv AS integer), CAST(:pl AS jsonb), CAST(:o AS jsonb), CAST(:u AS uuid)"
                " FROM dashboard_plan WHERE business_id = :b RETURNING version"
            ),
            {
                "b": business_id,
                "t": tenant_id,
                "pv": version,
                "pl": json.dumps(plan.to_json()),
                "o": json.dumps(kept),
                "u": user_id,
            },
        )
    ).scalar_one()
    return int(version), int(plan_version)


async def confirm(
    deps: Deps,
    tenant_id: UUID,
    user_id: UUID,
    session_id: UUID,
    *,
    name: str,
    timezone: str | None,
    overrides: dict[str, bool],
) -> dict[str, Any]:
    """Write what the owner confirmed: the business and its place (only the facts they gave; an empty answer never
    erases something already on record), the profile and the plan, each as a new version."""
    overrides = clean_overrides(overrides)
    async with transaction(deps.engine, tenant_id=tenant_id, user_id=user_id) as conn:
        s = await _open(conn, tenant_id, lock=True)
        if s is None or s.id != session_id:
            raise OnboardingError("not found", 404)
        if missing := om.missing_required(s.known):
            raise OnboardingError("Some answers are still needed: " + ", ".join(missing) + ".", 409)
        try:
            profile = om.build_profile(name, s.known, timezone=timezone)
        except ValueError as exc:
            raise OnboardingError(f"Something in the answers is not valid: {exc}", 422) from exc
        business_id = await _first_business(conn)
        if business_id is None:
            business_id = (
                await conn.execute(
                    text(
                        "INSERT INTO business (tenant_id, name, type, language, currency)"
                        " VALUES (:t, :n, :ty, :l, :c) RETURNING id"
                    ),
                    {
                        "t": tenant_id,
                        "n": profile.name,
                        "ty": profile.type,
                        "l": profile.language,
                        "c": profile.currency,
                    },
                )
            ).scalar_one()
        else:
            await conn.execute(
                text(
                    "UPDATE business SET name = :n, type = :ty, language = :l, currency = :c WHERE id = :i"
                ),
                {
                    "i": business_id,
                    "n": profile.name,
                    "ty": profile.type,
                    "l": profile.language,
                    "c": profile.currency,
                },
            )
        params = {
            "b": business_id,
            "t": tenant_id,
            "addr": profile.area,
            "lat": profile.lat,
            "lon": profile.lon,
            "tz": profile.timezone,
            "has_hours": bool(profile.hours),
            "hr": json.dumps([h.model_dump() if h else None for h in profile.hours]),
            "cap": profile.capacity,
            "sn": list(profile.show_nights),
            "eg": list(profile.excluded_genres),
        }
        location = (
            await conn.execute(
                text(
                    "SELECT id FROM location WHERE business_id = :b ORDER BY created_at, id LIMIT 1"
                ),
                {"b": business_id},
            )
        ).first()
        if location is None:
            await conn.execute(
                text(
                    "INSERT INTO location (tenant_id, business_id, name, address, geom, timezone, hours, capacity,"
                    " show_nights, excluded_genres) VALUES (:t, :b, 'Main room', :addr,"
                    " CASE WHEN CAST(:lon AS float8) IS NULL THEN NULL"
                    " ELSE ST_SetSRID(ST_MakePoint(CAST(:lon AS float8), CAST(:lat AS float8)), 4326)::geography END,"
                    " coalesce(CAST(:tz AS text), 'UTC'),"
                    " CASE WHEN :has_hours THEN CAST(:hr AS jsonb) ELSE '{}'::jsonb END, CAST(:cap AS integer),"
                    " CAST(:sn AS smallint[]), CAST(:eg AS text[]))"
                ),
                params,
            )
        else:
            await conn.execute(
                text(
                    "UPDATE location SET address = :addr,"
                    " geom = CASE WHEN CAST(:lon AS float8) IS NULL THEN geom"
                    " ELSE ST_SetSRID(ST_MakePoint(CAST(:lon AS float8), CAST(:lat AS float8)), 4326)::geography END,"
                    " timezone = coalesce(CAST(:tz AS text), timezone),"
                    " hours = CASE WHEN :has_hours THEN CAST(:hr AS jsonb) ELSE hours END,"
                    " capacity = coalesce(CAST(:cap AS integer), capacity),"
                    " show_nights = CASE WHEN cardinality(CAST(:sn AS smallint[])) > 0"
                    " THEN CAST(:sn AS smallint[]) ELSE show_nights END,"
                    " excluded_genres = CASE WHEN cardinality(CAST(:eg AS text[])) > 0"
                    " THEN CAST(:eg AS text[]) ELSE excluded_genres END WHERE id = :loc"
                ),
                {**params, "loc": location.id},
            )
        profile_version, plan_version = await _write_versions(
            conn, tenant_id, user_id, business_id, profile, overrides, s.id, new_profile=True
        )
        await conn.execute(
            text(
                "UPDATE onboarding_session SET status = 'confirmed', confirmed_at = now(), updated_at = now(),"
                " pending = NULL WHERE id = :i"
            ),
            {"i": s.id},
        )
        await conn.execute(
            text(
                "INSERT INTO audit_log (tenant_id, actor, action, target) VALUES (:t, :a, :x, :g)"
            ),
            {
                "t": tenant_id,
                "a": str(user_id),
                "x": "onboarding.confirm",
                "g": str(business_id),
            },
        )
        plan = await current_plan(conn)
    return {
        "business_id": str(business_id),
        "profile_version": profile_version,
        "plan_version": plan_version,
        "plan": plan,
    }


async def set_overrides(
    deps: Deps, tenant_id: UUID, user_id: UUID, overrides: dict[str, bool]
) -> dict[str, Any]:
    """The owner switched modules on or off: a new plan version from the same profile."""
    overrides = clean_overrides(overrides)
    async with transaction(deps.engine, tenant_id=tenant_id, user_id=user_id) as conn:
        business_id = await _first_business(conn)
        row = None
        if business_id is not None:
            row = (
                await conn.execute(
                    text(
                        "SELECT profile FROM business_profile WHERE business_id = :b ORDER BY version DESC LIMIT 1"
                    ),
                    {"b": business_id},
                )
            ).first()
        if business_id is None or row is None:
            raise OnboardingError("Tell Nigiwai about your business first.", 409)
        profile = om.Profile.model_validate(row.profile)
        await _write_versions(
            conn, tenant_id, user_id, business_id, profile, overrides, None, new_profile=False
        )
        await conn.execute(
            text(
                "INSERT INTO audit_log (tenant_id, actor, action, target) VALUES (:t, :a, :x, :g)"
            ),
            {"t": tenant_id, "a": str(user_id), "x": "plan.update", "g": str(business_id)},
        )
        plan = await current_plan(conn)
    assert plan is not None
    return plan


async def plan_of(deps: Deps, tenant_id: UUID) -> dict[str, Any] | None:
    async with transaction(deps.engine, tenant_id=tenant_id) as conn:
        return await current_plan(conn)
