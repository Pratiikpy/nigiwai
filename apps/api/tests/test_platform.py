"""Platform behaviour: health, headers, limits, settings, the Guard's Postgres stores."""

from __future__ import annotations

import asyncio
from typing import Any

import psycopg
import pytest
import redis.asyncio as aioredis
from fakeqloo import artist
from harness import WorldFactory, make_settings, make_venue, sign_up
from nigiwai_api.app import create_app
from nigiwai_api.ratelimit import RateLimiter
from nigiwai_api.settings import DEV_SECRET, Settings
from pydantic import ValidationError


async def test_health_endpoints(world: Any) -> None:
    c = world.client()
    assert (await c.get("/healthz")).json() == {"status": "ok"}
    ready = await c.get("/readyz")
    assert ready.status_code == 200
    assert ready.json() == {
        "status": "ready",
        "checks": {"database": "ok", "redis": "ok", "qloo": "configured"},
    }


async def test_readiness_fails_when_redis_is_down_and_says_which(
    world: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken() -> None:
        raise ConnectionError("down")

    monkeypatch.setattr(world.app.state.nigiwai.redis, "ping", broken)
    r = await world.client().get("/readyz")
    assert (
        r.status_code == 503
        and r.json()["checks"]["redis"] == "down"
        and r.json()["checks"]["database"] == "ok"
    )


async def test_without_a_qloo_key_readiness_still_passes_and_says_so(
    make_world: WorldFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("QLOO_API_KEY", raising=False)
    monkeypatch.delenv("NIGIWAI_QLOO_KEY_FILE", raising=False)
    async with make_world(with_qloo=False) as world:
        r = await world.client().get("/readyz")
        assert r.status_code == 200 and r.json()["checks"]["qloo"] == "no key"
        assert world.app.state.nigiwai.guard is None


async def test_security_headers_on_every_response(world: Any) -> None:
    c = world.client()
    for path in ("/healthz", "/v1/auth/me", "/nonexistent"):
        r = await c.get(path)
        assert r.headers["x-content-type-options"] == "nosniff", path
        assert r.headers["referrer-policy"] == "no-referrer", path
        assert r.headers["cache-control"] == "no-store", path
        assert r.headers["x-frame-options"] == "DENY", path
        assert "frame-ancestors 'none'" in r.headers["content-security-policy"], path


async def test_unknown_routes_and_methods(world: Any) -> None:
    c = world.client()
    assert (await c.get("/v1/nope")).status_code == 404
    assert (await c.delete("/v1/public/response")).status_code == 405
    assert (await c.put("/healthz")).status_code == 405


async def test_cors_allows_only_configured_origins(world: Any) -> None:
    c = world.client()
    ok = await c.options(
        "/v1/auth/login",
        headers={
            "origin": "http://localhost:3000",
            "access-control-request-method": "POST",
            "access-control-request-headers": "content-type,x-csrf-token",
        },
    )
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert ok.headers.get("access-control-allow-credentials") == "true"
    bad = await c.options(
        "/v1/auth/login",
        headers={"origin": "https://evil.example", "access-control-request-method": "POST"},
    )
    assert "access-control-allow-origin" not in bad.headers


async def test_an_unexpected_error_is_a_plain_500_that_leaks_nothing(
    world: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom(*_: Any, **__: Any) -> Any:
        raise RuntimeError("secret internals: password=hunter2")

    monkeypatch.setattr(world.app.state.nigiwai.limiter, "check_all", boom)
    c = world.client()
    r = await c.post("/v1/auth/login", json={"email": "a@example.com", "password": "whatever-123"})
    assert r.status_code == 500 and r.json() == {"detail": "something went wrong on our side"}
    assert "hunter2" not in r.text


def test_production_refuses_weak_or_default_secrets() -> None:
    base = {"env": "production", "cookie_secure": True}
    with pytest.raises(ValidationError):
        Settings(**base)  # default secret
    with pytest.raises(ValidationError):
        Settings(**base, secret_key="short")
    with pytest.raises(ValidationError):
        Settings(**base, secret_key=DEV_SECRET)
    with pytest.raises(ValidationError):
        Settings(env="production", secret_key="x" * 40, cookie_secure=False)
    assert Settings(**base, secret_key="x" * 40).env == "production"


async def test_api_docs_are_off_in_production(
    admin: psycopg.Connection[Any], redis_clean: aioredis.Redis
) -> None:
    settings = make_settings(env="production", cookie_secure=True, secret_key="p" * 48)
    app = create_app(settings)
    assert app.docs_url is None and app.openapi_url is None


async def test_sliding_window_limit_is_atomic_under_concurrency(
    redis_clean: aioredis.Redis,
) -> None:
    limiter = RateLimiter(redis_clean)
    results = await asyncio.gather(*[limiter.allow("burst-test", 10, 30.0) for _ in range(60)])
    assert sum(results) == 10  # exactly the limit gets through, however the requests interleave
    # A different key has its own budget.
    assert await limiter.allow("other-key", 10, 30.0)


async def test_nonce_ids_are_single_use_under_concurrency(redis_clean: aioredis.Redis) -> None:
    limiter = RateLimiter(redis_clean)
    results = await asyncio.gather(*[limiter.consume_nonce("same-id", 60) for _ in range(30)])
    assert sum(results) == 1


async def test_guard_writes_traces_calls_registry_and_ledger_to_postgres(
    world: Any, admin: psycopg.Connection[Any]
) -> None:
    world.qloo.catalogue = [
        artist(
            "Ledger Band",
            year=2010,
            tags=[("urn:tag:genre:qloo:folk", "Folk"), ("urn:tag:genre:qloo:indie", "Indie")],
        )
    ]
    owner = await sign_up(world)
    venue = await make_venue(owner)
    guest = world.client()
    page = (await guest.get(f"/v1/public/survey/{venue.token}")).json()
    await guest.post(
        "/v1/public/picker", json={"token": venue.token, "nonce": page["nonce"], "q": "ledger"}
    )
    entity = admin.execute("SELECT type, name_nfc, props FROM qloo_entity").fetchone()
    assert entity == (
        "urn:entity:artist",
        "Ledger Band",
        {"description": "Ledger Band, an invented act.", "release_year": 2010},
    )
    (tags,) = admin.execute("SELECT tags FROM qloo_entity").fetchone()  # type: ignore[misc]
    assert tags == [
        ["urn:tag:genre:qloo:folk", "Folk", "urn:tag:genre:qloo"],
        ["urn:tag:genre:qloo:indie", "Indie", "urn:tag:genre:qloo"],
    ]
    assert admin.execute("SELECT count(*) FROM qloo_call WHERE purpose = 'picker'").fetchone() == (
        1,
    )
    await world.app.state.nigiwai.ledger.flush()
    ledger = admin.execute(
        "SELECT purpose, calls_live, key_fingerprint FROM quota_ledger"
    ).fetchall()
    assert ledger == [("picker", 1, "none")]
    # The key itself never appears anywhere Postgres can see, and only a fingerprint is recorded.
    cached = admin.execute("SELECT count(*) FROM qloo_response").fetchone()
    assert cached == (1,)
    body = admin.execute("SELECT body FROM qloo_response").fetchone()[0]  # type: ignore[index]
    assert b"Ledger Band" not in bytes(body)  # cached Qloo bodies are encrypted at rest


async def test_picker_cache_survives_a_restart_and_serves_without_calling_qloo(
    make_world: WorldFactory, admin: psycopg.Connection[Any]
) -> None:
    async with make_world() as first:
        first.qloo.catalogue = [artist("Persisted Act")]
        owner = await sign_up(first)
        venue = await make_venue(owner)
        guest = first.client()
        page = (await guest.get(f"/v1/public/survey/{venue.token}")).json()
        await guest.post(
            "/v1/public/picker",
            json={"token": venue.token, "nonce": page["nonce"], "q": "persisted"},
        )
        assert len(first.qloo.calls) == 1
    async with make_world() as second:
        second.qloo.catalogue = []  # Qloo would now return nothing: only the stored answer can satisfy this
        guest = second.client()
        page = (await guest.get(f"/v1/public/survey/{venue.token}")).json()
        out = (
            await guest.post(
                "/v1/public/picker",
                json={"token": venue.token, "nonce": page["nonce"], "q": "persisted"},
            )
        ).json()
        assert [i["name"] for i in out["items"]] == ["Persisted Act"]
        assert second.qloo.calls == []
