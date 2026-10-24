"""Ask Nigiwai (PRD M12). A question is answered as a stream of events (steps, Qloo calls, then the validated answer) so
the page is never silent while the model works; the answer is stored, and the Qloo calls behind it can be reopened."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import StringConstraints

from ..deps import State, Tenant, Writer
from ..schemas import Strict
from ..services import ask as service

log = logging.getLogger("nigiwai.ask")

router = APIRouter(prefix="/v1/tenants/{tenant_id}/businesses/{business_id}", tags=["ask"])

STREAM_HEADERS = {
    "Cache-Control": "no-store",
    "X-Accel-Buffering": "no",
    "X-Content-Type-Options": "nosniff",
}


class AskIn(Strict):
    question: Annotated[str, StringConstraints(min_length=1, max_length=service.QUESTION_MAX)]
    mode: Literal["crowd", "culture"]


def _event(name: str, data: dict[str, Any]) -> str:
    return f"event: {name}\ndata: {json.dumps(data)}\n\n"


@router.post("/ask")
async def ask(business_id: UUID, body: AskIn, state: State, access: Writer) -> StreamingResponse:
    if await state.limiter.check_all([(f"ask-burst:{access.user_id}", 10, 600.0)]):
        raise HTTPException(
            status_code=429, detail="Too many questions at once. Wait a moment and try again."
        )
    try:
        checked = await service.preflight(
            state.engine,
            state.llm,
            state.limiter,
            tenant_id=access.tenant_id,
            business_id=business_id,
            question=body.question,
            mode=body.mode,
            daily_limit=state.settings.ask_daily_limit,
        )
    except service.AskError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc

    queue: asyncio.Queue[tuple[str, dict[str, Any]] | None] = asyncio.Queue()

    async def emit(name: str, data: dict[str, Any]) -> None:
        await queue.put((name, data))

    async def work() -> None:
        try:
            await service.ask(
                state.engine,
                state.guard,
                state.llm,
                state.limiter,
                tenant_id=access.tenant_id,
                user_id=access.user_id,
                business_id=business_id,
                question=body.question,
                mode=body.mode,
                daily_limit=state.settings.ask_daily_limit,
                emit=emit,
                checked=checked,
            )
        except service.AskError as exc:
            await queue.put(("error", {"message": str(exc), "status": exc.status}))
        except Exception:
            log.exception("ask failed")
            await queue.put(
                ("error", {"message": "Something went wrong on our side.", "status": 500})
            )
        finally:
            await queue.put(None)

    task = asyncio.create_task(work())

    async def stream() -> AsyncIterator[str]:
        try:
            yield _event("start", {"mode": body.mode})
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=15.0)
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if item is None:
                    break
                yield _event(*item)
            yield _event("done", {})
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(stream(), media_type="text/event-stream", headers=STREAM_HEADERS)


@router.get("/ask")
async def recent(business_id: UUID, state: State, access: Tenant) -> list[dict[str, Any]]:
    return await service.recent(state.engine, access.tenant_id, business_id)


@router.get("/ask/{answer_id}")
async def one(business_id: UUID, answer_id: UUID, state: State, access: Tenant) -> dict[str, Any]:
    doc = await service.get(state.engine, access.tenant_id, business_id, answer_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="not found")
    return doc


@router.get("/ask/{answer_id}/trace")
async def trace(
    business_id: UUID, answer_id: UUID, state: State, access: Tenant
) -> list[dict[str, Any]]:
    found = await service.trace(state.engine, access.tenant_id, business_id, answer_id)
    if found is None:
        raise HTTPException(status_code=404, detail="not found")
    return found
