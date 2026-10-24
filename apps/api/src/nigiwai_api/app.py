"""Application factory and lifespan: engine, Redis, the Qloo Guard and its Postgres-backed stores."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import redis.asyncio as aioredis
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from qloo_guard import QlooConfig, QlooGuard, build_guard, key_fingerprint, read_key
from qloo_guard.ratelimit import RedisTokenBucket
from qloo_guard.transports import Transport
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .db import assert_rls_effective, make_engine
from .deps import AppState
from .ratelimit import RateLimiter
from .routers import (
    ask,
    atlas,
    auth,
    brief,
    demo,
    drafts,
    grow,
    health,
    moves,
    onboarding,
    owner,
    public,
    soundcheck,
    today,
    trust,
)
from .routers import map as map_router
from .services.geocode import Geocoder
from .services.guard_stores import PgBackedLedger, PgRecorder, PgRegistry, PgResponseStore
from .services.lineup import MusicBrainz
from .services.llm import build_llm
from .services.picker import PickerService
from .settings import Settings, get_settings

log = logging.getLogger("nigiwai")

MAX_BODY_BYTES = 128 * 1024


class BodyLimit:
    """Reject request bodies over a fixed size before any handler reads them (declared length or streamed)."""

    def __init__(self, app: ASGIApp, limit: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.limit = limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > self.limit:
            await self._reject(send)
            return
        seen = 0
        too_big = False

        async def limited() -> Message:
            nonlocal seen, too_big
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > self.limit:
                    too_big = True
                    return {"type": "http.request", "body": b"", "more_body": False}
            return message

        started = False

        async def guarded_send(message: Message) -> None:
            nonlocal started
            if too_big and not started:
                started = True
                await self._reject(send)
                return
            if too_big:
                return
            started = True
            await send(message)

        await self.app(scope, limited, guarded_send)

    @staticmethod
    async def _reject(send: Send) -> None:
        body = b'{"detail":"request body too large"}'
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


def qloo_config(settings: Settings) -> QlooConfig:
    return QlooConfig(
        base_url=settings.qloo_base_url,
        key_file=settings.qloo_key_file,
        transport=settings.qloo_transport,
        mode=settings.qloo_mode,
        harness_home=settings.qloo_harness_home,
        rest_first_purposes=tuple(
            p.strip() for p in settings.qloo_rest_first.split(",") if p.strip()
        ),
    )


async def build_state(
    settings: Settings, transports: list[Transport] | None = None
) -> tuple[AppState, list[asyncio.Task[Any]]]:
    """`transports` replaces the real Qloo transports; tests and replay tooling use it."""
    engine = make_engine(settings)
    await assert_rls_effective(engine)
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    tasks: list[asyncio.Task[Any]] = []
    config = qloo_config(settings)
    key = read_key(config)
    guard: QlooGuard | None = None
    ledger: PgBackedLedger | None = None
    if key or config.mode == "replay" or transports is not None:
        fingerprint = key_fingerprint(key) if key else "none"
        ledger = PgBackedLedger(engine, fingerprint)
        await ledger.load()
        guard = build_guard(
            config,
            store=PgResponseStore(engine, settings.secret_key),
            registry=PgRegistry(engine),
            ledger=ledger,
            limiter=RedisTokenBucket(
                redis, f"qloo:bucket:{fingerprint}", config.rate_per_second, config.burst
            ),
            recorder=PgRecorder(engine),
            api_key=key,
            transports=transports,
        )
        tasks.append(asyncio.create_task(ledger.run_flusher()))
    else:
        log.warning(
            "no Qloo key configured: the picker serves saved matches only and nothing calls Qloo"
        )
    musicbrainz = MusicBrainz(engine, settings.musicbrainz_url, settings.lineup_contact)
    limiter = RateLimiter(redis)
    llm = build_llm(
        settings.anthropic_key_file,
        settings.llm_model,
        base_url=settings.llm_base_url,
        timeout=settings.llm_timeout_seconds,
    )
    if settings.embedded_worker:
        from .worker import DemoRefresh, run_forever

        stop = asyncio.Event()
        demo_refresh = DemoRefresh(llm, limiter, settings.llm_daily_limit)
        tasks.append(
            asyncio.create_task(run_forever(engine, guard, stop, musicbrainz, demo_refresh))
        )
    state = AppState(
        settings=settings,
        engine=engine,
        redis=redis,
        limiter=limiter,
        guard=guard,
        ledger=ledger,
        picker=PickerService(engine, guard),
        musicbrainz=musicbrainz,
        geocoder=Geocoder(engine, settings.nominatim_url, settings.lineup_contact),
        llm=llm,
    )
    if state.llm is None:
        log.info("no model key configured: the AI-alone comparison will say so")
    return state, tasks


async def close_state(state: AppState, tasks: list[asyncio.Task[Any]]) -> None:
    """Stop the background tasks and close every connection `build_state` opened."""
    for task in tasks:
        task.cancel()
    for task in tasks:
        with contextlib.suppress(asyncio.CancelledError):
            await task
    if state.ledger is not None:
        with contextlib.suppress(Exception):
            await state.ledger.flush()
    if state.guard is not None:
        await state.guard.aclose()
    await state.musicbrainz.aclose()
    await state.geocoder.aclose()
    if state.llm is not None:
        await state.llm.aclose()
    await state.redis.aclose()
    await state.engine.dispose()


def create_app(
    settings: Settings | None = None, *, transports: list[Transport] | None = None
) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        state, tasks = await build_state(settings, transports)
        app.state.nigiwai = state
        try:
            yield
        finally:
            await close_state(state, tasks)

    app = FastAPI(
        title="Nigiwai API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None if settings.env == "production" else "/docs",
        redoc_url=None,
        openapi_url=None if settings.env == "production" else "/openapi.json",
    )
    app.add_middleware(BodyLimit)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["content-type", "x-csrf-token"],
        max_age=600,
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Field and message only: the submitted value is never echoed back.
        detail = [
            {
                "field": ".".join(str(p) for p in e["loc"][1:]) or str(e["loc"][0]),
                "message": e["msg"],
            }
            for e in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": detail})

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": "something went wrong on our side"})

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(owner.router)
    app.include_router(soundcheck.router)
    app.include_router(brief.router)
    app.include_router(brief.public)
    app.include_router(map_router.router)
    app.include_router(demo.router)
    app.include_router(today.router)
    app.include_router(ask.router)
    app.include_router(onboarding.router)
    app.include_router(moves.router)
    app.include_router(grow.router)
    app.include_router(atlas.router)
    app.include_router(drafts.router)
    app.include_router(trust.public)
    app.include_router(trust.owner)
    app.include_router(public.router)
    return app
