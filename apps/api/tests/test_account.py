"""The login and the promises about it: a way back in without email, a new password, signing out everywhere, and deleting an account
(and everything in it) or a login. Every state, including the careless and the hostile ones."""

from __future__ import annotations

import asyncio
import re
from typing import Any

import psycopg
from harness import PASSWORD, Owner, World, make_venue, sign_up
from nigiwai_api.services.account import ALPHABET, new_recovery_code, recovery_hash
from test_atlas import ARTIST, Items, answer, entity, fill, join, venues
from test_atlas import rebuild_now as rebuild_atlas

CODE = re.compile(rf"^([{ALPHABET}]{{5}}-){{3}}[{ALPHABET}]{{5}}$")
NEW = "another-long-passphrase-7"
THIRD = "a-third-long-passphrase-3"


async def signup_raw(world: World, email: str, **body: Any) -> Any:
    client = world.client()
    r = await client.post(
        "/v1/auth/signup",
        json={"email": email, "password": PASSWORD, **({"business_name": "Acc"} | body)},
    )
    return client, r


async def code_of(world: World, email: str) -> tuple[Owner, str]:
    client, r = await signup_raw(world, email)
    assert r.status_code == 201, r.text
    return Owner(client, r.json()), r.json()["recovery_code"]


async def member_of_account(world: World, owner: Owner, role: str, email: str) -> Owner:
    made = (await owner.post("/team/invitations", json={"role": role})).json()
    client, r = await signup_raw(world, email, invite_token=made["token"], business_name=None)
    assert r.status_code == 201, r.text
    return Owner(client, r.json())


async def recover(world: World, email: str, code: str, password: str = NEW) -> Any:
    return await world.client().post(
        "/v1/auth/recover", json={"email": email, "recovery_code": code, "new_password": password}
    )


async def login(world: World, email: str, password: str) -> int:
    r = await world.client().post("/v1/auth/login", json={"email": email, "password": password})
    return int(r.status_code)


# ---- the recovery code -------------------------------------------------------------------------------------------
def test_a_code_is_twenty_readable_characters_and_never_repeats() -> None:
    codes = {new_recovery_code() for _ in range(500)}
    assert len(codes) == 500
    assert all(CODE.match(c) for c in codes)
    assert not set("0O1ILU") & set("".join(codes))
    assert recovery_hash("abcde-fghjk-mnpqr-stvwx") == recovery_hash(" ABCDE FGHJK  mnpqr-stvwx ")


async def test_signup_shows_the_code_once_and_the_database_keeps_only_its_hash(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner, code = await code_of(world, "own@example.com")
    assert CODE.match(code)
    stored = admin.execute("SELECT recovery_hash, recovery_set_at FROM app_user").fetchone()
    assert stored is not None and bytes(stored[0]) == recovery_hash(code) and stored[1] is not None
    assert code.replace("-", "") not in str(
        admin.execute("SELECT row_to_json(u)::text FROM app_user u").fetchone()
    )
    # it is never returned again: not by whoami, not by signing in
    assert "recovery_code" not in (await owner.client.get("/v1/auth/me")).json() or (
        (await owner.client.get("/v1/auth/me")).json()["recovery_code"] is None
    )
    again = await world.client().post(
        "/v1/auth/login", json={"email": "own@example.com", "password": PASSWORD}
    )
    assert again.status_code == 200 and again.json().get("recovery_code") is None
    other, other_code = await code_of(world, "two@example.com")
    assert other_code != code


async def test_someone_who_joins_by_invitation_gets_a_code_too(world: World) -> None:
    owner = await sign_up(world)
    made = (await owner.post("/team/invitations", json={"role": "viewer"})).json()
    client = world.client()
    r = await client.post(
        "/v1/auth/signup",
        json={"email": "guest@example.com", "password": PASSWORD, "invite_token": made["token"]},
    )
    assert r.status_code == 201 and CODE.match(r.json()["recovery_code"])


async def test_the_code_sets_a_new_password_signs_everything_out_and_is_spent(
    world: World,
) -> None:
    owner, code = await code_of(world, "own@example.com")
    laptop = world.client()
    assert (
        await laptop.post("/v1/auth/login", json={"email": "own@example.com", "password": PASSWORD})
    ).status_code == 200
    typed = code.lower().replace("-", " ")  # how a person copies it: lower case, spaces for dashes
    r = await recover(world, "OWN@example.com", typed)
    assert r.status_code == 200, r.text
    fresh = r.json()["recovery_code"]
    assert CODE.match(fresh) and fresh != code
    assert await login(world, "own@example.com", PASSWORD) == 401
    assert await login(world, "own@example.com", NEW) == 200
    # every earlier sign-in is gone, on every device
    assert (await owner.client.get("/v1/auth/me")).status_code == 401
    assert (await laptop.get("/v1/auth/me")).status_code == 401
    # the code that was used is spent; the fresh one works once
    assert (await recover(world, "own@example.com", code, THIRD)).status_code == 401
    assert (await recover(world, "own@example.com", fresh, THIRD)).status_code == 200
    assert (await recover(world, "own@example.com", fresh, NEW)).status_code == 401
    assert await login(world, "own@example.com", THIRD) == 200


async def test_a_wrong_code_an_unknown_address_and_a_person_with_no_code_get_the_same_answer(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    await code_of(world, "own@example.com")
    await code_of(world, "legacy@example.com")
    admin.execute(
        "UPDATE app_user SET recovery_hash = NULL, recovery_set_at = NULL WHERE email = 'legacy@example.com'"
    )
    right_shape = new_recovery_code()
    answers = [
        await recover(world, "own@example.com", right_shape),
        await recover(world, "nobody@example.com", right_shape),
        await recover(world, "legacy@example.com", right_shape),
        await recover(world, "own@example.com", "x"),
    ]
    assert {a.status_code for a in answers} == {401}
    assert len({a.text for a in answers}) == 1
    assert await login(world, "own@example.com", PASSWORD) == 200  # nothing changed


async def test_a_weak_new_password_is_refused_without_using_up_the_code(world: World) -> None:
    _, code = await code_of(world, "own@example.com")
    for weak in ("short", "own@example.com", "aaaaaaaaaaaa", "password123"):
        r = await recover(world, "own@example.com", code, weak)
        assert r.status_code == 422, (weak, r.text)
    assert (await recover(world, "own@example.com", code)).status_code == 200


async def test_junk_input_to_recovery_is_refused_plainly(world: World) -> None:
    c = world.client()
    for body in (
        {},
        {"email": "not-an-email", "recovery_code": "x", "new_password": NEW},
        {"email": "a@example.com", "recovery_code": "", "new_password": NEW},
        {"email": "a@example.com", "recovery_code": "x" * 101, "new_password": NEW},
        {"email": "a@example.com", "recovery_code": "x", "new_password": ""},
        {"email": "a@example.com", "recovery_code": "x", "new_password": NEW, "extra": 1},
        {"email": "a@example.com", "recovery_code": 5, "new_password": NEW},
    ):
        r = await c.post("/v1/auth/recover", json=body)
        assert r.status_code == 422, (body, r.status_code)


async def test_two_people_racing_with_one_code_yield_exactly_one_new_password(
    world: World,
) -> None:
    _, code = await code_of(world, "own@example.com")
    passwords = [f"racing-long-passphrase-{i}" for i in range(5)]
    results = await asyncio.gather(*[recover(world, "own@example.com", code, p) for p in passwords])
    codes = sorted(r.status_code for r in results)
    assert codes.count(200) == 1 and set(codes) <= {200, 401}, codes
    winner = passwords[[r.status_code for r in results].index(200)]
    assert await login(world, "own@example.com", winner) == 200
    assert sum([await login(world, "own@example.com", p) == 200 for p in passwords]) == 1


async def test_guessing_a_code_is_limited_per_address_and_per_network(world: World) -> None:
    await code_of(world, "own@example.com")
    codes = [
        (await recover(world, "own@example.com", new_recovery_code())).status_code for _ in range(7)
    ]
    assert codes[:5] == [401] * 5 and codes[5:] == [429, 429]
    by_network = [
        (await recover(world, f"person{i}@example.com", new_recovery_code())).status_code
        for i in range(25)
    ]
    assert by_network[0] == 401 and 429 in by_network


# ---- changing the password, the code and the sessions ------------------------------------------------------------
async def test_changing_the_password_needs_the_old_one_and_ends_every_other_sign_in(
    world: World,
) -> None:
    owner, _ = await code_of(world, "own@example.com")
    phone = world.client()
    assert (
        await phone.post("/v1/auth/login", json={"email": "own@example.com", "password": PASSWORD})
    ).status_code == 200

    def put(body: dict[str, Any]) -> Any:
        return owner.client.put("/v1/account/password", headers=owner.headers, json=body)

    assert (
        await put({"current_password": "wrong-wrong-wrong", "new_password": NEW})
    ).status_code == 403
    assert (await put({"current_password": PASSWORD, "new_password": "short"})).status_code == 422
    assert (await put({"current_password": PASSWORD, "new_password": PASSWORD})).status_code == 422
    assert (
        await put({"current_password": PASSWORD, "new_password": "own@example.com"})
    ).status_code == 422
    assert (await put({"current_password": PASSWORD})).status_code == 422
    assert (await put({"current_password": PASSWORD, "new_password": NEW})).status_code == 204
    assert (await owner.client.get("/v1/auth/me")).status_code == 200  # this sign-in stays
    assert (await phone.get("/v1/auth/me")).status_code == 401  # the other is gone
    assert await login(world, "own@example.com", PASSWORD) == 401
    assert await login(world, "own@example.com", NEW) == 200


async def test_account_calls_need_a_session_and_the_csrf_header(world: World) -> None:
    owner, _ = await code_of(world, "own@example.com")
    anon = world.client()
    for method, path, body in (
        ("GET", "/v1/account", None),
        ("PUT", "/v1/account/password", {"current_password": PASSWORD, "new_password": NEW}),
        ("POST", "/v1/account/recovery-code", {"password": PASSWORD}),
        ("POST", "/v1/account/sign-out-everywhere", None),
        ("POST", "/v1/account/delete", {"password": PASSWORD}),
        (
            "POST",
            f"/v1/tenants/{owner.tenant_id}/delete-account",
            {"password": PASSWORD, "confirm_name": "Acc"},
        ),
    ):
        kw: dict[str, Any] = {"json": body} if body is not None else {}
        assert (await anon.request(method, path, **kw)).status_code == 401, path
        if method != "GET":
            assert (await owner.client.request(method, path, **kw)).status_code == 403, path
    assert await login(world, "own@example.com", PASSWORD) == 200  # nothing above did anything


async def test_a_new_code_needs_the_password_and_replaces_the_old_one(world: World) -> None:
    owner, old = await code_of(world, "own@example.com")

    def post(pw: str) -> Any:
        return owner.client.post(
            "/v1/account/recovery-code", headers=owner.headers, json={"password": pw}
        )

    assert (await post("wrong-wrong-wrong")).status_code == 403
    r = await post(PASSWORD)
    assert r.status_code == 200
    new = r.json()["recovery_code"]
    assert CODE.match(new) and new != old
    assert (await recover(world, "own@example.com", old)).status_code == 401
    assert (await recover(world, "own@example.com", new)).status_code == 200


async def test_asking_for_the_password_again_is_limited_so_it_cannot_be_used_to_guess_it(
    world: World,
) -> None:
    owner, _ = await code_of(world, "own@example.com")
    codes = [
        (
            await owner.client.post(
                "/v1/account/recovery-code",
                headers=owner.headers,
                json={"password": f"guess-{i}-guess-guess"},
            )
        ).status_code
        for i in range(10)
    ]
    assert codes[:8] == [403] * 8 and 429 in codes[8:]
    # and even the right password is refused while the limit holds
    assert (
        await owner.client.post(
            "/v1/account/recovery-code", headers=owner.headers, json={"password": PASSWORD}
        )
    ).status_code == 429


async def test_signing_out_everywhere_ends_every_session_and_clears_the_cookie(
    world: World,
) -> None:
    owner, _ = await code_of(world, "own@example.com")
    other = world.client()
    await other.post("/v1/auth/login", json={"email": "own@example.com", "password": PASSWORD})
    r = await owner.client.post("/v1/account/sign-out-everywhere", headers=owner.headers)
    assert r.status_code == 204
    assert "nigiwai_session" in r.headers.get("set-cookie", "") and "Max-Age=0" in r.headers.get(
        "set-cookie", ""
    )
    assert (await owner.client.get("/v1/auth/me")).status_code == 401
    assert (await other.get("/v1/auth/me")).status_code == 401


async def test_the_overview_lists_the_accounts_and_which_ones_the_person_alone_holds_up(
    world: World,
) -> None:
    owner, _ = await code_of(world, "own@example.com")
    r = (await owner.client.get("/v1/account")).json()
    assert r["email"] == "own@example.com" and r["recovery_set_at"] is not None
    assert [(a["name"], a["role"], a["sole_owner"], a["others"]) for a in r["accounts"]] == [
        ("Acc", "owner", True, 0)
    ]
    made = (await owner.post("/team/invitations", json={"role": "viewer"})).json()
    guest = world.client()
    await guest.post(
        "/v1/auth/signup",
        json={"email": "g@example.com", "password": PASSWORD, "invite_token": made["token"]},
    )
    r = (await owner.client.get("/v1/account")).json()
    assert [(a["sole_owner"], a["others"]) for a in r["accounts"]] == [(True, 1)]
    g = (await guest.get("/v1/account")).json()
    assert [(a["role"], a["sole_owner"], a["others"]) for a in g["accounts"]] == [
        ("viewer", False, None)
    ]


# ---- deleting an account and everything in it --------------------------------------------------------------------
def tenant_rows(admin: psycopg.Connection[Any], tenant_id: str) -> dict[str, int]:
    """Rows left for a tenant in every table that has a tenant_id column, found from the schema so a future table is covered too."""
    tables = [
        r[0]
        for r in admin.execute(
            "SELECT table_name FROM information_schema.columns WHERE table_schema = 'public' AND column_name = 'tenant_id'"
            " AND table_name IN (SELECT table_name FROM information_schema.tables WHERE table_type = 'BASE TABLE')"
        ).fetchall()
    ]
    left = {}
    for t in tables:
        (n,) = admin.execute(
            f'SELECT count(*) FROM "{t}" WHERE tenant_id = %s', (tenant_id,)
        ).fetchone()  # type: ignore[misc]
        if n:
            left[t] = int(n)
    return left


async def test_deleting_an_account_removes_everything_in_it_and_nothing_of_anyone_elses(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner, _ = await code_of(world, "own@example.com")
    other, _ = await code_of(world, "other@example.com")
    venue = await make_venue(owner)
    keep = await make_venue(other)
    pick = entity(admin, "Sample Act")
    answer(admin, venue, [(pick, ARTIST)])  # a guest's answer
    answer(admin, keep, [(pick, ARTIST)])
    before = tenant_rows(admin, owner.tenant_id)
    assert before.get("response") and before.get("business")

    r = await owner.client.post(
        f"/v1/tenants/{owner.tenant_id}/delete-account",
        headers=owner.headers,
        json={"password": PASSWORD, "confirm_name": "acc"},
    )
    assert r.status_code == 204, r.text
    assert tenant_rows(admin, owner.tenant_id) == {}
    assert admin.execute(
        "SELECT count(*) FROM tenant WHERE id = %s", (owner.tenant_id,)
    ).fetchone() == (0,)
    # the other account is untouched, and so is the person's own login (they can still sign in, into nothing)
    assert tenant_rows(admin, other.tenant_id).get("response") == 1
    me = await owner.client.get("/v1/auth/me")
    assert me.status_code == 200 and me.json()["tenants"] == []
    assert (await owner.client.get(f"/v1/tenants/{owner.tenant_id}/businesses")).status_code in (
        403,
        404,
    )


async def test_deleting_an_account_also_removes_its_log_of_qloo_calls(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner, _ = await code_of(world, "own@example.com")
    admin.execute(
        "INSERT INTO qloo_call (id, trace_id, tenant_id, purpose, endpoint, params, status, transport, cache, key_fingerprint, host, guard_version)"
        " VALUES (gen_random_uuid(), gen_random_uuid(), %s, 'board', '/x', '{}'::jsonb, 'ok', 'rest', 'miss', 'fp', 'h', 'v')",
        (owner.tenant_id,),
    )
    assert admin.execute(
        "SELECT count(*) FROM qloo_call WHERE tenant_id = %s", (owner.tenant_id,)
    ).fetchone() == (1,)
    r = await owner.client.post(
        f"/v1/tenants/{owner.tenant_id}/delete-account",
        headers=owner.headers,
        json={"password": PASSWORD, "confirm_name": "Acc"},
    )
    assert r.status_code == 204, r.text
    assert admin.execute(
        "SELECT count(*) FROM qloo_call WHERE tenant_id = %s", (owner.tenant_id,)
    ).fetchone() == (0,)


async def test_deleting_an_account_needs_the_name_the_password_and_the_owner(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner, _ = await code_of(world, "own@example.com")
    made = (await owner.post("/team/invitations", json={"role": "manager"})).json()
    manager = world.client()
    r = await manager.post(
        "/v1/auth/signup",
        json={"email": "m@example.com", "password": PASSWORD, "invite_token": made["token"]},
    )
    csrf = {"x-csrf-token": r.json()["csrf_token"]}
    url = f"/v1/tenants/{owner.tenant_id}/delete-account"
    attempts = [
        (manager, csrf, {"password": PASSWORD, "confirm_name": "Acc"}, 403),  # not an owner
        (
            owner.client,
            owner.headers,
            {"password": "wrong-wrong-wrong", "confirm_name": "Acc"},
            403,
        ),
        (
            owner.client,
            owner.headers,
            {"password": PASSWORD, "confirm_name": "Something else"},
            422,
        ),
        (owner.client, owner.headers, {"password": PASSWORD, "confirm_name": ""}, 422),
        (owner.client, owner.headers, {"password": PASSWORD}, 422),
    ]
    for client, headers, body, want in attempts:
        got = await client.post(url, headers=headers, json=body)
        assert got.status_code == want, (body, got.status_code, got.text)
    assert admin.execute(
        "SELECT count(*) FROM tenant WHERE id = %s", (owner.tenant_id,)
    ).fetchone() == (1,)
    # an owner of another account cannot delete this one by naming it
    other, _ = await code_of(world, "other@example.com")
    sneaky = await other.client.post(
        url, headers=other.headers, json={"password": PASSWORD, "confirm_name": "Acc"}
    )
    assert sneaky.status_code in (403, 404)
    assert admin.execute(
        "SELECT count(*) FROM tenant WHERE id = %s", (owner.tenant_id,)
    ).fetchone() == (1,)


async def test_the_other_people_in_a_deleted_account_lose_it_and_keep_their_logins(
    world: World,
) -> None:
    owner, _ = await code_of(world, "own@example.com")
    made = (await owner.post("/team/invitations", json={"role": "viewer"})).json()
    guest = world.client()
    r = await guest.post(
        "/v1/auth/signup",
        json={"email": "g@example.com", "password": PASSWORD, "invite_token": made["token"]},
    )
    assert r.status_code == 201
    done = await owner.client.post(
        f"/v1/tenants/{owner.tenant_id}/delete-account",
        headers=owner.headers,
        json={"password": PASSWORD, "confirm_name": "Acc"},
    )
    assert done.status_code == 204
    assert (await guest.get("/v1/auth/me")).json()["tenants"] == []
    assert await login(world, "g@example.com", PASSWORD) == 200


async def test_deleting_an_account_that_joined_the_atlas_takes_its_counts_out_at_once(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    group = await venues(world, 5)
    items = Items(admin)
    fill(admin, items, group)
    for owner, venue in group:
        await join(owner, venue)
    await rebuild_atlas(world)
    assert admin.execute("SELECT count(*) FROM atlas_cell").fetchone() != (0,)
    leaver = group[0][0]
    r = await leaver.client.post(
        f"/v1/tenants/{leaver.tenant_id}/delete-account",
        headers=leaver.headers,
        json={"password": PASSWORD, "confirm_name": "The Lantern"},
    )
    assert r.status_code == 204, r.text
    # four venues are left, which is not a neighbourhood: the pooled table is empty without waiting for the next scheduled rebuild
    assert admin.execute("SELECT count(*) FROM atlas_cell").fetchone() == (0,)


async def test_the_demo_venues_account_cannot_be_deleted_even_by_asking_the_database_nicely(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner, _ = await code_of(world, "own@example.com")
    demo = "6e1c0de0-0000-4000-8000-00000000d3a0"
    admin.execute(
        "INSERT INTO membership (tenant_id, user_id, role) VALUES (%s, %s, 'owner')",
        (demo, owner.me["user_id"]),
    )
    r = await owner.client.post(
        f"/v1/tenants/{demo}/delete-account",
        headers=owner.headers,
        json={"password": PASSWORD, "confirm_name": "Nigiwai demo venues"},
    )
    assert r.status_code == 403, r.text
    assert admin.execute("SELECT count(*) FROM tenant WHERE id = %s", (demo,)).fetchone() == (1,)


# ---- deleting a login --------------------------------------------------------------------------------------------
async def test_a_login_cannot_be_deleted_while_the_person_alone_holds_up_an_account(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner, _ = await code_of(world, "own@example.com")
    bad = await owner.client.post(
        "/v1/account/delete", headers=owner.headers, json={"password": "wrong-wrong-wrong"}
    )
    assert bad.status_code == 403
    r = await owner.client.post(
        "/v1/account/delete", headers=owner.headers, json={"password": PASSWORD}
    )
    assert r.status_code == 409 and "only owner of “Acc”" in r.json()["detail"]
    assert admin.execute("SELECT count(*) FROM app_user").fetchone() == (1,)
    # delete the account first, and then the login goes
    await owner.client.post(
        f"/v1/tenants/{owner.tenant_id}/delete-account",
        headers=owner.headers,
        json={"password": PASSWORD, "confirm_name": "Acc"},
    )
    gone = await owner.client.post(
        "/v1/account/delete", headers=owner.headers, json={"password": PASSWORD}
    )
    assert gone.status_code == 204 and "Max-Age=0" in gone.headers.get("set-cookie", "")
    assert admin.execute("SELECT count(*) FROM app_user").fetchone() == (0,)
    assert admin.execute("SELECT count(*) FROM app_session").fetchone() == (0,)
    assert await login(world, "own@example.com", PASSWORD) == 401
    assert (await owner.client.get("/v1/auth/me")).status_code == 401


async def test_a_member_can_delete_their_login_and_the_account_they_left_carries_on(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner, _ = await code_of(world, "own@example.com")
    made = (await owner.post("/team/invitations", json={"role": "manager"})).json()
    manager = world.client()
    r = await manager.post(
        "/v1/auth/signup",
        json={"email": "m@example.com", "password": PASSWORD, "invite_token": made["token"]},
    )
    csrf = {"x-csrf-token": r.json()["csrf_token"]}
    biz = await manager.post(
        f"/v1/tenants/{owner.tenant_id}/businesses",
        headers=csrf,
        json={"name": "Side", "type": "bar", "currency": "GBP"},
    )
    assert biz.status_code == 201, biz.text
    gone = await manager.post("/v1/account/delete", headers=csrf, json={"password": PASSWORD})
    assert gone.status_code == 204
    assert admin.execute(
        "SELECT count(*) FROM app_user WHERE email = 'm@example.com'"
    ).fetchone() == (0,)
    # what they made stays with the account, no longer attributed to anyone
    assert [b["name"] for b in (await owner.get("/businesses")).json()] == ["Side"]
    members = (await owner.get("/team")).json()["members"]
    assert [m["email"] for m in members] == ["own@example.com"]


async def test_one_of_two_owners_can_delete_their_login(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner, _ = await code_of(world, "own@example.com")
    made = (await owner.post("/team/invitations", json={"role": "manager"})).json()
    second = world.client()
    r = await second.post(
        "/v1/auth/signup",
        json={"email": "two@example.com", "password": PASSWORD, "invite_token": made["token"]},
    )
    two = Owner(second, r.json())
    base = f"/v1/tenants/{owner.tenant_id}/team"
    up = await owner.client.put(
        f"{base}/members/{two.me['user_id']}", headers=owner.headers, json={"role": "owner"}
    )
    assert up.status_code == 200
    done = await owner.client.post(
        "/v1/account/delete", headers=owner.headers, json={"password": PASSWORD}
    )
    assert done.status_code == 204, done.text
    assert admin.execute(
        "SELECT role FROM membership WHERE tenant_id = %s", (owner.tenant_id,)
    ).fetchall() == [("owner",)]
    # and now the other is the sole owner, so they cannot leave without deleting it
    refused = await second.post(
        "/v1/account/delete", headers=two.headers, json={"password": PASSWORD}
    )
    assert refused.status_code == 409


# ---- starting another venue from a login ---------------------------------------------------------------------------
async def test_a_login_can_start_another_venue_and_owns_it(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner, _ = await code_of(world, "own@example.com")
    r = await owner.client.post(
        "/v1/account/accounts", headers=owner.headers, json={"business_name": "  Side Bar  "}
    )
    assert r.status_code == 201, r.text
    made = r.json()
    assert made["name"] == "Side Bar" and made["role"] == "owner"
    me = (await owner.client.get("/v1/auth/me")).json()
    assert [(t["name"], t["role"]) for t in me["tenants"]] == [
        ("Acc", "owner"),
        ("Side Bar", "owner"),
    ]
    # it is a working account of its own: its owner can use it, and the first account's data is not in it
    mine = await owner.client.post(
        f"/v1/tenants/{made['id']}/businesses",
        headers=owner.headers,
        json={"name": "Side", "type": "bar", "currency": "GBP"},
    )
    assert mine.status_code == 201, mine.text
    assert [
        b["name"]
        for b in (await owner.client.get(f"/v1/tenants/{owner.tenant_id}/businesses")).json()
    ] == []
    assert admin.execute(
        "SELECT action FROM audit_log WHERE tenant_id = %s AND action LIKE 'account.%%'",
        (made["id"],),
    ).fetchall() == [("account.create",)]


async def test_a_person_whose_account_was_deleted_can_start_a_new_one(world: World) -> None:
    owner, _ = await code_of(world, "own@example.com")
    gone = await owner.client.post(
        f"/v1/tenants/{owner.tenant_id}/delete-account",
        headers=owner.headers,
        json={"password": PASSWORD, "confirm_name": "Acc"},
    )
    assert gone.status_code == 204
    assert (await owner.client.get("/v1/auth/me")).json()["tenants"] == []
    made = await owner.client.post(
        "/v1/account/accounts", headers=owner.headers, json={"business_name": "Fresh Start"}
    )
    assert made.status_code == 201
    assert [t["name"] for t in (await owner.client.get("/v1/auth/me")).json()["tenants"]] == [
        "Fresh Start"
    ]


async def test_starting_a_venue_needs_a_session_a_clean_name_and_stops_at_five_accounts(
    world: World,
) -> None:
    owner, _ = await code_of(world, "own@example.com")
    assert (
        await world.client().post("/v1/account/accounts", json={"business_name": "X"})
    ).status_code == 401
    assert (
        await owner.client.post("/v1/account/accounts", json={"business_name": "X"})
    ).status_code == 403  # no CSRF header
    for body in (
        {},
        {"business_name": ""},
        {"business_name": "   "},
        {"business_name": "a" * 121},
        {"business_name": "two\nlines"},
        {"business_name": "X", "extra": 1},
        {"business_name": 5},
    ):
        r = await owner.client.post("/v1/account/accounts", headers=owner.headers, json=body)
        assert r.status_code == 422, (body, r.status_code)
    # the person already owns one; three starts an hour is the limit
    codes = [
        (
            await owner.client.post(
                "/v1/account/accounts", headers=owner.headers, json={"business_name": f"Venue {i}"}
            )
        ).status_code
        for i in range(3)
    ]
    assert codes == [201, 201, 201]
    limited = await owner.client.post(
        "/v1/account/accounts", headers=owner.headers, json={"business_name": "One too many"}
    )
    assert limited.status_code == 429


async def test_the_cap_on_owned_accounts_holds_when_the_hourly_limit_does_not_apply(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner, _ = await code_of(world, "own@example.com")
    for i in range(4):  # made directly, as if over several hours
        (tenant,) = admin.execute(
            "INSERT INTO tenant (name) VALUES (%s) RETURNING id", (f"Held {i}",)
        ).fetchone()  # type: ignore[misc]
        admin.execute(
            "INSERT INTO membership (tenant_id, user_id, role) VALUES (%s, %s, 'owner')",
            (tenant, owner.me["user_id"]),
        )
    r = await owner.client.post(
        "/v1/account/accounts", headers=owner.headers, json={"business_name": "Sixth"}
    )
    assert r.status_code == 409 and "already own 5" in r.json()["detail"]
    # being a viewer or a manager elsewhere does not count against the cap
    other, _ = await code_of(world, "other@example.com")
    made = (await other.post("/team/invitations", json={"role": "viewer"})).json()
    joined = await owner.client.post(
        "/v1/invitations/accept", headers=owner.headers, json={"token": made["token"]}
    )
    assert joined.status_code == 200


# ---- a copy of the account's data ---------------------------------------------------------------------------------
def _unzip(content: bytes) -> dict[str, bytes]:
    import io
    import zipfile

    with zipfile.ZipFile(io.BytesIO(content)) as z:
        assert z.testzip() is None
        return {n: z.read(n) for n in z.namelist()}


async def test_an_owner_downloads_a_copy_that_holds_their_data_and_nothing_that_signs_anyone_in(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    import json

    owner, code = await code_of(world, "own@example.com")
    other, _ = await code_of(world, "other@example.com")
    venue = await make_venue(
        owner, reward={"title": "A free coffee", "detail": "Show this at the bar"}
    )
    await make_venue(other)  # another account's data must stay out
    made = (await owner.post("/team/invitations", json={"role": "viewer"})).json()
    r = await owner.client.get(f"/v1/tenants/{owner.tenant_id}/export")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    assert re.fullmatch(
        r'attachment; filename="nigiwai-export-\d{8}-\d{4}\.zip"', r.headers["content-disposition"]
    )
    assert r.headers["cache-control"] == "private, no-store"
    files = _unzip(r.content)
    assert set(files) == {
        "README.txt",
        "account.json",
        "venue.json",
        "guests.json",
        "groups.json",
        "scores.json",
        "decisions.json",
        "questions.json",
        "audit_log.csv",
    }
    account = json.loads(files["account.json"])
    assert account["account"]["name"] == "Acc" and [m["email"] for m in account["members"]] == [
        "own@example.com"
    ]
    assert [i["role"] for i in account["invitations"]] == ["viewer"]
    vj = json.loads(files["venue.json"])
    assert [b["name"] for b in vj["businesses"]] == ["The Lantern"] and len(vj["posters"]) == 1
    assert vj["survey_versions"][0]["reward"]["title"] == "A free coffee"
    assert vj["places"][0]["lat"] == 51.5 and vj["places"][0]["lon"] == -0.12
    # nothing in the copy can be used to sign in, to get in, or to remove a guest's answer
    everything = b"\n".join(files.values()).decode("utf-8")
    for secret in (
        code,
        code.replace("-", ""),
        made["token"],
        venue.token,
        PASSWORD,
        "$argon2",
        "password_hash",
        "recovery_hash",
        "token_hash",
        "token_enc",
        "delete_token",
        "csrf",
    ):
        assert secret not in everything, secret
    stored = admin.execute(
        "SELECT encode(recovery_hash, 'hex'), password_hash FROM app_user WHERE email = 'own@example.com'"
    ).fetchone()
    assert stored is not None and all(s not in everything for s in stored)
    # the other account's name and data are not in it, and the export is written to the audit log
    assert "other@example.com" not in everything
    assert admin.execute(
        "SELECT count(*) FROM audit_log WHERE tenant_id = %s AND action = 'account.export'",
        (owner.tenant_id,),
    ).fetchone() == (1,)
    assert (
        "audit_log.csv" in files and b"account.export" not in files["audit_log.csv"]
    )  # the entry is made after the copy is built


async def test_the_copy_counts_guests_but_never_shows_one(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    import json

    owner, _ = await code_of(world, "own@example.com")
    venue = await make_venue(owner)
    common, rare = entity(admin, "Sample Act Common"), entity(admin, "Sample Act Rare")
    for i in range(13):
        answer(
            admin, venue, [(common, ARTIST)] + ([(rare, ARTIST)] if i < 9 else [])
        )  # the rare act is picked by 9 guests
    admin.execute(
        "UPDATE response SET age_band = '25-34', district = 'Eastside' WHERE tenant_id = %s",
        (owner.tenant_id,),
    )
    admin.execute(
        "UPDATE response SET age_band = '18-24', district = 'Old Town' WHERE id IN (SELECT id FROM response WHERE tenant_id = %s ORDER BY id LIMIT 2)",
        (owner.tenant_id,),
    )
    # one answer is held for review (sent too fast): it is counted as held and is in no figure
    admin.execute(
        "UPDATE response SET quality_flag = 'quarantined' WHERE id = (SELECT id FROM response WHERE tenant_id = %s AND district = 'Eastside' ORDER BY id LIMIT 1)",
        (owner.tenant_id,),
    )
    r = await owner.client.get(f"/v1/tenants/{owner.tenant_id}/export")
    files = _unzip(r.content)
    g = json.loads(files["guests.json"])["businesses"][0]
    assert (g["counted"], g["held_for_review"]) == (12, 1)
    # 9 guests is below the minimum of ten: the rare act is not listed, the common one is
    assert [(i["name"], i["guests"]) for i in g["items_at_least_minimum_guests"]] == [
        ("Sample Act Common", 12)
    ]
    # a value fewer than ten guests gave is not there at all, so it cannot be told apart from "nobody"
    assert g["answers_at_least_minimum_guests"]["district"] == {"Eastside": 10}
    assert g["answers_at_least_minimum_guests"]["age_band"] == {"25-34": 10}
    assert "Old Town" not in files["guests.json"].decode("utf-8") and "18-24" not in files[
        "guests.json"
    ].decode("utf-8")
    # no row is one guest: no response id, no pick row, no receipt
    blob = b"\n".join(files.values()).decode("utf-8")
    ids = [str(x[0]) for x in admin.execute("SELECT id FROM response").fetchall()]
    assert not any(i in blob for i in ids)
    assert "position" not in blob and "response_id" not in blob


async def test_only_an_owner_can_download_a_copy_and_it_is_limited(world: World) -> None:
    owner, _ = await code_of(world, "own@example.com")
    manager = await member_of_account(world, owner, "manager", "m@example.com")
    viewer = await member_of_account(world, owner, "viewer", "v@example.com")
    url = f"/v1/tenants/{owner.tenant_id}/export"
    assert (await world.client().get(url)).status_code == 401
    for who in (manager, viewer):
        assert (await who.client.get(url)).status_code == 403
    outsider, _ = await code_of(world, "out@example.com")
    assert (await outsider.client.get(url)).status_code in (403, 404)
    codes = [(await owner.client.get(url)).status_code for _ in range(6)]
    assert codes == [200] * 5 + [429]


async def test_an_account_with_nothing_in_it_still_has_a_copy(world: World) -> None:
    owner, _ = await code_of(world, "own@example.com")
    r = await owner.client.get(f"/v1/tenants/{owner.tenant_id}/export")
    assert r.status_code == 200
    import json

    files = _unzip(r.content)
    assert (
        json.loads(files["guests.json"])["businesses"] == []
        and json.loads(files["venue.json"])["businesses"] == []
    )
