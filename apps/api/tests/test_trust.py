"""The trust surfaces: the waitlist, the usefulness feedback, and the privacy page's promise that it matches the database."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import psycopg
import pytest
from harness import APP_URL, World, make_venue, sign_up

PRIVACY = Path(__file__).resolve().parents[3] / "apps" / "web" / "src" / "content" / "privacy.json"


async def join(world: World, email: str, **over: Any) -> Any:
    body = {"email": email, "consent": True, "website": "", **over}
    return await world.client().post("/v1/public/waitlist", json=body)


async def test_the_waitlist_keeps_an_email_and_the_consent_version_and_answers_a_repeat_the_same(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    consent = (await world.client().get("/v1/public/waitlist/consent")).json()
    assert (
        consent["version"] == "waitlist-v1"
        and "do not join it to any survey data" in consent["body"]
    )
    first = await join(world, "Owner@Example.com ")
    again = await join(world, "owner@example.com")
    assert first.status_code == again.status_code == 201 and first.json() == again.json() == {
        "joined": True
    }
    rows = admin.execute("SELECT email, consent_version FROM waitlist").fetchall()
    assert (
        rows == [("Owner@example.com", "waitlist-v1")]
    )  # once, with the domain in lower case as email addresses define it, and the text version they saw


async def test_a_script_that_fills_the_hidden_field_gets_the_same_answer_and_leaves_nothing(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    res = await join(world, "bot@example.com", website="http://spam.example")
    assert res.status_code == 201 and res.json() == {"joined": True}
    assert admin.execute("SELECT count(*) FROM waitlist").fetchone() == (0,)


async def test_the_waitlist_refuses_without_consent_and_junk_is_refused_not_stored(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    assert (await join(world, "a@example.com", consent=False)).status_code == 422
    for bad in ("", "nope", "a@", "@b.com", "a b@c.com", "x" * 300 + "@example.com"):
        assert (await join(world, bad)).status_code == 422, bad
    junk = await world.client().post(
        "/v1/public/waitlist", json={"email": "a@example.com", "consent": True, "role": "admin"}
    )
    assert junk.status_code == 422  # unknown fields are refused, never ignored
    assert (
        await world.client().post("/v1/public/waitlist", content=b"not json")
    ).status_code == 422
    assert admin.execute("SELECT count(*) FROM waitlist").fetchone() == (0,)


async def test_the_waitlist_is_rate_limited_per_address(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    codes = [(await join(world, f"p{i}@example.com")).status_code for i in range(8)]
    assert codes[:6] == [201] * 6 and codes[6:] == [429, 429]


def test_the_application_can_add_to_the_waitlist_but_never_read_it(
    admin: psycopg.Connection[Any],
) -> None:
    dsn = APP_URL.replace("postgresql+asyncpg://", "postgresql://")
    with psycopg.connect(dsn, autocommit=True) as app:
        app.execute(
            "INSERT INTO waitlist (email, email_key, consent_version) VALUES ('x@example.com', 'x@example.com', 'v')"
        )
        for statement in (
            "SELECT * FROM waitlist",
            "UPDATE waitlist SET email = 'y'",
            "DELETE FROM waitlist",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                app.execute(statement)  # type: ignore[arg-type]
    columns = {
        r[0]
        for r in admin.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'waitlist'"
        )
    }
    assert columns == {
        "id",
        "email",
        "email_key",
        "consent_version",
        "created_at",
    }  # no tenant, no survey link


async def test_feedback_is_stored_with_nothing_that_says_who_sent_it(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    await make_venue(owner)
    sent = await owner.post(
        "/feedback", json={"kind": "soundcheck", "useful": True, "note": "  Helpful, thanks  "}
    )
    assert sent.status_code == 201 and sent.json() == {"stored": True}
    await owner.post("/feedback", json={"kind": "brief", "useful": False})
    rows = admin.execute("SELECT kind, useful, note FROM feedback ORDER BY id").fetchall()
    assert rows == [("soundcheck", True, "Helpful, thanks"), ("brief", False, None)]
    columns = {
        r[0]
        for r in admin.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'feedback'"
        )
    }
    assert columns == {"id", "kind", "useful", "note", "created_at"}
    assert owner.tenant_id not in json.dumps(rows, default=str)


async def test_feedback_refuses_junk_strangers_and_floods(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    other = await sign_up(world)
    for bad in (
        {"kind": "everything", "useful": True},
        {"kind": "brief", "useful": "yes"},
        {"kind": "brief"},
        {"kind": "brief", "useful": True, "note": "x" * 281},
        {"kind": "brief", "useful": True, "tenant": "x"},
    ):
        assert (await owner.post("/feedback", json=bad)).status_code == 422, bad
    mine = f"/v1/tenants/{owner.tenant_id}/feedback"
    ok = {"kind": "brief", "useful": True}
    assert (await world.client().post(mine, json=ok)).status_code in (401, 403)
    assert (await other.client.post(mine, json=ok, headers=other.headers)).status_code in (403, 404)
    codes = [(await owner.post("/feedback", json=ok)).status_code for _ in range(32)]
    assert codes.count(201) == 30 and codes[-1] == 429
    assert admin.execute("SELECT count(*) FROM feedback").fetchone() == (30,)


def test_the_privacy_page_lists_exactly_the_columns_that_hold_a_guests_answer(
    admin: psycopg.Connection[Any],
) -> None:
    """If a column is added to the guest tables without being listed on the privacy page, this fails."""
    doc = json.loads(PRIVACY.read_text(encoding="utf-8"))
    documented: dict[str, set[str]] = {"response": set(), "pick": set(doc["pick_internal"])}
    for item in doc["stored_per_answer"]:
        documented[item["table"]] |= set(item["columns"])
    for table, listed in documented.items():
        actual = {
            r[0]
            for r in admin.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = %s AND table_schema = 'public'",
                (table,),
            )
        }
        assert actual == listed, (
            f"{table}: undocumented {sorted(actual - listed)}, documented but absent {sorted(listed - actual)}"
        )
