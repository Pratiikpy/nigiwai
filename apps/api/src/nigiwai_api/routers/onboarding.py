"""Onboarding (PRD M1) and the dashboard plan it produces, plus the address search the interview uses. Tenant-scoped like
every owner route; anyone in the account can read, only someone who can change the account can answer or confirm."""

from __future__ import annotations

import logging
from typing import Annotated, Any, Literal
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import Field, StringConstraints

from ..deps import AppState, State, Tenant, TenantAccess, Writer
from ..schemas import Name, Strict
from ..services import onboarding as service

log = logging.getLogger("nigiwai.onboarding")

router = APIRouter(prefix="/v1/tenants/{tenant_id}", tags=["onboarding"])


class StartIn(Strict):
    mode: Literal["auto", "form"] = "auto"
    restart: bool = False


class AnswerIn(Strict):
    field: Annotated[str, StringConstraints(min_length=1, max_length=40)]
    value: Any = None
    place: dict[str, Any] | None = None


class SayIn(Strict):
    text: Annotated[str, StringConstraints(min_length=1, max_length=service.OWNER_TEXT_MAX * 2)]


class SkipIn(Strict):
    field: Annotated[str, StringConstraints(min_length=1, max_length=40)]


class ConfirmIn(Strict):
    name: Name
    timezone: str | None = Field(default=None, max_length=64)
    overrides: dict[str, bool] = Field(default_factory=dict, max_length=20)


class PlanIn(Strict):
    overrides: dict[str, bool] = Field(max_length=20)


def _deps(state: AppState) -> service.Deps:
    return service.Deps(
        state.engine, state.llm, state.limiter, state.settings.onboarding_daily_limit
    )


def _refused(exc: service.OnboardingError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=str(exc))


async def _throttle(state: AppState, access: TenantAccess) -> None:
    if await state.limiter.check_all([(f"onboard:{access.user_id}", 60, 600.0)]):
        raise HTTPException(status_code=429, detail="Too many answers at once. Wait a moment.")


@router.get("/onboarding")
async def current(state: State, access: Tenant) -> dict[str, Any]:
    return await service.get(_deps(state), access.tenant_id)


@router.post("/onboarding")
async def start(body: StartIn, state: State, access: Writer) -> dict[str, Any]:
    await _throttle(state, access)
    try:
        return await service.start(
            _deps(state), access.tenant_id, access.user_id, mode=body.mode, restart=body.restart
        )
    except service.OnboardingError as exc:
        raise _refused(exc) from exc


@router.post("/onboarding/{session_id}/answer")
async def answer(session_id: UUID, body: AnswerIn, state: State, access: Writer) -> dict[str, Any]:
    await _throttle(state, access)
    try:
        return await service.answer(
            _deps(state), access.tenant_id, session_id, body.field, body.value, body.place
        )
    except service.OnboardingError as exc:
        raise _refused(exc) from exc


@router.post("/onboarding/{session_id}/say")
async def say(session_id: UUID, body: SayIn, state: State, access: Writer) -> dict[str, Any]:
    await _throttle(state, access)
    try:
        return await service.say(_deps(state), access.tenant_id, session_id, body.text)
    except service.OnboardingError as exc:
        raise _refused(exc) from exc


@router.post("/onboarding/{session_id}/skip")
async def skip(session_id: UUID, body: SkipIn, state: State, access: Writer) -> dict[str, Any]:
    await _throttle(state, access)
    try:
        return await service.skip(_deps(state), access.tenant_id, session_id, body.field)
    except service.OnboardingError as exc:
        raise _refused(exc) from exc


@router.post("/onboarding/{session_id}/confirm")
async def confirm(
    session_id: UUID, body: ConfirmIn, state: State, access: Writer
) -> dict[str, Any]:
    await _throttle(state, access)
    try:
        return await service.confirm(
            _deps(state),
            access.tenant_id,
            access.user_id,
            session_id,
            name=body.name,
            timezone=body.timezone,
            overrides=body.overrides,
        )
    except service.OnboardingError as exc:
        raise _refused(exc) from exc


@router.post("/onboarding/{session_id}/abandon", status_code=204)
async def abandon(session_id: UUID, state: State, access: Writer) -> None:
    try:
        await service.abandon(_deps(state), access.tenant_id, access.user_id, session_id)
    except service.OnboardingError as exc:
        raise _refused(exc) from exc


@router.get("/plan")
async def plan(state: State, access: Tenant) -> dict[str, Any] | None:
    return await service.plan_of(_deps(state), access.tenant_id)


@router.put("/plan")
async def set_plan(body: PlanIn, state: State, access: Writer) -> dict[str, Any]:
    try:
        return await service.set_overrides(
            _deps(state), access.tenant_id, access.user_id, body.overrides
        )
    except service.OnboardingError as exc:
        raise _refused(exc) from exc


@router.get("/places/search")
async def search_places(
    state: State,
    access: Tenant,
    q: Annotated[str, Query(min_length=3, max_length=200)],
) -> dict[str, Any]:
    """Matches for an address, from OpenStreetMap. Asked only when the owner presses the button, never as they type."""
    if await state.limiter.check_all([(f"places:{access.user_id}", 20, 600.0)]):
        raise HTTPException(status_code=429, detail="Too many searches. Wait a moment.")
    try:
        places = await state.geocoder.search(q)
    except httpx.HTTPError as exc:
        log.warning("address search failed (%s)", type(exc).__name__)
        raise HTTPException(
            status_code=503,
            detail="The address search is not answering. Try again, or set the position on Your venue.",
        ) from exc
    return {"places": places}
