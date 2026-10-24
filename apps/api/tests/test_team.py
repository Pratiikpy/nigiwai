"""Team: who is in an account, what each may do, and the invitation links that bring someone in. Every state of a link, every role,
and the database-level guarantee that an account never loses its last owner."""

from __future__ import annotations

import asyncio
from typing import Any

import psycopg
import pytest
from harness import APP_URL, PASSWORD, Owner, World, sign_up
from nigiwai_api.security import token_hash

NO_TOKEN = "x" * 43  # well formed, matches nothing


async def invite(owner: Owner, role: str = "viewer") -> dict[str, Any]:
    r = await owner.post("/team/invitations", json={"role": role})
    assert r.status_code == 201, r.text
    return r.json()


async def look(world: World, token: str) -> Any:
    return await world.client().post("/v1/invitations/peek", json={"token": token})


def token_of(made: dict[str, Any]) -> str:
    return str(made["token"])


async def signup_with(world: World, token: str, email: str) -> Any:
    client = world.client()
    r = await client.post(
        "/v1/auth/signup", json={"email": email, "password": PASSWORD, "invite_token": token}
    )
    return client, r


async def member_of(world: World, owner: Owner, role: str, email: str) -> Owner:
    """Someone who joined through a real invitation, signed in with their own session."""
    made = await invite(owner, role)
    client, r = await signup_with(world, token_of(made), email)
    assert r.status_code == 201, r.text
    return Owner(client, r.json())


# ---- the link ----------------------------------------------------------------------------------------------------
async def test_an_owner_makes_a_link_and_only_its_hash_is_stored(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world, "own@example.com", "Lantern")
    made = await invite(owner, "manager")
    assert made["url"] == f"https://nigiwai.test/invite#{made['token']}"
    assert made["role"] == "manager"
    rows = admin.execute("SELECT token_hash, role FROM invitation").fetchall()
    assert rows == [(token_hash(made["token"]), "manager")]
    dump = admin.execute("SELECT row_to_json(i)::text FROM invitation i").fetchone()
    assert dump is not None and made["token"] not in dump[0]
    # the token is shown once: the list never carries it
    listing = (await owner.get("/team")).json()
    assert [i["role"] for i in listing["invitations"]] == ["manager"]
    assert "token" not in listing["invitations"][0] and "url" not in listing["invitations"][0]


async def test_a_link_can_offer_manager_or_viewer_and_never_owner(world: World) -> None:
    owner = await sign_up(world)
    for role in ("owner", "admin", "", None):
        r = await owner.post("/team/invitations", json={"role": role})
        assert r.status_code == 422, (role, r.text)
    assert (await owner.post("/team/invitations", json={})).status_code == 422
    assert (
        await owner.post("/team/invitations", json={"role": "viewer", "x": 1})
    ).status_code == 422


async def test_a_stranger_sees_the_account_name_and_the_role_and_nothing_else(
    world: World,
) -> None:
    owner = await sign_up(world, "own@example.com", "The Lantern")
    made = await invite(owner, "viewer")
    r = await look(world, made["token"])
    assert r.status_code == 200
    assert r.json() == {"account": "The Lantern", "role": "viewer", "state": "open", "reason": None}


async def test_unknown_and_malformed_links_are_a_plain_404_or_422(world: World) -> None:
    c = world.client()
    assert (await c.post("/v1/invitations/peek", json={"token": NO_TOKEN})).status_code == 404
    for junk in ("short", "a" * 101, "a" * 30 + " x", 5, None, ""):
        r = await c.post("/v1/invitations/peek", json={"token": junk})
        assert r.status_code == 422, (junk, r.text)
    assert (await c.post("/v1/invitations/peek", json={})).status_code == 422
    # the link no longer carries the secret in a path a server could log: that route is gone
    assert (await c.get(f"/v1/invitations/{NO_TOKEN}")).status_code in (404, 405)


async def test_the_link_page_is_rate_limited_per_network(world: World) -> None:
    c = world.client()
    codes = [
        (await c.post("/v1/invitations/peek", json={"token": NO_TOKEN})).status_code
        for _ in range(65)
    ]
    assert codes[0] == 404 and 429 in codes


# ---- joining -------------------------------------------------------------------------------------------------------
async def test_a_new_person_signs_up_from_a_link_and_joins_with_the_offered_role(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world, "own@example.com", "The Lantern")
    made = await invite(owner, "manager")
    client, r = await signup_with(world, made["token"], "new@example.com")
    assert r.status_code == 201, r.text
    me = r.json()
    assert me["tenants"] == [{"id": owner.tenant_id, "name": "The Lantern", "role": "manager"}]
    # they joined the account; they did not get a business of their own
    assert admin.execute(
        "SELECT count(*) FROM membership WHERE user_id = %s", (me["user_id"],)
    ).fetchone() == (1,)
    # and the session works at once
    assert (await client.get("/v1/auth/me")).json()["email"] == "new@example.com"
    assert (await client.get(f"/v1/tenants/{owner.tenant_id}/businesses")).status_code == 200


async def test_a_link_works_once(world: World, admin: psycopg.Connection[Any]) -> None:
    owner = await sign_up(world)
    made = await invite(owner)
    _, first = await signup_with(world, made["token"], "one@example.com")
    assert first.status_code == 201
    _, second = await signup_with(world, made["token"], "two@example.com")
    assert second.status_code == 410
    # the refused signup left nothing behind: no account for the second address
    assert admin.execute(
        "SELECT count(*) FROM app_user WHERE email = 'two@example.com'"
    ).fetchone() == (0,)
    peek = (await look(world, made["token"])).json()
    assert peek["state"] == "used" and "already been used" in peek["reason"]


async def test_two_people_racing_for_one_link_yield_exactly_one_member(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    made = await invite(owner)
    results = await asyncio.gather(
        *[signup_with(world, made["token"], f"race{i}@example.com") for i in range(5)]
    )
    codes = sorted(r.status_code for _, r in results)
    assert codes.count(201) == 1 and set(codes) <= {201, 410}, codes
    assert admin.execute(
        "SELECT count(*) FROM membership WHERE tenant_id = %s AND role <> 'owner'",
        (owner.tenant_id,),
    ).fetchone() == (1,)
    assert admin.execute("SELECT count(*) FROM app_user WHERE email LIKE 'race%'").fetchone() == (
        1,
    )


async def test_an_existing_person_accepts_a_link_and_keeps_their_own_account(
    world: World,
) -> None:
    owner = await sign_up(world, "own@example.com", "The Lantern")
    other = await sign_up(world, "other@example.com", "The Anchor")
    made = await invite(owner, "viewer")
    r = await other.client.post(
        "/v1/invitations/accept", headers=other.headers, json={"token": made["token"]}
    )
    assert r.status_code == 200 and r.json() == {"tenant_id": owner.tenant_id}
    me = (await other.client.get("/v1/auth/me")).json()
    assert {(t["name"], t["role"]) for t in me["tenants"]} == {
        ("The Anchor", "owner"),
        ("The Lantern", "viewer"),
    }
    again = await other.client.post(
        "/v1/invitations/accept", headers=other.headers, json={"token": made["token"]}
    )
    assert again.status_code == 410


async def test_accepting_needs_a_session_and_the_csrf_header(world: World) -> None:
    owner = await sign_up(world)
    other = await sign_up(world)
    made = await invite(owner)
    body = {"token": made["token"]}
    assert (await world.client().post("/v1/invitations/accept", json=body)).status_code == 401
    no_csrf = await other.client.post("/v1/invitations/accept", json=body)
    assert no_csrf.status_code == 403
    # neither attempt used the link
    peek = (await look(world, made["token"])).json()
    assert peek["state"] == "open"


async def test_someone_already_in_the_account_is_refused_and_their_role_is_unchanged(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    made = await invite(owner, "viewer")
    r = await owner.client.post(
        "/v1/invitations/accept", headers=owner.headers, json={"token": made["token"]}
    )
    assert r.status_code == 409
    assert admin.execute(
        "SELECT role FROM membership WHERE user_id = %s", (owner.me["user_id"],)
    ).fetchall() == [("owner",)]
    # the failed attempt did not burn the link
    assert (await look(world, made["token"])).json()["state"] == "open"


async def test_a_revoked_link_and_an_expired_link_both_fail_with_their_own_reason(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    revoked = await invite(owner)
    expired = await invite(owner)
    d = await owner.client.delete(
        owner.url(f"/team/invitations/{revoked['id']}"), headers=owner.headers
    )
    assert d.status_code == 204
    admin.execute(
        "UPDATE invitation SET expires_at = now() - interval '1 second', created_at = now() - interval '1 day' WHERE id = %s",
        (expired["id"],),
    )
    c = world.client()
    p1 = (await c.post("/v1/invitations/peek", json={"token": revoked["token"]})).json()
    p2 = (await c.post("/v1/invitations/peek", json={"token": expired["token"]})).json()
    assert (p1["state"], p2["state"]) == ("revoked", "expired")
    assert "withdrawn" in p1["reason"] and "expired" in p2["reason"]
    for made in (revoked, expired):
        _, r = await signup_with(world, made["token"], f"late{made['id'][:4]}@example.com")
        assert r.status_code == 410, r.text
    assert admin.execute("SELECT count(*) FROM app_user WHERE email LIKE 'late%'").fetchone() == (
        0,
    )
    listing = (await owner.get("/team")).json()
    assert listing["invitations"] == []  # neither is offered as still open


async def test_signup_is_a_business_name_or_a_link_never_both_and_never_neither(
    world: World,
) -> None:
    owner = await sign_up(world)
    made = await invite(owner)
    c = world.client()
    both = await c.post(
        "/v1/auth/signup",
        json={
            "email": "b@example.com",
            "password": PASSWORD,
            "business_name": "X",
            "invite_token": made["token"],
        },
    )
    neither = await c.post("/v1/auth/signup", json={"email": "n@example.com", "password": PASSWORD})
    assert both.status_code == 422 and neither.status_code == 422
    junk = await c.post(
        "/v1/auth/signup",
        json={"email": "j@example.com", "password": PASSWORD, "invite_token": "not a token!"},
    )
    assert junk.status_code == 422
    unknown = await c.post(
        "/v1/auth/signup",
        json={"email": "u@example.com", "password": PASSWORD, "invite_token": NO_TOKEN},
    )
    assert unknown.status_code == 404
    # none of them used the real link
    assert (await look(world, made["token"])).json()["state"] == "open"


async def test_a_duplicate_email_through_a_link_is_a_409_and_does_not_burn_it(
    world: World,
) -> None:
    owner = await sign_up(world, "own@example.com")
    made = await invite(owner)
    _, r = await signup_with(world, made["token"], "OWN@example.com")
    assert r.status_code == 409
    assert (await look(world, made["token"])).json()["state"] == "open"


# ---- who may do what ---------------------------------------------------------------------------------------------
async def test_only_an_owner_can_invite_change_roles_or_remove(world: World) -> None:
    owner = await sign_up(world, "own@example.com")
    manager = await member_of(world, owner, "manager", "mgr@example.com")
    viewer = await member_of(world, owner, "viewer", "view@example.com")
    victim = viewer.me["user_id"]
    for who in (manager, viewer):
        base = f"/v1/tenants/{owner.tenant_id}/team"
        assert (
            await who.client.post(
                f"{base}/invitations", headers=who.headers, json={"role": "viewer"}
            )
        ).status_code == 403
        assert (
            await who.client.put(
                f"{base}/members/{victim}", headers=who.headers, json={"role": "owner"}
            )
        ).status_code == 403
        assert (
            await who.client.delete(f"{base}/members/{victim}", headers=who.headers)
        ).status_code == 403
        assert (
            await who.client.delete(f"{base}/invitations/{victim}", headers=who.headers)
        ).status_code == 403
    # every one of them can read the people list; only an owner sees the open links
    for who in (manager, viewer):
        listing = (await who.client.get(f"/v1/tenants/{owner.tenant_id}/team")).json()
        assert {m["email"] for m in listing["members"]} == {
            "own@example.com",
            "mgr@example.com",
            "view@example.com",
        }
        assert listing["invitations"] == []
        assert [m["you"] for m in listing["members"] if m["user_id"] == who.me["user_id"]] == [True]


async def test_an_owner_changes_a_role_and_it_takes_effect_at_once(world: World) -> None:
    owner = await sign_up(world, "own@example.com")
    member = await member_of(world, owner, "viewer", "m@example.com")
    base = f"/v1/tenants/{owner.tenant_id}"
    blocked = await member.client.post(
        f"{base}/businesses",
        headers=member.headers,
        json={"name": "X", "type": "bar", "currency": "GBP"},
    )
    assert blocked.status_code == 403
    r = await owner.client.put(
        f"{base}/team/members/{member.me['user_id']}",
        headers=owner.headers,
        json={"role": "manager"},
    )
    assert r.status_code == 200
    assert {m["email"]: m["role"] for m in r.json()["members"]}["m@example.com"] == "manager"
    allowed = await member.client.post(
        f"{base}/businesses",
        headers=member.headers,
        json={"name": "X", "type": "bar", "currency": "GBP"},
    )
    assert allowed.status_code == 201, allowed.text


async def test_a_removed_person_loses_the_account_at_once_and_keeps_their_login(
    world: World,
) -> None:
    owner = await sign_up(world, "own@example.com")
    member = await member_of(world, owner, "manager", "m@example.com")
    base = f"/v1/tenants/{owner.tenant_id}"
    assert (await member.client.get(f"{base}/businesses")).status_code == 200
    d = await owner.client.delete(
        f"{base}/team/members/{member.me['user_id']}", headers=owner.headers
    )
    assert d.status_code == 204
    assert (await member.client.get(f"{base}/businesses")).status_code in (403, 404)
    assert (await member.client.get(f"{base}/team")).status_code in (403, 404)
    me = (await member.client.get("/v1/auth/me")).json()
    assert me["tenants"] == []  # still signed in, belongs to nothing


async def test_the_last_owner_cannot_be_removed_or_demoted_but_a_second_owner_can_leave(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world, "own@example.com")
    base = f"/v1/tenants/{owner.tenant_id}/team"
    me = owner.me["user_id"]
    demote = await owner.client.put(
        f"{base}/members/{me}", headers=owner.headers, json={"role": "viewer"}
    )
    remove = await owner.client.delete(f"{base}/members/{me}", headers=owner.headers)
    assert (demote.status_code, remove.status_code) == (409, 409)
    assert "at least one owner" in demote.json()["detail"]
    second = await member_of(world, owner, "manager", "two@example.com")
    promote = await owner.client.put(
        f"{base}/members/{second.me['user_id']}", headers=owner.headers, json={"role": "owner"}
    )
    assert promote.status_code == 200
    # now there are two owners: the first may step down, the second may not
    assert (
        await owner.client.put(
            f"{base}/members/{me}", headers=owner.headers, json={"role": "viewer"}
        )
    ).status_code == 200
    last = await second.client.delete(
        f"{base}/members/{second.me['user_id']}", headers=second.headers
    )
    assert last.status_code == 409
    assert admin.execute(
        "SELECT count(*) FROM membership WHERE tenant_id = %s AND role = 'owner'",
        (owner.tenant_id,),
    ).fetchone() == (1,)


async def test_the_database_itself_refuses_to_orphan_an_account_and_still_allows_deleting_it(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    for sql in (
        "DELETE FROM membership WHERE tenant_id = %s",
        "UPDATE membership SET role = 'viewer' WHERE tenant_id = %s",
    ):
        with pytest.raises(psycopg.errors.RaiseException, match="at least one owner"):
            admin.execute(sql, (owner.tenant_id,))
    admin.execute("DELETE FROM tenant WHERE id = %s", (owner.tenant_id,))
    assert admin.execute(
        "SELECT count(*) FROM membership WHERE tenant_id = %s", (owner.tenant_id,)
    ).fetchone() == (0,)


async def test_a_role_change_for_someone_who_is_not_in_the_account_is_a_404(world: World) -> None:
    owner = await sign_up(world)
    stranger = await sign_up(world)
    base = f"/v1/tenants/{owner.tenant_id}/team"
    r = await owner.client.put(
        f"{base}/members/{stranger.me['user_id']}", headers=owner.headers, json={"role": "viewer"}
    )
    d = await owner.client.delete(f"{base}/members/{stranger.me['user_id']}", headers=owner.headers)
    assert (r.status_code, d.status_code) == (404, 404)
    # and the stranger's own account was not touched
    assert (await stranger.client.get(f"/v1/tenants/{stranger.tenant_id}/team")).status_code == 200


# ---- isolation ---------------------------------------------------------------------------------------------------
async def test_one_account_never_sees_or_revokes_another_accounts_people_or_links(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    a = await sign_up(world, "a@example.com", "Account A")
    b = await sign_up(world, "b@example.com", "Account B")
    made = await invite(a)
    await member_of(world, a, "viewer", "va@example.com")
    # B reading A's people, and B's own tenant path, with B's session
    assert (await b.client.get(f"/v1/tenants/{a.tenant_id}/team")).status_code in (403, 404)
    listing = (await b.get("/team")).json()
    assert [m["email"] for m in listing["members"]] == ["b@example.com"]
    # B revoking or creating against A
    assert (
        await b.client.delete(
            f"/v1/tenants/{a.tenant_id}/team/invitations/{made['id']}", headers=b.headers
        )
    ).status_code in (403, 404)
    assert (
        await b.client.post(
            f"/v1/tenants/{a.tenant_id}/team/invitations",
            headers=b.headers,
            json={"role": "viewer"},
        )
    ).status_code in (403, 404)
    # B's own owner cannot revoke A's link through B's tenant path either
    cross = await b.client.delete(b.url(f"/team/invitations/{made['id']}"), headers=b.headers)
    assert cross.status_code == 404
    assert admin.execute(
        "SELECT revoked_at FROM invitation WHERE id = %s", (made["id"],)
    ).fetchone() == (None,)


async def test_the_member_list_function_answers_only_members_of_that_account(
    world: World,
) -> None:
    """Called as the application's own database role, the way the API calls it: a member gets the list, a stranger gets nothing."""
    a = await sign_up(world, "a@example.com")
    b = await sign_up(world, "b@example.com")
    dsn = APP_URL.replace("postgresql+asyncpg://", "postgresql://")
    with psycopg.connect(dsn) as conn:

        def members(as_user: str, tenant: str) -> list[Any]:
            conn.execute("SELECT set_config('app.user_id', %s, true)", (as_user,))
            rows = conn.execute("SELECT email FROM team_members(%s)", (tenant,)).fetchall()
            conn.rollback()
            return rows

        assert members(a.me["user_id"], a.tenant_id) == [("a@example.com",)]
        assert members(b.me["user_id"], a.tenant_id) == []
        assert members("00000000-0000-4000-8000-000000000000", a.tenant_id) == []
        # nobody can ask on behalf of someone else: the accept function checks the caller is the user named
        conn.execute("SELECT set_config('app.user_id', %s, true)", (b.me["user_id"],))
        try:
            conn.execute(
                "SELECT invitation_accept(%s, %s)", (token_hash(NO_TOKEN), a.me["user_id"])
            )
        except psycopg.errors.InsufficientPrivilege:
            pass
        else:  # pragma: no cover
            raise AssertionError("accepting as another person was allowed")


# ---- bookkeeping ---------------------------------------------------------------------------------------------------
async def test_every_team_change_is_written_to_the_audit_log_without_the_token(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world, "own@example.com")
    made = await invite(owner, "manager")
    other = await invite(owner, "viewer")
    member = await member_of(world, owner, "viewer", "m@example.com")
    base = f"/v1/tenants/{owner.tenant_id}/team"
    await owner.client.delete(f"{base}/invitations/{other['id']}", headers=owner.headers)
    await owner.client.put(
        f"{base}/members/{member.me['user_id']}", headers=owner.headers, json={"role": "manager"}
    )
    await owner.client.delete(f"{base}/members/{member.me['user_id']}", headers=owner.headers)
    actions = [
        a
        for (a,) in admin.execute(
            "SELECT action FROM audit_log WHERE action LIKE 'team.%' ORDER BY id"
        ).fetchall()
    ]
    assert actions == [
        "team.invite.manager",
        "team.invite.viewer",
        "team.invite.viewer",
        "team.revoke",
        "team.role.manager",
        "team.remove",
    ]
    dump = admin.execute("SELECT string_agg(row_to_json(a)::text, ' ') FROM audit_log a").fetchone()
    assert dump is not None and made["token"] not in (dump[0] or "")


async def test_open_invitations_are_capped_and_creation_is_rate_limited(world: World) -> None:
    owner = await sign_up(world)
    codes = [
        (await owner.post("/team/invitations", json={"role": "viewer"})).status_code
        for _ in range(21)
    ]
    assert codes[:20] == [201] * 20 and codes[20] == 409
    listing = (await owner.get("/team")).json()
    assert len(listing["invitations"]) == 20 and listing["limits"]["max_open"] == 20
    # revoking one frees a place
    first = listing["invitations"][0]["id"]
    assert (
        await owner.client.delete(owner.url(f"/team/invitations/{first}"), headers=owner.headers)
    ).status_code == 204
    assert (await owner.post("/team/invitations", json={"role": "viewer"})).status_code == 201
    # revoking something that is already revoked is a 404, not a 500
    again = await owner.client.delete(
        owner.url(f"/team/invitations/{first}"), headers=owner.headers
    )
    assert again.status_code == 404
    # churning links (make one, withdraw it, make another) is stopped by the hourly limit, not by the cap
    for left in (await owner.get("/team")).json()["invitations"]:
        await owner.client.delete(
            owner.url(f"/team/invitations/{left['id']}"), headers=owner.headers
        )
    seen: set[int] = set()
    for _ in range(15):
        r = await owner.post("/team/invitations", json={"role": "viewer"})
        seen.add(r.status_code)
        if r.status_code == 201:
            await owner.client.delete(
                owner.url(f"/team/invitations/{r.json()['id']}"), headers=owner.headers
            )
        elif r.status_code == 409:
            break
    assert 429 in seen, seen


async def test_a_manager_who_joined_works_in_the_account_like_any_member(world: World) -> None:
    """The point of inviting someone: they land in the account and can do their part, and only that."""
    owner = await sign_up(world, "own@example.com", "The Lantern")
    manager = await member_of(world, owner, "manager", "mgr@example.com")
    base = f"/v1/tenants/{owner.tenant_id}"
    b = await manager.client.post(
        f"{base}/businesses",
        headers=manager.headers,
        json={"name": "Side room", "type": "bar", "currency": "GBP"},
    )
    assert b.status_code == 201, b.text
    seen = (await owner.client.get(f"{base}/businesses")).json()
    assert any(x["name"] == "Side room" for x in seen)
