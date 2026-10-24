"""Tenant isolation, checked at both layers: the HTTP API refuses, and Postgres refuses even if the API were wrong."""

from __future__ import annotations

import uuid
from typing import Any

import psycopg
import pytest
from harness import APP_URL, World, make_venue, sign_up
from nigiwai_api.db import assert_rls_effective, transaction
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.ext.asyncio import create_async_engine


async def test_a_member_of_another_tenant_gets_404_everywhere(world: World) -> None:
    a = await sign_up(world, "a@example.com", "A Venue")
    b = await sign_up(world, "b@example.com", "B Venue")
    venue = await make_venue(a)
    base = f"/v1/tenants/{a.tenant_id}"
    ids = {"b": venue.business_id, "l": venue.location_id, "q": venue.qr["id"]}
    reads = [
        f"{base}/businesses",
        f"{base}/businesses/{ids['b']}/locations",
        f"{base}/businesses/{ids['b']}/survey",
        f"{base}/businesses/{ids['b']}/stats",
        f"{base}/locations/{ids['l']}/qr-points",
        f"{base}/qr-points/{ids['q']}/poster.pdf",
    ]
    for url in reads:
        r = await b.client.get(url)
        assert r.status_code == 404, (url, r.status_code)
    writes = [
        ("post", f"{base}/businesses", {"name": "Hijack", "type": "bar"}),
        ("put", f"{base}/businesses/{ids['b']}", {"name": "Hijack", "type": "bar"}),
        ("post", f"{base}/businesses/{ids['b']}/locations", {"name": "Hijack"}),
        ("post", f"{base}/locations/{ids['l']}/qr-points", {"label": "Hijack"}),
        ("post", f"{base}/qr-points/{ids['q']}/rotate", None),
        ("post", f"{base}/qr-points/{ids['q']}/revoke", None),
        ("put", f"{base}/businesses/{ids['b']}/survey", {"questions": {}, "publish": True}),
        ("put", f"{base}/locations/{ids['l']}", {"name": "Hijack"}),
    ]
    for method, url, body in writes:
        r = await getattr(b.client, method)(
            url, headers=b.headers, **({"json": body} if body is not None else {})
        )
        assert r.status_code == 404, (method, url, r.status_code)
    # A's data is untouched.
    assert (await a.get("/businesses")).json()[0]["name"] == "The Lantern"


async def test_ids_from_another_tenant_do_not_work_inside_my_own_tenant(world: World) -> None:
    a = await sign_up(world, "a2@example.com")
    b = await sign_up(world, "b2@example.com")
    venue = await make_venue(a)
    # B uses B's own tenant path but A's business, location and QR ids.
    assert (await b.get(f"/businesses/{venue.business_id}/locations")).status_code == 404
    assert (
        await b.post(f"/businesses/{venue.business_id}/locations", json={"name": "x"})
    ).status_code == 404
    assert (
        await b.post(f"/locations/{venue.location_id}/qr-points", json={"label": "x"})
    ).status_code == 404
    assert (await b.post(f"/qr-points/{venue.qr['id']}/rotate")).status_code == 404
    assert (await b.put(f"/locations/{venue.location_id}", json={"name": "x"})).status_code == 404
    assert (await b.get(f"/businesses/{venue.business_id}/survey")).status_code == 404


async def test_unauthenticated_requests_to_tenant_routes_are_401(world: World) -> None:
    a = await sign_up(world, "a3@example.com")
    anon = world.client()
    assert (await anon.get(f"/v1/tenants/{a.tenant_id}/businesses")).status_code == 401
    assert (
        await anon.post(f"/v1/tenants/{a.tenant_id}/businesses", json={"name": "x", "type": "bar"})
    ).status_code == 401


async def test_non_uuid_tenant_or_ids_are_422_not_500(world: World) -> None:
    a = await sign_up(world, "a4@example.com")
    assert (await a.client.get("/v1/tenants/not-a-uuid/businesses")).status_code == 422
    assert (await a.get("/businesses/not-a-uuid/locations")).status_code == 422
    assert (await a.get(f"/businesses/{uuid.uuid4()}/locations")).status_code == 404


async def test_a_viewer_can_read_but_not_write(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world, "own@example.com")
    viewer = await sign_up(world, "view@example.com")
    venue = await make_venue(owner)
    admin.execute(
        "INSERT INTO membership (tenant_id, user_id, role) VALUES (%s, %s, 'viewer')",
        (owner.tenant_id, viewer.me["user_id"]),
    )
    base = f"/v1/tenants/{owner.tenant_id}"
    assert (await viewer.client.get(f"{base}/businesses")).status_code == 200
    qrs = (await viewer.client.get(f"{base}/locations/{venue.location_id}/qr-points")).json()
    assert qrs and qrs[0]["url"] is None  # a viewer never receives the survey secret
    for method, url, body in [
        ("post", f"{base}/businesses", {"name": "x", "type": "bar"}),
        ("post", f"{base}/locations/{venue.location_id}/qr-points", {"label": "x"}),
        ("post", f"{base}/qr-points/{venue.qr['id']}/rotate", None),
        (
            "put",
            f"{base}/businesses/{venue.business_id}/survey",
            {"questions": {}, "publish": True},
        ),
    ]:
        r = await getattr(viewer.client, method)(
            url, headers=viewer.headers, **({"json": body} if body is not None else {})
        )
        assert r.status_code == 403, (url, r.status_code)
    assert (
        await viewer.client.get(f"{base}/qr-points/{venue.qr['id']}/poster.pdf")
    ).status_code == 403


# ---- the database enforces the same boundary on its own --------------------------------------------------------
@pytest.fixture
async def app_engine(world: World):  # type: ignore[no-untyped-def]
    engine = create_async_engine(APP_URL)
    yield engine
    await engine.dispose()


async def test_rls_hides_other_tenants_rows_from_the_app_role(
    world: World, app_engine: Any
) -> None:
    a = await sign_up(world, "r1@example.com")
    b = await sign_up(world, "r2@example.com")
    await make_venue(a)
    async with transaction(
        app_engine, tenant_id=uuid.UUID(b.tenant_id), user_id=uuid.UUID(b.me["user_id"])
    ) as conn:
        for table in (
            "business",
            "location",
            "qr_point",
            "survey",
            "response",
            "pick",
            "audit_log",
        ):
            count = (await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()
            assert count == 0, table
    async with transaction(
        app_engine, tenant_id=uuid.UUID(a.tenant_id), user_id=uuid.UUID(a.me["user_id"])
    ) as conn:
        assert (await conn.execute(text("SELECT count(*) FROM business"))).scalar_one() == 1


async def test_with_no_tenant_set_the_app_role_sees_nothing(world: World, app_engine: Any) -> None:
    a = await sign_up(world, "r3@example.com")
    await make_venue(a)
    async with app_engine.begin() as conn:
        for table in ("business", "location", "qr_point", "survey", "response", "audit_log"):
            assert (await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one() == 0, (
                table
            )


async def test_writing_into_another_tenant_is_refused_by_the_database(
    world: World, app_engine: Any
) -> None:
    a = await sign_up(world, "r4@example.com")
    b = await sign_up(world, "r5@example.com")
    with pytest.raises((DBAPIError, ProgrammingError)):
        async with transaction(
            app_engine, tenant_id=uuid.UUID(b.tenant_id), user_id=uuid.UUID(b.me["user_id"])
        ) as conn:
            await conn.execute(
                text("INSERT INTO business (tenant_id, name, type) VALUES (:t, 'planted', 'bar')"),
                {"t": a.tenant_id},
            )


async def test_a_user_cannot_enrol_themselves_in_an_existing_tenant(
    world: World, app_engine: Any
) -> None:
    a = await sign_up(world, "v1@example.com")
    b = await sign_up(world, "v2@example.com")
    user_b = uuid.UUID(b.me["user_id"])
    # Scoped to A's tenant (as a bug or an injection might leave it), B inserts a membership for themselves.
    for scope_tenant in (uuid.UUID(a.tenant_id), uuid.UUID(b.tenant_id), None):
        with pytest.raises((DBAPIError, ProgrammingError)):
            async with transaction(app_engine, tenant_id=scope_tenant, user_id=user_b) as conn:
                await conn.execute(
                    text(
                        "INSERT INTO membership (tenant_id, user_id, role) VALUES (:t, :u, 'owner')"
                    ),
                    {"t": a.tenant_id, "u": user_b},
                )
    # Nor can they promote themselves inside their own tenant's rows to a different tenant, or read A's membership list.
    async with transaction(app_engine, tenant_id=uuid.UUID(b.tenant_id), user_id=user_b) as conn:
        rows = (await conn.execute(text("SELECT tenant_id FROM membership"))).all()
    assert {str(r.tenant_id) for r in rows} == {b.tenant_id}


async def test_create_tenant_function_refuses_a_different_user(
    world: World, app_engine: Any
) -> None:
    a = await sign_up(world, "f1@example.com")
    b = await sign_up(world, "f2@example.com")
    with pytest.raises((DBAPIError, ProgrammingError)):
        async with transaction(app_engine, user_id=uuid.UUID(a.me["user_id"])) as conn:
            await conn.execute(
                text("SELECT create_tenant('forged', :u)"), {"u": uuid.UUID(b.me["user_id"])}
            )


async def test_direct_tenant_insert_is_denied(world: World, app_engine: Any) -> None:
    a = await sign_up(world, "d1@example.com")
    with pytest.raises((DBAPIError, ProgrammingError)):
        async with transaction(app_engine, user_id=uuid.UUID(a.me["user_id"])) as conn:
            await conn.execute(text("INSERT INTO tenant (name) VALUES ('rogue')"))


async def test_audit_log_is_append_only(world: World, app_engine: Any) -> None:
    a = await sign_up(world, "au@example.com")
    await make_venue(a)
    scope = {"tenant_id": uuid.UUID(a.tenant_id), "user_id": uuid.UUID(a.me["user_id"])}
    async with transaction(app_engine, **scope) as conn:
        assert (await conn.execute(text("SELECT count(*) FROM audit_log"))).scalar_one() >= 4
    for statement in ("UPDATE audit_log SET action = 'x'", "DELETE FROM audit_log"):
        with pytest.raises((DBAPIError, ProgrammingError)):
            async with transaction(app_engine, **scope) as conn:
                await conn.execute(text(statement))


async def test_the_api_refuses_to_start_as_a_role_that_bypasses_rls(
    admin: psycopg.Connection[Any],
) -> None:
    owner_engine = create_async_engine(
        APP_URL.replace("nigiwai_app:nigiwai-app-dev-only", "nigiwai:nigiwai-dev-only")
    )
    try:
        with pytest.raises(RuntimeError, match="bypasses row-level security"):
            await assert_rls_effective(owner_engine)
    finally:
        await owner_engine.dispose()
    app_engine = create_async_engine(APP_URL)
    try:
        await assert_rls_effective(app_engine)  # the real application role passes
    finally:
        await app_engine.dispose()


# ---- the login tables are protected the same way ---------------------------------------------------------------
async def test_the_app_role_sees_only_its_own_login_and_sessions(
    world: World, app_engine: Any
) -> None:
    a = await sign_up(world, "login-a@example.com")
    b = await sign_up(world, "login-b@example.com")
    await world.client().post(
        "/v1/auth/login", json={"email": "login-b@example.com", "password": "a-long-passphrase-9"}
    )
    ua, ub = uuid.UUID(a.me["user_id"]), uuid.UUID(b.me["user_id"])
    async with transaction(app_engine, user_id=ua) as conn:
        assert (await conn.execute(text("SELECT email::text FROM app_user"))).scalars().all() == [
            "login-a@example.com"
        ]
        assert (
            await conn.execute(
                text("SELECT count(*) FROM app_session WHERE user_id = :b"), {"b": ub}
            )
        ).scalar_one() == 0
        assert (await conn.execute(text("SELECT count(*) FROM app_session"))).scalar_one() == 1
        # another person's login cannot be changed or removed, and cannot be created under a made-up identity
        for statement in (
            "UPDATE app_user SET password_hash = 'x' WHERE id = :b",
            "DELETE FROM app_user WHERE id = :b",
            "UPDATE app_session SET expires_at = now() WHERE user_id = :b",
            "DELETE FROM app_session WHERE user_id = :b",
        ):
            assert (await conn.execute(text(statement), {"b": ub})).rowcount == 0, statement
    with pytest.raises((DBAPIError, ProgrammingError)):
        async with transaction(app_engine, user_id=ua) as conn:
            await conn.execute(
                text(
                    "INSERT INTO app_user (id, email, password_hash) VALUES (gen_random_uuid(), 'made-up@example.com', 'x')"
                )
            )
    # with nobody signed in the tables are empty to the application role
    async with app_engine.begin() as conn:
        assert (await conn.execute(text("SELECT count(*) FROM app_user"))).scalar_one() == 0
        assert (await conn.execute(text("SELECT count(*) FROM app_session"))).scalar_one() == 0


async def test_the_lookups_made_before_anyone_is_signed_in_answer_one_key_each(
    world: World, app_engine: Any, admin: psycopg.Connection[Any]
) -> None:
    a = await sign_up(world, "lookup-a@example.com")
    await sign_up(world, "lookup-b@example.com")
    async with app_engine.begin() as conn:
        found = (
            await conn.execute(
                text("SELECT id, password_hash FROM auth_user_by_email('LOOKUP-A@example.com')")
            )
        ).all()
        assert [str(r.id) for r in found] == [a.me["user_id"]] and found[
            0
        ].password_hash.startswith("$argon2id$")
        assert (
            await conn.execute(
                text("SELECT count(*) FROM auth_user_by_email('nobody@example.com')")
            )
        ).scalar_one() == 0
        assert (
            await conn.execute(text("SELECT count(*) FROM auth_session(decode('00', 'hex'))"))
        ).scalar_one() == 0
    # the function takes one address: there is no way through it to list people
    for sql in (
        "SELECT count(*) FROM auth_user_by_email('%')",
        "SELECT count(*) FROM auth_user_by_email('')",
    ):
        async with app_engine.begin() as conn:
            assert (await conn.execute(text(sql))).scalar_one() == 0
    # a login that was deleted cannot be found, so it cannot sign in
    admin.execute("UPDATE app_user SET deleted_at = now() WHERE email = 'lookup-a@example.com'")
    async with app_engine.begin() as conn:
        assert (
            await conn.execute(
                text("SELECT count(*) FROM auth_user_by_email('lookup-a@example.com')")
            )
        ).scalar_one() == 0
    assert (
        await a.client.get("/v1/auth/me")
    ).status_code == 401  # and its open sessions stop working


async def test_the_worker_role_has_no_way_into_other_peoples_logins(world: World) -> None:
    await sign_up(world, "w@example.com")
    dsn = APP_URL.replace("postgresql+asyncpg://", "postgresql://").replace(
        "nigiwai_app:nigiwai-app-dev-only", "nigiwai_worker:nigiwai-worker-dev-only"
    )
    with psycopg.connect(dsn) as conn:
        assert conn.execute("SELECT count(*) FROM app_user").fetchone() == (0,)
        assert conn.execute("SELECT count(*) FROM app_session").fetchone() == (0,)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT * FROM auth_user_by_email('w@example.com')")
