"""Liveness and readiness. Neither reveals versions or configuration."""

from __future__ import annotations

from fastapi import APIRouter, Response
from sqlalchemy import text

from ..deps import State

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """The process is up. Used by the container's liveness probe."""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(state: State, response: Response) -> dict[str, object]:
    """Ready only when the database and Redis answer. The Qloo link is reported but does not fail readiness:
    the product degrades (local picker, cached answers) when Qloo is down."""
    checks: dict[str, str] = {}
    try:
        async with state.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "down"
    try:
        await state.redis.ping()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "down"
    checks["qloo"] = "configured" if state.guard is not None else "no key"
    ok = checks["database"] == "ok" and checks["redis"] == "ok"
    if not ok:
        response.status_code = 503
    return {"status": "ready" if ok else "not ready", "checks": checks}
