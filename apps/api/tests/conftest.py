"""Fixtures for the API tests: a fresh database migrated from scratch, a clean Redis database, and the real
application wired to a fake Qloo. These tests need the dev services (`just up`)."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import psycopg
import pytest
import pytest_asyncio
import redis.asyncio as aioredis
from alembic import command
from alembic.config import Config
from fakeqloo import FakeQloo
from harness import (
    ADMIN_DSN,
    REDIS_URL,
    ROOT,
    TEST_DB,
    World,
    WorldFactory,
    admin_connect,
    make_settings,
)
from nigiwai_api.app import create_app


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Everything under apps/api/tests needs Postgres and Redis (`just up`); the live ones also spend Qloo quota."""
    here = Path(__file__).parent
    for item in items:
        path = Path(str(item.fspath))
        if here in path.parents:
            item.add_marker(pytest.mark.integration)
            if "live" in path.parts:
                item.add_marker(pytest.mark.live)


@pytest.fixture(scope="session")
def database() -> Iterator[None]:
    """Drop and recreate the test database and run every migration, so each run proves a clean install.
    NIGIWAI_TEST_REUSE_DB=1 skips this for quick reruns and for mutation checks on the schema."""
    if os.environ.get("NIGIWAI_TEST_REUSE_DB") == "1":
        yield
        return
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
        conn.execute(f"CREATE DATABASE {TEST_DB}")
    cfg = Config(str(ROOT / "db" / "alembic.ini"))
    os.environ["NIGIWAI_DATABASE_URL_SYNC"] = (
        ADMIN_DSN.rsplit("/", 1)[0].replace("postgresql://", "postgresql+psycopg://")
        + f"/{TEST_DB}"
    )
    command.upgrade(cfg, "head")
    yield


@pytest.fixture
def admin(database: None) -> Iterator[psycopg.Connection[Any]]:
    """A superuser connection to the test database, for seeding and for reading what the app wrote."""
    with admin_connect() as conn:
        conn.execute(
            "TRUNCATE app_user, tenant, qloo_entity, qloo_response, trace, qloo_call, quota_ledger, external_cache,"
            " audit_log CASCADE"
        )
        yield conn


@pytest_asyncio.fixture
async def redis_clean() -> AsyncIterator[aioredis.Redis]:
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    await r.flushdb()
    yield r
    await r.flushdb()
    await r.aclose()


@pytest_asyncio.fixture
async def world(
    admin: psycopg.Connection[Any], redis_clean: aioredis.Redis
) -> AsyncIterator[World]:
    settings = make_settings()
    qloo = FakeQloo()
    app = create_app(settings, transports=[qloo])  # type: ignore[list-item]
    async with app.router.lifespan_context(app):
        w = World(app, qloo, settings)
        try:
            yield w
        finally:
            await w.aclose()


@pytest.fixture
def make_world(admin: psycopg.Connection[Any], redis_clean: aioredis.Redis) -> WorldFactory:
    """A world with custom settings or no Qloo at all."""

    @asynccontextmanager
    async def build(*, with_qloo: bool = True, **over: Any) -> AsyncIterator[World]:
        settings = make_settings(**over)
        qloo = FakeQloo()
        app = create_app(settings, transports=[qloo] if with_qloo else None)  # type: ignore[list-item]
        async with app.router.lifespan_context(app):
            w = World(app, qloo, settings)
            try:
                yield w
            finally:
                await w.aclose()

    return build
