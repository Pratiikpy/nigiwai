"""The tools Ask Nigiwai's model may call (ARCHITECTURE 4.1).

Every tool is fixed: the model chooses which to call and with what, but it cannot reach Qloo, the database or the network
any other way, and it cannot make up what a tool returns. Qloo tools go through the Guard. A tool that names an entity
registers it as "seen" for this question, so the answer can later be checked: an item the model lists must have been
returned by one of these tools, and where it first appeared says whether Qloo surfaced it or the model proposed it.

Owner tools (`my_groups`, `my_hours`, `my_moves`) read the signed-in owner's own stored data and exist only in crowd mode.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any
from uuid import UUID

from qloo_guard import (
    INSIGHTS_BY_TYPE,
    AreaRef,
    CallContext,
    Entity,
    EntityType,
    GeoPoint,
    GuardError,
    PlaceCategory,
    PlaceInsights,
    QlooGuard,
    SearchRequest,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from ..db import transaction
from . import soundcheck, today

log = logging.getLogger("nigiwai.ask")

QLOO_BUDGET = 10  # calls the model may make through tools in one question; the trace allows a few more for probes
FIT_COST = 4  # a Soundcheck asks Qloo once per group, up to four groups
TAKE_MAX = 12

KINDS: dict[str, EntityType] = {
    "artist": EntityType.ARTIST,
    "movie": EntityType.MOVIE,
    "tv_show": EntityType.TV_SHOW,
    "book": EntityType.BOOK,
    "brand": EntityType.BRAND,
    "podcast": EntityType.PODCAST,
    "videogame": EntityType.VIDEOGAME,
}
PLACE_CATEGORIES: dict[str, PlaceCategory] = {c.name.lower(): c for c in PlaceCategory}
QLOO_TOOLS = ("resolve_entity", "related", "places_nearby", "verify_place", "fit_verdict")
OWNER_TOOLS = ("my_groups", "my_hours", "my_moves", "fit_verdict")


@dataclass
class Seen:
    """An entity some tool returned during this question."""

    entity_id: str
    name: str
    kind: str
    first_tool: str
    first_call: str
    tags: list[str] = field(default_factory=list)
    note: str | None = None


@dataclass
class Area:
    point: GeoPoint
    radius_m: int


@dataclass
class Run:
    """Everything one question carries: who is asking, what the tools have returned, and how much budget is left."""

    engine: AsyncEngine
    guard: QlooGuard | None
    tenant_id: UUID
    business_id: UUID
    mode: str
    ctx: CallContext | None
    venue: str
    type: str
    timezone: str
    address: str | None
    area: Area | None
    emit: Callable[[str, dict[str, Any]], Awaitable[None]]
    qloo_left: int = QLOO_BUDGET
    seen: dict[str, Seen] = field(default_factory=dict)
    known_names: set[str] = field(
        default_factory=set
    )  # names a tool gave that are not items (a group, a favourite)
    tools_called: list[str] = field(default_factory=list)
    trace_ids: list[str] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    qloo_unavailable: bool = False
    owner_data_used: bool = False
    qloo_used: bool = False


def kind_of(entity: Entity) -> str:
    return entity.primary_type.rsplit(":", 1)[-1] if entity.primary_type else "entity"


def similar(a: str, b: str) -> float:
    def norm(s: str) -> str:
        return re.sub(r"[^a-z0-9 ]+", "", s.casefold()).strip()

    return SequenceMatcher(None, norm(a), norm(b)).ratio()


def _clip(value: Any, limit: int) -> str:
    return " ".join(str(value).split())[:limit]


def _spend(run: Run, n: int) -> str | None:
    if run.guard is None or run.ctx is None:
        return "Qloo is not available on this server."
    if run.qloo_left < n:
        return "The Qloo call budget for this question is used up. Finish your answer with what you have."
    run.qloo_left -= n
    return None


async def _note_call(run: Run, tool: str, res: Any) -> str:
    call_id = str(res.call_id)
    run.qloo_used = True
    run.calls.append(
        {
            "tool": tool,
            "call_id": call_id,
            "status": res.status,
            "cache": res.cache,
            "results": len(res.result_entity_ids),
        }
    )
    await run.emit(
        "qloo_call",
        {
            "tool": tool,
            "status": res.status,
            "cache": res.cache,
            "results": len(res.result_entity_ids),
            "left": run.qloo_left,
        },
    )
    return call_id


def _see(run: Run, e: Entity, tool: str, call_id: str, note: str | None = None) -> dict[str, Any]:
    kind = kind_of(e)
    if e.entity_id not in run.seen:
        run.seen[e.entity_id] = Seen(
            e.entity_id, e.name, kind, tool, call_id, [t.name for t in e.tags[:5]], note
        )
    out: dict[str, Any] = {"id": e.entity_id, "name": e.name, "type": kind}
    if e.tags:
        out["tags"] = [t.name for t in e.tags[:4]]
    if e.distance_m is not None:
        out["distance_m"] = round(e.distance_m)
    if e.address:
        out["address"] = e.address
    if e.release_year:
        out["year"] = e.release_year
    return out


def _failure(run: Run, res: Any) -> dict[str, Any] | None:
    """The tool result for a Qloo call that did not give an answer, or None when it did."""
    if res.ok:
        return None
    if res.status in ("unavailable", "budget_exhausted"):
        run.qloo_unavailable = True
        return {
            "error": "Qloo could not answer this just now. Finish your answer with what you already have."
        }
    if res.status == "rejected":
        return {"error": "Qloo's rules refused that request. Try a simpler one."}
    return {"items": [], "note": "Qloo returned nothing for that."}


def _seeds(run: Run, raw: Any) -> tuple[tuple[str, ...], str | None]:
    if not isinstance(raw, list) or not raw or len(raw) > 5:
        return (), "seeds must be one to five entity ids that earlier tools returned."
    ids = tuple(dict.fromkeys(str(s) for s in raw))
    unknown = [s for s in ids if s not in run.seen]
    if unknown:
        return (
            (),
            "A seed was not returned by any tool in this question. Use resolve_entity to find it first.",
        )
    return ids, None


async def resolve_entity(run: Run, args: dict[str, Any]) -> dict[str, Any]:
    kind = str(args.get("type", ""))
    query = _clip(args.get("text", ""), 120)
    if kind not in KINDS or not query:
        return {"error": f"Give some text and a type from: {', '.join(KINDS)}."}
    if (err := _spend(run, 1)) or run.guard is None or run.ctx is None:
        return {"error": err or "Qloo is not available."}
    try:
        res = await run.guard.search(
            SearchRequest(query=query, types=(KINDS[kind],), take=5), run.ctx
        )
    except GuardError as exc:
        log.info("ask resolve_entity refused: %s", exc)
        return {"error": "Qloo could not search for that."}
    call_id = await _note_call(run, "resolve_entity", res)
    if (failed := _failure(run, res)) is not None:
        return failed
    return {"items": [_see(run, e, "resolve_entity", call_id) for e in res.items[:5]]}


async def related(run: Run, args: dict[str, Any]) -> dict[str, Any]:
    kind = str(args.get("type", ""))
    if kind not in KINDS:
        return {"error": f"type must be one of: {', '.join(KINDS)}."}
    seeds, bad = _seeds(run, args.get("seeds"))
    if bad:
        return {"error": bad}
    take = max(1, min(TAKE_MAX, int(args.get("take", 8) or 8)))
    if (err := _spend(run, 1)) or run.guard is None or run.ctx is None:
        return {"error": err or "Qloo is not available."}
    request_cls = INSIGHTS_BY_TYPE[KINDS[kind]]
    try:
        verdicts = await run.guard.ensure_eligible(seeds, run.ctx)
        usable = tuple(s for s in seeds if verdicts.get(s) is True)
        if not usable:
            return {"error": "Qloo cannot use those as a starting point. Try other seeds."}
        request: Any = request_cls(signal_entities=usable, take=take)
        res = await run.guard.insights(request, run.ctx)
    except GuardError as exc:
        log.info("ask related refused: %s", exc)
        return {"error": "Qloo could not answer that."}
    except ValueError as exc:
        return {"error": f"That request is not valid: {_clip(exc, 120)}"}
    call_id = await _note_call(run, "related", res)
    if (failed := _failure(run, res)) is not None:
        return failed
    if kind == "brand" and any(run.seen[s].kind == "artist" for s in seeds):
        run.warnings.append(
            "Brand suggestions seeded from music were weaker than an AI alone in our tests: check them before acting."
        )
    if kind == "book":
        run.warnings.append("Qloo's coverage of books is thin: check titles before acting.")
    return {"items": [_see(run, e, "related", call_id) for e in res.items[:take]]}


def _in_area(run: Run, e: Entity) -> bool:
    if run.area is None or e.location is None:
        return False
    return run.area.point.distance_m(e.location) <= run.area.radius_m * 1.02


async def places_nearby(run: Run, args: dict[str, Any]) -> dict[str, Any]:
    if run.area is None:
        return {"error": "This venue has no position yet, so places nearby cannot be searched."}
    category = PLACE_CATEGORIES.get(str(args.get("category", "")).lower())
    if category is None:
        return {"error": f"category must be one of: {', '.join(PLACE_CATEGORIES)}."}
    seeds: tuple[str, ...] = ()
    if args.get("seeds"):
        seeds, bad = _seeds(run, args["seeds"])
        if bad:
            return {"error": bad}
    take = max(1, min(15, int(args.get("take", 10) or 10)))
    if (err := _spend(run, 1)) or run.guard is None or run.ctx is None:
        return {"error": err or "Qloo is not available."}
    try:
        if seeds:
            verdicts = await run.guard.ensure_eligible(seeds, run.ctx)
            seeds = tuple(s for s in seeds if verdicts.get(s) is True)
        area = AreaRef(center=run.area.point, radius_m=run.area.radius_m)
        res = await run.guard.insights(
            PlaceInsights(area=area, category=category, signal_entities=seeds, take=take), run.ctx
        )
    except GuardError as exc:
        log.info("ask places_nearby refused: %s", exc)
        return {"error": "Qloo could not answer that."}
    call_id = await _note_call(run, "places_nearby", res)
    if (failed := _failure(run, res)) is not None:
        return failed
    open_places = [e for e in res.items if e.is_closed is not True]
    closed = len(res.items) - len(open_places)
    if not run.timezone.startswith("America/"):
        run.warnings.append(
            "Place data outside the United States is thinner: check each place is open before acting."
        )
    out: dict[str, Any] = {
        "items": [_see(run, e, "places_nearby", call_id) for e in open_places[:take]]
    }
    if closed:
        out["dropped_closed"] = closed
    out["area"] = f"within {run.area.radius_m} m of the venue"
    return out


async def verify_place(run: Run, args: dict[str, Any]) -> dict[str, Any]:
    if run.area is None:
        return {
            "error": "This venue has no position yet, so places cannot be checked against its area."
        }
    name = _clip(args.get("name", ""), 120)
    if not name:
        return {"error": "Give the name of the place."}
    if (err := _spend(run, 1)) or run.guard is None or run.ctx is None:
        return {"error": err or "Qloo is not available."}
    try:
        res = await run.guard.search(
            SearchRequest(query=name, types=(EntityType.PLACE,), take=5), run.ctx
        )
    except GuardError as exc:
        log.info("ask verify_place refused: %s", exc)
        return {"error": "Qloo could not search for that."}
    call_id = await _note_call(run, "verify_place", res)
    if (failed := _failure(run, res)) is not None:
        return {"found": False, **failed} if "items" in failed else failed
    for e in res.items:
        if similar(name, e.name) >= 0.85 and _in_area(run, e) and e.is_closed is not True:
            return {"found": True, "place": _see(run, e, "verify_place", call_id)}
    return {
        "found": False,
        "note": "Qloo does not know a place by that name inside this venue's area.",
    }


async def fit_verdict(run: Run, args: dict[str, Any]) -> dict[str, Any]:
    entity_id = str(args.get("entity_id", ""))
    seen = run.seen.get(entity_id)
    if seen is None or seen.kind != "artist":
        return {"error": "fit_verdict takes an artist id that an earlier tool returned."}
    if (err := _spend(run, FIT_COST)) or run.guard is None:
        return {"error": err or "Qloo is not available."}
    try:
        doc = await soundcheck.run(run.engine, run.guard, run.tenant_id, run.business_id, entity_id)
    except soundcheck.SoundcheckError as exc:
        return {"error": _clip(exc, 240)}
    except GuardError:
        return {"error": "Qloo could not answer that."}
    run.qloo_used = True
    run.owner_data_used = True
    async with transaction(run.engine, tenant_id=run.tenant_id) as conn:
        row = (
            await conn.execute(
                text("SELECT trace_ids FROM soundcheck WHERE id = :i"), {"i": UUID(doc["id"])}
            )
        ).first()
    for t in row.trace_ids if row else []:
        if t not in run.trace_ids:
            run.trace_ids.append(str(t))
    await run.emit(
        "qloo_call",
        {
            "tool": "fit_verdict",
            "status": "ok",
            "cache": "n/a",
            "results": 0,
            "left": run.qloo_left,
        },
    )
    out: dict[str, Any] = {
        "name": seen.name,
        "status": doc["status"],
        "provisional": bool(doc.get("provisional")),
    }
    if doc["status"] == "ok":
        out |= {
            "score": doc["score"],
            "range": doc["band"],
            "groups": [
                {"label": g["label"], "share": round(g["share"], 2), "fit": round(g["fit"], 2)}
                for g in doc["groups"]
                if g["status"] == "scored"
            ],
            "watch": doc.get("watch", [])[:2],
            "note": "Fit with this crowd, not a sales forecast.",
        }
    else:
        out["reason"] = _clip(doc.get("reason", ""), 240)
    return out


async def my_groups(run: Run, args: dict[str, Any]) -> dict[str, Any]:
    try:
        basis = await soundcheck.load_basis(run.engine, run.tenant_id, run.business_id)
    except soundcheck.SoundcheckError as exc:
        return {"error": _clip(exc, 240)}
    run.owner_data_used = True
    groups = []
    for g in basis.groups:
        run.known_names.add(g.label)
        run.known_names.update(g.seed_names)
        groups.append(
            {
                "label": g.label,
                "share_pct": round(100 * g.share),
                "size": round(g.size),
                "favourites": list(g.seed_names)[:5],
            }
        )
    return {
        "read_from": "guests" if basis.kind == "guests" else "public lineups",
        "provisional": bool(basis.crowd.provisional),
        "label": "measured" if basis.kind == "guests" else "modelled",
        "groups": groups,
    }


async def my_hours(run: Run, args: dict[str, Any]) -> dict[str, Any]:
    board = await today.build(run.engine, run.tenant_id, run.business_id)
    if board is None:
        return {"error": "No venue found."}
    run.owner_data_used = True
    h = board["hours"]
    return {
        "scans": board["status"]["scans"],
        "opening_hours_set": h["set"],
        "quietest": [{"when": w["text"], "scans": w["scans"]} for w in h["quiet"]],
        "early_look": h["early"],
        "label": "measured",
        "note": "Scans are guests who chose to answer, not a headcount.",
    }


async def my_moves(run: Run, args: dict[str, Any]) -> dict[str, Any]:
    async with transaction(run.engine, tenant_id=run.tenant_id) as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT title, started_on FROM move WHERE business_id = :b ORDER BY started_on DESC LIMIT 10"
                ),
                {"b": run.business_id},
            )
        ).all()
    run.owner_data_used = True
    return {
        "moves": [{"title": r.title, "started_on": r.started_on.isoformat()} for r in rows],
        "label": "measured",
    }


Handler = Callable[[Run, dict[str, Any]], Awaitable[dict[str, Any]]]
HANDLERS: dict[str, Handler] = {
    "resolve_entity": resolve_entity,
    "related": related,
    "places_nearby": places_nearby,
    "verify_place": verify_place,
    "fit_verdict": fit_verdict,
    "my_groups": my_groups,
    "my_hours": my_hours,
    "my_moves": my_moves,
}

_ID_LIST = {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 5}
SPECS: dict[str, dict[str, Any]] = {
    "resolve_entity": {
        "name": "resolve_entity",
        "description": "Find an artist, film, show, book, brand, podcast or game in Qloo by name. Returns real entities with ids. Use it before using anything as a seed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "maxLength": 120},
                "type": {"type": "string", "enum": list(KINDS)},
            },
            "required": ["text", "type"],
        },
    },
    "related": {
        "name": "related",
        "description": "Items of one type that Qloo links to the seeds you give it (ids from earlier tool results). Works across types, for example artists for a film.",
        "input_schema": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": list(KINDS)},
                "seeds": _ID_LIST,
                "take": {"type": "integer", "minimum": 1, "maximum": TAKE_MAX},
            },
            "required": ["type", "seeds"],
        },
    },
    "places_nearby": {
        "name": "places_nearby",
        "description": "Places of one category inside the venue's own area (an exact radius), optionally leaning to the taste of seeds. Closed places are dropped.",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "enum": list(PLACE_CATEGORIES)},
                "seeds": {**_ID_LIST, "minItems": 0},
                "take": {"type": "integer", "minimum": 1, "maximum": 15},
            },
            "required": ["category"],
        },
    },
    "verify_place": {
        "name": "verify_place",
        "description": "Check whether Qloo knows a place of this name inside the venue's area. Use it for any place you want to mention that no other tool returned.",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string", "maxLength": 120}},
            "required": ["name"],
        },
    },
    "fit_verdict": {
        "name": "fit_verdict",
        "description": "How well one artist fits this venue's own crowd, 0 to 100, with the range and each group's fit. Costs four Qloo calls. Artist ids from earlier tool results only.",
        "input_schema": {
            "type": "object",
            "properties": {"entity_id": {"type": "string"}},
            "required": ["entity_id"],
        },
    },
    "my_groups": {
        "name": "my_groups",
        "description": "The owner's crowd: its groups, how big each is, and the favourites that define them.",
        "input_schema": {"type": "object", "properties": {}},
    },
    "my_hours": {
        "name": "my_hours",
        "description": "How many guests have scanned and which three-hour stretches of the week are quietest.",
        "input_schema": {"type": "object", "properties": {}},
    },
    "my_moves": {
        "name": "my_moves",
        "description": "Changes the owner logged recently (an act booked, a menu change).",
        "input_schema": {"type": "object", "properties": {}},
    },
}

ANSWER_SPEC: dict[str, Any] = {
    "name": "answer",
    "description": "Give the final answer. Call it exactly once, when you are done. Items may only be entity ids that tool results in this conversation returned.",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {
                "type": "string",
                "maxLength": 400,
                "description": "The answer in one or two plain sentences.",
            },
            "items": {
                "type": "array",
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "properties": {
                        "entity_id": {"type": "string"},
                        "reason": {"type": "string", "maxLength": 200},
                    },
                    "required": ["entity_id", "reason"],
                },
            },
            "evidence": {
                "type": "array",
                "maxItems": 6,
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string", "enum": ["measured", "observed", "modelled"]},
                        "text": {"type": "string", "maxLength": 300},
                    },
                    "required": ["label", "text"],
                },
            },
            "what_would_change": {
                "type": "array",
                "maxItems": 3,
                "items": {"type": "string", "maxLength": 200},
            },
            "not_enough_data": {
                "type": ["object", "null"],
                "properties": {
                    "reason": {"type": "string", "maxLength": 300},
                    "unlock": {
                        "type": "array",
                        "maxItems": 4,
                        "items": {"type": "string", "maxLength": 200},
                    },
                },
            },
        },
        "required": ["verdict", "items", "evidence", "what_would_change"],
    },
}


def tools_for(mode: str) -> list[dict[str, Any]]:
    names = [n for n in QLOO_TOOLS if n != "fit_verdict" or mode == "crowd"]
    if mode == "crowd":
        names += ["my_groups", "my_hours", "my_moves"]
    return [SPECS[n] for n in names] + [ANSWER_SPEC]


def local_date_text(tz_name: str) -> str:
    from zoneinfo import ZoneInfo

    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("UTC")
    return datetime.now(tz).strftime("%A %d %B %Y")
