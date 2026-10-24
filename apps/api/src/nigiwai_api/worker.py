"""The background worker: drains the job queue. Run it next to the API (`python -m nigiwai_api.worker`) or let the API
start one in-process (`NIGIWAI_EMBEDDED_WORKER=true`, the default outside production).

A job is claimed with SKIP LOCKED so several workers never take the same one, runs inside the job's tenant scope, and is
retried a few times with a growing delay. A job a crashed worker left `running` is reclaimed after ten minutes.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any
from uuid import UUID

from qloo_guard import QlooGuard
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from .services import lineup, tribes

log = logging.getLogger("nigiwai.worker")

POLL_SECONDS = 2.0
MAX_ATTEMPTS = 4
STALE_AFTER_MINUTES = 10
NIGHTLY_EVERY = 900.0  # seconds between sweeps that queue businesses whose groups are a day old


async def claim(engine: AsyncEngine) -> Any | None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE job SET state = 'pending', locked_at = NULL"
                " WHERE state = 'running' AND locked_at < now() - make_interval(mins => :mins)"
            ),
            {"mins": STALE_AFTER_MINUTES},
        )
        return (
            await conn.execute(
                text(
                    "UPDATE job SET state = 'running', locked_at = now(), attempts = attempts + 1"
                    " WHERE id = (SELECT id FROM job WHERE state = 'pending' AND run_after <= now()"
                    "             ORDER BY run_after, id LIMIT 1 FOR UPDATE SKIP LOCKED)"
                    " RETURNING id, kind, tenant_id, business_id, payload, attempts"
                )
            )
        ).first()


async def finish(engine: AsyncEngine, job_id: int, error: str | None, attempts: int) -> None:
    async with engine.begin() as conn:
        if error is None:
            await conn.execute(
                text(
                    "UPDATE job SET state = 'done', finished_at = now(), last_error = NULL WHERE id = :i"
                ),
                {"i": job_id},
            )
        elif attempts >= MAX_ATTEMPTS:
            await conn.execute(
                text(
                    "UPDATE job SET state = 'failed', finished_at = now(), last_error = :e WHERE id = :i"
                ),
                {"i": job_id, "e": error[:500]},
            )
        else:
            delay = 30 * attempts**2  # seconds: 30, 120, 270
            await conn.execute(
                text(
                    "UPDATE job SET state = 'pending', locked_at = NULL, last_error = :e,"
                    " run_after = now() + make_interval(secs => :d) WHERE id = :i"
                ),
                {"i": job_id, "e": error[:500], "d": delay},
            )


async def run_job(
    engine: AsyncEngine, guard: QlooGuard | None, job: Any, mb: lineup.MusicBrainz | None
) -> None:
    if job.kind == "recompute_tribes":
        force = bool((job.payload or {}).get("force"))
        outcome = await tribes.recompute(
            engine, guard, UUID(str(job.tenant_id)), UUID(str(job.business_id)), force=force
        )
        log.info(
            "recompute %s: stored=%s state=%s n=%s (%s)",
            job.business_id,
            outcome.stored,
            outcome.state,
            outcome.n,
            outcome.reason,
        )
    elif job.kind == "build_lineup":
        if mb is None:
            raise RuntimeError("no MusicBrainz client configured")
        doc = await lineup.build(
            engine, guard, UUID(str(job.tenant_id)), UUID(str(job.business_id)), mb
        )
        log.info(
            "lineup %s: %s (%s events)",
            job.business_id,
            doc.get("state"),
            (doc.get("events") or {}).get("used"),
        )
    else:
        raise ValueError(f"unknown job kind {job.kind!r}")


async def work_once(
    engine: AsyncEngine, guard: QlooGuard | None, mb: lineup.MusicBrainz | None = None
) -> bool:
    """Claim and run one job. True when there was one (so the caller loops again without sleeping)."""
    job = await claim(engine)
    if job is None:
        return False
    try:
        await run_job(engine, guard, job, mb)
    except Exception as exc:
        log.exception("job %s failed", job.id)
        await finish(engine, job.id, f"{type(exc).__name__}: {exc}", job.attempts)
    else:
        await finish(engine, job.id, None, job.attempts)
    return True


async def sweep_stale_businesses(engine: AsyncEngine) -> int:
    """Queue a recompute for every business whose latest groups are a day old and that has newer responses."""
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                "SELECT enqueue_recompute(b.tenant_id, b.id, interval '0 seconds')"
                " FROM business b"
                " WHERE EXISTS (SELECT 1 FROM tribe_version v WHERE v.business_id = b.id"
                "               AND v.created_at < now() - interval '24 hours')"
                "   AND NOT EXISTS (SELECT 1 FROM tribe_version v WHERE v.business_id = b.id"
                "                   AND v.created_at >= now() - interval '24 hours')"
            )
        )
        return result.rowcount


async def run_forever(
    engine: AsyncEngine,
    guard: QlooGuard | None,
    stop: asyncio.Event | None = None,
    mb: lineup.MusicBrainz | None = None,
) -> None:
    stop = stop or asyncio.Event()
    last_sweep = 0.0
    loop = asyncio.get_running_loop()
    while not stop.is_set():
        try:
            if loop.time() - last_sweep > NIGHTLY_EVERY:
                last_sweep = loop.time()
                await sweep_stale_businesses(engine)
            if await work_once(engine, guard, mb):
                continue
        except Exception:
            log.exception("worker loop error")
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=POLL_SECONDS)


def main() -> None:  # pragma: no cover - the process entry point
    import signal

    from .app import build_state
    from .settings import get_settings

    async def go() -> None:
        state, tasks = await build_state(get_settings())
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(
                NotImplementedError
            ):  # Windows has no signal handlers on the loop
                loop.add_signal_handler(sig, stop.set)
        try:
            await run_forever(state.engine, state.guard, stop, state.musicbrainz)
        finally:
            for t in tasks:
                t.cancel()
            await state.engine.dispose()

    logging.basicConfig(level=logging.INFO)
    asyncio.run(go())


if __name__ == "__main__":  # pragma: no cover
    main()
