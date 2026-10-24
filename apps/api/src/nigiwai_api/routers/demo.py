"""Judge mode (PRD M25): the public demo venues, readable and usable without an account.

The routes mirror the owner's (`/soundcheck`, `/suggestions`, `/map`, `/brief` ...) under `/v1/public/demo/{slug}`, so the same
pages serve both. What differs is who may do what: a visitor can look at everything the demo venue has, check any act
(rate-limited, with a daily cap for the whole site, because each new check calls Qloo), and download the brief. A visitor
cannot rebuild suggestions, share a brief or send feedback, and cannot reach any venue that is not in the demo list: the
database refuses a demo row that points anywhere else, and every route below resolves the venue from that list only.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import StringConstraints

from ..deps import State
from ..schemas import Strict
from ..services import brief as brief_service
from ..services import compare as compare_service
from ..services import demo as demo_service
from ..services import mapdata
from ..services import soundcheck as service
from ..services.brief_pdf import render
from .public import limit

router = APIRouter(prefix="/v1/public/demo", tags=["demo"])

EntityId = Annotated[str, StringConstraints(min_length=36, max_length=36)]
Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9-]{2,40}$")]
PDF_HEADERS = {"Cache-Control": "public, max-age=300", "X-Content-Type-Options": "nosniff"}

READ = ("demo-read", 240, 600.0)
# Each new check calls Qloo, so it is limited per network and for the whole site per day.
RUN = ("demo-run", 8, 600.0)
SEARCH = ("demo-search", 40, 60.0)
COMPARE = ("demo-compare", 8, 600.0)
DAY = 86400.0
BUSY = "The demo is busy. Please try again in a little while."


class SoundcheckIn(Strict):
    entity_id: EntityId
    basis: Literal["guests", "lineup"] | None = None


def _clean(doc: dict[str, Any]) -> dict[str, Any]:
    """What a visitor may be sent about an act: our own score and the names, not Qloo's descriptive fields."""
    out = dict(doc)
    cand = out.get("candidate")
    if isinstance(cand, dict):
        out["candidate"] = {k: v for k, v in cand.items() if k not in ("description", "popularity")}
    if "popularity" in out:
        out.pop("popularity")
    return out


async def _site_cap(state: Any, name: str, count: int) -> None:
    if await state.limiter.check_all([(f"{name}:site", count, DAY)]):
        raise HTTPException(status_code=429, detail=BUSY)


async def _venue(state: Any, slug: str) -> dict[str, Any]:
    found = await demo_service.venue(state.engine, slug)
    if found is None:
        raise HTTPException(status_code=404, detail="not found")
    if found["status"] != "ready":
        raise HTTPException(
            status_code=503,
            detail="This demo venue is not available right now. Please try again later.",
        )
    return found


def _guard(state: Any) -> Any:
    if state.guard is None:
        raise HTTPException(
            status_code=503,
            detail="Qloo is not configured on this server, so checks are unavailable.",
        )
    return state.guard


def _public(v: dict[str, Any]) -> dict[str, Any]:
    return {
        "slug": v["slug"],
        "name": v["name"],
        "city": v["city"],
        "blurb": v["blurb"],
        "summary": v["summary"],
        "refreshed_at": v["refreshed_at"],
    }


@router.get("")
async def venues(request: Request, state: State) -> list[dict[str, Any]]:
    await limit(state, request, [READ])
    return await demo_service.listing(state.engine)


@router.get("/{slug}")
async def one_venue(slug: Slug, request: Request, state: State) -> dict[str, Any]:
    await limit(state, request, [READ])
    return _public(await _venue(state, slug))


@router.get("/{slug}/soundcheck/basis")
async def basis(slug: Slug, request: Request, state: State) -> dict[str, Any]:
    await limit(state, request, [READ])
    v = await _venue(state, slug)
    return await service.basis_status(state.engine, v["tenant_id"], v["business_id"])


@router.get("/{slug}/soundcheck/search")
async def search(
    slug: Slug, request: Request, state: State, q: str = Query(min_length=2, max_length=80)
) -> dict[str, Any]:
    await limit(state, request, [SEARCH])
    v = await _venue(state, slug)
    await _site_cap(state, "demo-search", state.settings.demo_searches_per_day)
    out = await state.picker.search(q, ["artist"], tenant_id=v["tenant_id"], allow_live=True)
    found: dict[str, Any] = out.model_dump()
    return found


@router.post("/{slug}/soundcheck")
async def run(slug: Slug, body: SoundcheckIn, request: Request, state: State) -> dict[str, Any]:
    await limit(state, request, [RUN])
    v = await _venue(state, slug)
    await _site_cap(state, "demo-run", state.settings.demo_runs_per_day)
    try:
        doc = await service.run(
            state.engine,
            _guard(state),
            v["tenant_id"],
            v["business_id"],
            body.entity_id,
            prefer=body.basis,
        )
    except service.SoundcheckError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    return _clean(doc)


@router.get("/{slug}/soundchecks")
async def recent(slug: Slug, request: Request, state: State) -> list[dict[str, Any]]:
    """The checks the demo was built with, not other visitors' checks."""
    await limit(state, request, [READ])
    v = await _venue(state, slug)
    sug = await service.suggestions(state.engine, v["tenant_id"], v["business_id"])
    result = (sug or {}).get("result")
    if not result:
        return []
    acts = [*result["top"], *([result["wildcard"]] if result["wildcard"] else [])]
    return [
        {
            "id": a["soundcheck_id"],
            "entity_id": a["entity_id"],
            "name": a["name"],
            "basis": result["basis"]["kind"],
            "status": "ok",
            "score": a["score"],
            "band": a["band"],
            "created_at": result["generated_at"],
        }
        for a in acts
    ]


@router.get("/{slug}/soundchecks/{soundcheck_id}")
async def one(slug: Slug, soundcheck_id: UUID, request: Request, state: State) -> dict[str, Any]:
    await limit(state, request, [READ])
    v = await _venue(state, slug)
    doc = await service.get(state.engine, v["tenant_id"], v["business_id"], soundcheck_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="not found")
    return _clean(doc)


@router.get("/{slug}/soundchecks/{soundcheck_id}/calls")
async def calls(
    slug: Slug, soundcheck_id: UUID, request: Request, state: State
) -> list[dict[str, Any]]:
    await limit(state, request, [READ])
    v = await _venue(state, slug)
    found = await service.calls_for(state.engine, v["tenant_id"], v["business_id"], soundcheck_id)
    if found is None:
        raise HTTPException(status_code=404, detail="not found")
    return found


@router.get("/{slug}/soundchecks/{soundcheck_id}/compare")
async def compare(
    slug: Slug, soundcheck_id: UUID, request: Request, state: State
) -> dict[str, Any]:
    await limit(state, request, [COMPARE])
    v = await _venue(state, slug)
    if not await compare_service.exists(state.engine, v["tenant_id"], soundcheck_id):
        await _site_cap(state, "demo-compare", state.settings.demo_compares_per_day)
    doc = await compare_service.build(
        state.engine,
        state.guard,
        state.llm,
        state.limiter,
        state.settings.llm_daily_limit,
        v["tenant_id"],
        v["business_id"],
        soundcheck_id,
    )
    if doc is None:
        raise HTTPException(status_code=404, detail="not found")
    return doc


@router.get("/{slug}/suggestions")
async def suggestions(slug: Slug, request: Request, state: State) -> dict[str, Any] | None:
    await limit(state, request, [READ])
    v = await _venue(state, slug)
    sug = await service.suggestions(state.engine, v["tenant_id"], v["business_id"])
    if sug is None or not sug.get("result"):
        return sug
    result = dict(sug["result"])
    for key in ("top",):
        result[key] = [{k: x for k, x in a.items() if k != "popularity"} for a in result[key]]
    if result.get("wildcard"):
        result["wildcard"] = {k: x for k, x in result["wildcard"].items() if k != "popularity"}
    return {**sug, "result": result}


@router.get("/{slug}/map")
async def crowd_map(
    slug: Slug,
    request: Request,
    state: State,
    period: str = Query(default="all", pattern="^(7d|4w|all)$"),
) -> dict[str, Any]:
    await limit(state, request, [READ])
    v = await _venue(state, slug)
    doc = await mapdata.build(
        state.engine, state.guard, state.geocoder, v["tenant_id"], v["business_id"], period
    )
    if doc is None:
        raise HTTPException(status_code=404, detail="not found")
    return doc


@router.get("/{slug}/map/around")
async def around(slug: Slug, request: Request, state: State) -> dict[str, Any]:
    await limit(state, request, [READ])
    v = await _venue(state, slug)
    doc = await mapdata.around_for(state.engine, state.guard, v["tenant_id"], v["business_id"])
    if doc is None:
        raise HTTPException(status_code=404, detail="not found")
    return doc


async def _brief(state: Any, v: dict[str, Any]) -> dict[str, Any]:
    doc = await brief_service.build(state.engine, v["tenant_id"], v["business_id"])
    if doc is None:
        raise HTTPException(status_code=404, detail="not found")
    return doc


@router.get("/{slug}/brief")
async def get_brief(slug: Slug, request: Request, state: State) -> dict[str, Any]:
    await limit(state, request, [READ])
    return await _brief(state, await _venue(state, slug))


@router.get("/{slug}/brief.pdf")
async def get_brief_pdf(slug: Slug, request: Request, state: State) -> Response:
    await limit(state, request, [READ])
    doc = await _brief(state, await _venue(state, slug))
    name = re.sub(r"[^a-z0-9]+", "-", doc["venue"]["business"].lower()).strip("-") or "venue"
    return Response(
        render(doc),
        media_type="application/pdf",
        headers={
            **PDF_HEADERS,
            "Content-Disposition": f'attachment; filename="booking-brief-{name}-{doc["date"]}.pdf"',
        },
    )
