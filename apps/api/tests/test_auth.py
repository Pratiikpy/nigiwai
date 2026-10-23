"""Accounts: signup, login, logout, sessions, CSRF. Every state, including the careless and the hostile ones."""

from __future__ import annotations

import asyncio
from typing import Any

import psycopg
from harness import PASSWORD, World, sign_up


async def test_signup_creates_account_tenant_and_owner_membership(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world, "ada@example.com", "Ada's Bar")
    assert owner.me["email"] == "ada@example.com"
    assert owner.me["tenants"] == [{"id": owner.tenant_id, "name": "Ada's Bar", "role": "owner"}]
    row = admin.execute(
        "SELECT role FROM membership WHERE tenant_id = %s", (owner.tenant_id,)
    ).fetchall()
    assert row == [("owner",)]


async def test_signup_stores_an_argon2id_hash_never_the_password(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    await sign_up(world, "hash@example.com")
    (stored,) = admin.execute("SELECT password_hash FROM app_user").fetchone()  # type: ignore[misc]
    assert stored.startswith("$argon2id$")
    assert PASSWORD not in stored


async def test_session_cookie_is_httponly_samesite_lax(world: World) -> None:
    c = world.client()
    r = await c.post(
        "/v1/auth/signup",
        json={"email": "c@example.com", "password": PASSWORD, "business_name": "C"},
    )
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "path=/" in cookie


async def test_duplicate_email_is_a_409_and_case_insensitive(world: World) -> None:
    await sign_up(world, "dup@example.com")
    r = await world.client().post(
        "/v1/auth/signup",
        json={"email": "DUP@Example.com", "password": PASSWORD, "business_name": "X"},
    )
    assert r.status_code == 409


async def test_concurrent_duplicate_signups_leave_one_account_and_no_500(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    body = {"email": "race@example.com", "password": PASSWORD, "business_name": "Race"}
    results = await asyncio.gather(
        *[world.client().post("/v1/auth/signup", json=body) for _ in range(6)]
    )
    codes = sorted(r.status_code for r in results)
    assert codes.count(201) == 1 and set(codes) <= {201, 409}, codes
    assert admin.execute("SELECT count(*) FROM app_user").fetchone() == (1,)
    assert admin.execute("SELECT count(*) FROM tenant").fetchone() == (1,)


async def test_weak_and_junk_passwords_are_refused(world: World) -> None:
    c = world.client()
    for password in ("short", "x" * 201, "password1234", "a@example.com-longer", ""):
        r = await c.post(
            "/v1/auth/signup",
            json={"email": "a@example.com", "password": password, "business_name": "A"},
        )
        assert r.status_code == 422, (password, r.text)


async def test_signup_rejects_junk_bodies(world: World) -> None:
    c = world.client()
    for body in (
        {},
        {"email": "not-an-email", "password": PASSWORD, "business_name": "A"},
        {"email": "a@example.com", "password": PASSWORD, "business_name": ""},
        {"email": "a@example.com", "password": PASSWORD, "business_name": "A", "role": "admin"},
        {"email": "a@example.com", "password": PASSWORD, "business_name": "x" * 500},
    ):
        r = await c.post("/v1/auth/signup", json=body)
        assert r.status_code == 422, (body, r.text)
    assert (
        await c.post(
            "/v1/auth/signup", content=b"{not json", headers={"content-type": "application/json"}
        )
    ).status_code == 422


async def test_validation_errors_do_not_echo_the_submitted_value(world: World) -> None:
    r = await world.client().post(
        "/v1/auth/signup",
        json={"email": "a@example.com", "password": "hunter2-secret-xyz", "business_name": ""},
    )
    assert r.status_code == 422
    assert "hunter2-secret-xyz" not in r.text


async def test_login_succeeds_and_gives_a_working_session(world: World) -> None:
    await sign_up(world, "login@example.com")
    c = world.client()
    r = await c.post("/v1/auth/login", json={"email": "LOGIN@example.com", "password": PASSWORD})
    assert r.status_code == 200
    me = await c.get("/v1/auth/me")
    assert me.status_code == 200 and me.json()["email"] == "login@example.com"


async def test_login_failure_is_identical_for_unknown_email_and_wrong_password(
    world: World,
) -> None:
    await sign_up(world, "known@example.com")
    c = world.client()
    wrong = await c.post(
        "/v1/auth/login", json={"email": "known@example.com", "password": "wrong-password-1"}
    )
    unknown = await c.post(
        "/v1/auth/login", json={"email": "nobody@example.com", "password": "wrong-password-1"}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


async def test_login_is_rate_limited_per_account(world: World) -> None:
    await sign_up(world, "brute@example.com")
    c = world.client()
    codes = []
    for _ in range(12):
        r = await c.post(
            "/v1/auth/login", json={"email": "brute@example.com", "password": "wrong-password-1"}
        )
        codes.append(r.status_code)
    assert codes[:8] == [401] * 8
    assert 429 in codes[8:]
    # While locked out, even the right password is refused: the limit is not bypassed by guessing correctly late.
    assert (
        await c.post("/v1/auth/login", json={"email": "brute@example.com", "password": PASSWORD})
    ).status_code == 429


async def test_me_without_a_session_is_401(world: World) -> None:
    c = world.client()
    assert (await c.get("/v1/auth/me")).status_code == 401
    c.cookies.set("nigiwai_session", "not-a-real-token")
    assert (await c.get("/v1/auth/me")).status_code == 401


async def test_state_changing_calls_need_the_csrf_token(world: World) -> None:
    owner = await sign_up(world)
    body = {"name": "No token", "type": "bar"}
    missing = await owner.client.post(owner.url("/businesses"), json=body)
    wrong = await owner.client.post(
        owner.url("/businesses"), json=body, headers={"x-csrf-token": "forged"}
    )
    ok = await owner.post("/businesses", json=body)
    assert missing.status_code == 403 and wrong.status_code == 403
    assert ok.status_code == 201


async def test_csrf_token_from_another_session_is_refused(world: World) -> None:
    a = await sign_up(world, "a1@example.com")
    b = await sign_up(world, "b1@example.com")
    r = await a.client.post(
        a.url("/businesses"), json={"name": "X", "type": "bar"}, headers=b.headers
    )
    assert r.status_code == 403


async def test_logout_kills_the_session_server_side(world: World) -> None:
    owner = await sign_up(world)
    stolen = owner.client.cookies.get("nigiwai_session")
    assert (await owner.client.post("/v1/auth/logout", headers=owner.headers)).status_code == 204
    assert (await owner.client.get("/v1/auth/me")).status_code == 401
    replay = world.client()
    replay.cookies.set("nigiwai_session", stolen)
    assert (await replay.get("/v1/auth/me")).status_code == 401


async def test_expired_sessions_are_refused(world: World, admin: psycopg.Connection[Any]) -> None:
    owner = await sign_up(world)
    admin.execute("UPDATE app_session SET expires_at = now() - interval '1 second'")
    assert (await owner.client.get("/v1/auth/me")).status_code == 401


async def test_signup_is_rate_limited_per_network(world: World) -> None:
    codes = []
    for i in range(12):
        r = await world.client().post(
            "/v1/auth/signup",
            json={"email": f"flood{i}@example.com", "password": PASSWORD, "business_name": "F"},
        )
        codes.append(r.status_code)
    assert codes[:10] == [201] * 10
    assert set(codes[10:]) == {429}
