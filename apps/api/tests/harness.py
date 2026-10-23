"""Helpers shared by the API tests: settings, the World, owners and venues."""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Any

import httpx
import psycopg
from fakeqloo import FakeQloo
from fastapi import FastAPI
from nigiwai_api.settings import Settings

ROOT = Path(__file__).resolve().parents[3]
ADMIN_DSN = os.environ.get(
    "NIGIWAI_TEST_ADMIN_DSN", "postgresql://nigiwai:nigiwai-dev-only@127.0.0.1:55432/postgres"
)
TEST_DB = "nigiwai_test"
APP_URL = f"postgresql+asyncpg://nigiwai_app:nigiwai-app-dev-only@127.0.0.1:55432/{TEST_DB}"
ADMIN_URL_ASYNC = f"postgresql+asyncpg://nigiwai:nigiwai-dev-only@127.0.0.1:55432/{TEST_DB}"
REDIS_URL = os.environ.get("NIGIWAI_TEST_REDIS_URL", "redis://127.0.0.1:56379/15")
SECRET = "test-secret-key-that-is-long-enough-for-production-rules"
PASSWORD = "a-long-passphrase-9"
WorldFactory = Callable[..., AbstractAsyncContextManager["World"]]


def admin_connect() -> psycopg.Connection[Any]:
    return psycopg.connect(ADMIN_DSN.rsplit("/", 1)[0] + f"/{TEST_DB}", autocommit=True)


def make_settings(**over: Any) -> Settings:
    base: dict[str, Any] = {
        "env": "test",
        "database_url": APP_URL,
        "redis_url": REDIS_URL,
        "secret_key": SECRET,
        "min_completion_seconds": 0.0,
        "public_base_url": "https://nigiwai.test",
    }
    base.update(over)
    return Settings(**base)


class World:
    """The running app, a fake Qloo, and a way to make independent browsers (each with its own cookie jar)."""

    def __init__(self, app: FastAPI, qloo: FakeQloo, settings: Settings) -> None:
        self.app = app
        self.qloo = qloo
        self.settings = settings
        self._clients: list[httpx.AsyncClient] = []

    def client(self) -> httpx.AsyncClient:
        c = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app, raise_app_exceptions=False),
            base_url="http://test",
            follow_redirects=False,
        )
        self._clients.append(c)
        return c

    async def aclose(self) -> None:
        for c in self._clients:
            await c.aclose()


# ---- helpers ----------------------------------------------------------------------------------------------------
class Owner:
    """A signed-in owner: a client with the session cookie, plus the CSRF header every write needs."""

    def __init__(self, client: httpx.AsyncClient, me: dict[str, Any]) -> None:
        self.client = client
        self.me = me
        self.tenant_id: str = me["tenants"][0]["id"]
        self.headers = {"x-csrf-token": me["csrf_token"]}

    def url(self, path: str) -> str:
        return f"/v1/tenants/{self.tenant_id}{path}"

    async def post(self, path: str, **kw: Any) -> httpx.Response:
        return await self.client.post(self.url(path), headers=self.headers, **kw)

    async def put(self, path: str, **kw: Any) -> httpx.Response:
        return await self.client.put(self.url(path), headers=self.headers, **kw)

    async def get(self, path: str, **kw: Any) -> httpx.Response:
        return await self.client.get(self.url(path), **kw)


async def sign_up(world: World, email: str | None = None, business: str = "The Lantern") -> Owner:
    email = email or f"owner-{uuid.uuid4().hex[:8]}@example.com"
    client = world.client()
    r = await client.post(
        "/v1/auth/signup", json={"email": email, "password": PASSWORD, "business_name": business}
    )
    assert r.status_code == 201, r.text
    return Owner(client, r.json())


class Venue:
    """A business with one located QR point and a published survey, ready for guests."""

    def __init__(
        self, owner: Owner, business_id: str, location_id: str, qr: dict[str, Any], token: str
    ) -> None:
        self.owner = owner
        self.business_id = business_id
        self.location_id = location_id
        self.qr = qr
        self.token = token


async def make_venue(
    owner: Owner,
    *,
    questions: dict[str, Any] | None = None,
    reward: dict[str, Any] | None = None,
    publish: bool = True,
) -> Venue:
    b = await owner.post(
        "/businesses", json={"name": "The Lantern", "type": "live_music_venue", "currency": "GBP"}
    )
    assert b.status_code == 201, b.text
    business_id = b.json()["id"]
    loc = await owner.post(
        f"/businesses/{business_id}/locations",
        json={"name": "Main room", "lat": 51.5, "lon": -0.12, "timezone": "Europe/London"},
    )
    assert loc.status_code == 201, loc.text
    location_id = loc.json()["id"]
    qr = await owner.post(f"/locations/{location_id}/qr-points", json={"label": "Bar end"})
    assert qr.status_code == 201, qr.text
    payload: dict[str, Any] = {"questions": questions or {}, "publish": publish}
    if reward:
        payload["reward"] = reward
    s = await owner.put(f"/businesses/{business_id}/survey", json=payload)
    assert s.status_code == 200, s.text
    token = qr.json()["url"].rsplit("/", 1)[1]
    return Venue(owner, business_id, location_id, qr.json(), token)


def seed_entities(admin: psycopg.Connection[Any], rows: list[tuple[str, str, str]]) -> None:
    """(entity_id, type urn, name) -> qloo_entity rows, as if earlier searches had registered them."""
    for entity_id, type_urn, name in rows:
        admin.execute(
            "INSERT INTO qloo_entity (entity_id, type, types, name_nfc) VALUES (%s, %s, %s, %s)"
            " ON CONFLICT DO NOTHING",
            (entity_id, type_urn, [type_urn], name),
        )
