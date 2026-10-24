"""The City Taste Atlas through the database and the API: who may join, what the rebuild is allowed to publish, and what a reader can
and cannot learn. The privacy minimums are enforced by `atlas_rebuild()` and restated as column checks, so most of these tests
look at the database directly. Every name is invented."""

from __future__ import annotations

import random
import uuid
from typing import Any

import psycopg
import pytest
from harness import Owner, Venue, World, make_venue, seed_entities, sign_up
from nigiwai_api import worker
from nigiwai_api.services import atlas as service
from sqlalchemy import text

ARTIST = "urn:entity:artist"
MOVIE = "urn:entity:movie"


def entity(admin: psycopg.Connection[Any], name: str, kind: str = ARTIST) -> str:
    entity_id = str(uuid.uuid4())
    seed_entities(admin, [(entity_id, kind, name)])
    return entity_id


def answer(admin: psycopg.Connection[Any], venue: Venue, picks: list[tuple[str, str]]) -> None:
    """One guest's response with these (entity id, type) picks, through the same database function the survey uses."""
    survey = admin.execute(
        "SELECT id, version FROM survey WHERE business_id = %s AND status = 'published'",
        (venue.business_id,),
    ).fetchone()
    assert survey is not None
    admin.execute(
        "SELECT public_insert_response(%s, %s, %s, 'v1', NULL, NULL, NULL, 'ok', %s, %s, %s)",
        (
            venue.qr["id"],
            survey[0],
            survey[1],
            [p[0] for p in picks],
            [p[1] for p in picks],
            uuid.uuid4().bytes,
        ),
    )


async def venues(world: World, n: int) -> list[tuple[Owner, Venue]]:
    out: list[tuple[Owner, Venue]] = []
    for _ in range(n):
        owner = await sign_up(world)
        out.append((owner, await make_venue(owner)))
    return out


async def join(owner: Owner, venue: Venue) -> dict[str, Any]:
    res = await owner.put(f"/businesses/{venue.business_id}/atlas", json={"opt_in": True})
    assert res.status_code == 200, res.text
    doc: dict[str, Any] = res.json()
    return doc


async def rebuild(world: World, admin: psycopg.Connection[Any]) -> None:
    """Run the queued rebuild jobs the way the worker does."""
    admin.execute("UPDATE job SET run_after = now() WHERE state = 'pending'")
    state = world.app.state.nigiwai
    while await worker.work_once(state.engine, state.guard):
        pass


async def rebuild_now(world: World) -> int:
    """Rebuild straight away, as the six-hourly sweep does, after the test has changed the data underneath."""
    return await service.rebuild(world.app.state.nigiwai.engine)


class Items:
    """Five items with the shapes the minimums are about, and a way to give each of five venues its twelve guests."""

    def __init__(self, admin: psycopg.Connection[Any]) -> None:
        self.everyone = entity(admin, "Sample Act Everyone")
        self.three_venues = entity(admin, "Sample Act Three Venues")
        self.nine = entity(admin, "Sample Act Nine")
        self.one_venue = entity(admin, "Sample Act One Venue")
        self.one_dominates = entity(admin, "Sample Act One Dominates", MOVIE)

    def picks(self, v: int, i: int) -> list[tuple[str, str]]:
        out = [(self.everyone, ARTIST)]  # all 60 responses
        if v < 3 and i < 4:
            out.append((self.three_venues, ARTIST))  # 4 + 4 + 4 = 12 responses from 3 venues
        if v < 3 and 4 <= i < 7:
            out.append((self.nine, ARTIST))  # 3 + 3 + 3 = 9 responses: one short
        if v == 0:
            out.append((self.one_venue, ARTIST))  # 12 responses, but from one venue
        if (v == 0 and i < 11) or (v > 0 and i == 0):
            out.append(
                (self.one_dominates, MOVIE)
            )  # 11 + 1 + 1 + 1 + 1 = 15 responses, 11 from one venue
        return out


def fill(
    admin: psycopg.Connection[Any], items: Items, group: list[tuple[Owner, Venue]], each: int = 12
) -> None:
    for v, (_, venue) in enumerate(group):
        for i in range(each):
            answer(admin, venue, items.picks(v, i))


def cells(admin: psycopg.Connection[Any]) -> list[tuple[Any, ...]]:
    return admin.execute(
        "SELECT cell_x, cell_y, entity_id, responses, venues, cell_responses, cell_venues FROM atlas_cell"
        " ORDER BY responses DESC, entity_id"
    ).fetchall()


# ----------------------------------------------------------------------------------------------- the rebuild
async def test_five_venues_open_a_cell_and_only_items_that_meet_every_minimum_are_listed(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    group = await venues(world, 5)
    items = Items(admin)
    fill(admin, items, group)
    for owner, venue in group:
        await join(owner, venue)
    await rebuild(world, admin)

    rows = cells(admin)
    listed = {r[2]: r for r in rows}
    assert set(listed) == {items.everyone, items.three_venues}
    everyone = listed[items.everyone]
    assert (everyone[3], everyone[4], everyone[5], everyone[6]) == (60, 5, 60, 5)
    three = listed[items.three_venues]
    assert (three[3], three[4]) == (12, 3)
    # the one that was 9 responses, the one from a single venue, and the one a single venue supplied most of: none is published
    assert items.nine not in listed
    assert items.one_venue not in listed
    assert items.one_dominates not in listed
    assert (everyone[0], everyone[1]) == service.cell_of(51.5, -0.12)


async def test_the_page_shows_the_cell_to_a_venue_that_joined_and_withholds_small_counts_of_its_own(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    group = await venues(world, 5)
    items = Items(admin)
    fill(admin, items, group)
    for owner, venue in group:
        await join(owner, venue)
    await rebuild(world, admin)

    owner, venue = group[0]
    doc = (await owner.get(f"/businesses/{venue.business_id}/atlas")).json()
    assert doc["state"] == "ready"
    assert doc["opted_in"] is True
    assert doc["cell_responses"] == 60
    assert [g["type"] for g in doc["groups"]] == [ARTIST]
    by_name = {i["name"]: i for i in doc["groups"][0]["items"]}
    assert set(by_name) == {"Sample Act Everyone", "Sample Act Three Venues"}
    everyone = by_name["Sample Act Everyone"]
    assert (everyone["responses"], everyone["venues"], everyone["share"]) == (60, 5, 1.0)
    assert everyone["own"] == 12  # its own twelve guests: a count of ten or more may be shown
    assert (
        by_name["Sample Act Three Venues"]["own"] is None
    )  # four of its own guests: under the minimum, so not a number
    # nothing in the answer says which venue supplied what, or how many venues are in the cell
    text_ = str(doc)
    assert venue.business_id not in text_ and "cell_venues" not in text_
    assert doc["limits"]["venues_in_cell"] == 5


async def test_four_venues_are_not_a_cell_and_the_page_says_only_that_it_is_waiting(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    group = await venues(world, 4)
    items = Items(admin)
    fill(admin, items, group)
    for owner, venue in group:
        await join(owner, venue)
    await rebuild(world, admin)
    assert cells(admin) == []
    doc = (await group[0][0].get(f"/businesses/{group[0][1].business_id}/atlas")).json()
    assert doc["state"] == "waiting"
    assert doc["groups"] == [] and doc["cell_responses"] is None
    assert "at least 5" in doc["reason"]


async def test_a_venue_with_fewer_than_ten_answers_does_not_count_toward_the_cell(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    group = await venues(world, 5)
    items = Items(admin)
    fill(admin, items, group[:4])
    fill(admin, items, group[4:], each=9)  # nine answers: not enough to count as a venue
    for owner, venue in group:
        await join(owner, venue)
    await rebuild(world, admin)
    assert cells(admin) == []
    # the tenth answer opens the cell
    answer(admin, group[4][1], items.picks(4, 0))
    await rebuild_now(world)
    assert len(cells(admin)) >= 1


async def test_quarantined_answers_and_venues_in_another_cell_do_not_count(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    group = await venues(world, 5)
    items = Items(admin)
    fill(admin, items, group)
    for owner, venue in group:
        await join(owner, venue)
    await rebuild_now(world)
    assert len(cells(admin)) == 2
    # three of one venue's twelve answers are held back: it falls under ten and the cell loses a venue
    admin.execute(
        "UPDATE response SET quality_flag = 'quarantined' WHERE id IN"
        " (SELECT r.id FROM response r JOIN qr_point q ON q.id = r.qr_point_id WHERE q.id = %s LIMIT 3)",
        (group[4][1].qr["id"],),
    )
    await rebuild_now(world)
    assert cells(admin) == []
    # a venue that moved across town is in another cell
    admin.execute("UPDATE response SET quality_flag = 'ok'")
    await rebuild_now(world)
    assert len(cells(admin)) == 2
    admin.execute(
        "UPDATE location SET geom = ST_SetSRID(ST_MakePoint(-0.30, 51.5), 4326)::geography WHERE id = %s",
        (group[3][1].location_id,),
    )
    await rebuild_now(world)
    assert cells(admin) == []


async def test_leaving_takes_the_venue_out_at_once_and_is_written_to_the_audit_log(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    group = await venues(world, 5)
    items = Items(admin)
    fill(admin, items, group)
    for owner, venue in group:
        await join(owner, venue)
    await rebuild(world, admin)
    assert len(cells(admin)) == 2

    owner, venue = group[0]
    left = await owner.put(f"/businesses/{venue.business_id}/atlas", json={"opt_in": False})
    assert left.status_code == 200
    assert left.json()["state"] == "not_joined"
    assert left.json()["groups"] == []
    pending = admin.execute(
        "SELECT count(*) FROM job WHERE kind = 'atlas_rebuild' AND state = 'pending'"
    ).fetchone()
    assert pending == (1,)
    await rebuild(world, admin)
    assert cells(admin) == []  # four venues are not a cell
    actions = [
        r[0]
        for r in admin.execute(
            "SELECT action FROM audit_log WHERE action LIKE 'atlas.%%' AND target = %s ORDER BY id",
            (venue.business_id,),
        ).fetchall()
    ]
    assert actions == ["atlas.join", "atlas.leave"]
    # asking again for what is already so changes nothing and writes nothing more
    again = await owner.put(f"/businesses/{venue.business_id}/atlas", json={"opt_in": False})
    assert again.status_code == 200
    assert admin.execute(
        "SELECT count(*) FROM audit_log WHERE action LIKE 'atlas.%%'"
    ).fetchone() == (6,)


async def test_a_venue_that_has_not_joined_sees_nothing_even_when_its_cell_is_open(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    group = await venues(world, 6)
    items = Items(admin)
    fill(admin, items, group)
    for owner, venue in group[:5]:
        await join(owner, venue)
    await rebuild(world, admin)
    assert len(cells(admin)) == 2
    outsider, venue = group[5]
    doc = (await outsider.get(f"/businesses/{venue.business_id}/atlas")).json()
    assert doc["state"] == "not_joined"
    assert doc["groups"] == [] and doc["cell_responses"] is None
    # and it contributed nothing: its answers are not in the counts
    assert cells(admin)[0][3] == 60


# ----------------------------------------------------------------------------- what the database itself refuses
def test_a_row_below_a_minimum_cannot_be_written_even_by_hand(
    admin: psycopg.Connection[Any],
) -> None:
    ok = (1, 1, "e", ARTIST, 10, 3, 10, 5)
    for bad in (
        (1, 1, "e", ARTIST, 9, 3, 10, 5),  # too few responses
        (1, 1, "e", ARTIST, 10, 2, 10, 5),  # too few venues for the item
        (1, 1, "e", ARTIST, 10, 3, 10, 4),  # too few venues in the cell
        (1, 1, "e", ARTIST, 10, 3, 9, 5),  # more responses for the item than the cell has
    ):
        with pytest.raises(psycopg.errors.CheckViolation):
            admin.execute(
                "INSERT INTO atlas_cell (cell_x, cell_y, entity_id, entity_type, responses, venues, cell_responses, cell_venues)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                bad,
            )
    admin.execute(
        "INSERT INTO atlas_cell (cell_x, cell_y, entity_id, entity_type, responses, venues, cell_responses, cell_venues)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        ok,
    )
    admin.execute("DELETE FROM atlas_cell")


def test_the_table_has_no_column_that_could_name_a_venue_a_tenant_or_a_place_of_business(
    admin: psycopg.Connection[Any],
) -> None:
    columns = {
        r[0]
        for r in admin.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'atlas_cell'"
        ).fetchall()
    }
    assert columns == {
        "cell_x",
        "cell_y",
        "entity_id",
        "entity_type",
        "responses",
        "venues",
        "cell_responses",
        "cell_venues",
        "built_at",
    }


async def test_the_application_role_can_read_and_rebuild_the_atlas_but_never_write_it(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    engine = world.app.state.nigiwai.engine
    async with engine.begin() as conn:
        assert (await conn.execute(text("SELECT count(*) FROM atlas_cell"))).scalar_one() == 0
        built = (await conn.execute(text("SELECT atlas_rebuild()"))).scalar_one()
        assert built == 0
    for statement in (
        "INSERT INTO atlas_cell (cell_x, cell_y, entity_id, entity_type, responses, venues, cell_responses, cell_venues)"
        " VALUES (1, 1, 'e', 'urn:entity:artist', 10, 3, 10, 5)",
        "DELETE FROM atlas_cell",
        "UPDATE atlas_cell SET responses = 99",
    ):
        with pytest.raises(Exception, match="permission denied"):
            async with engine.begin() as conn:
                await conn.execute(text(statement))


def test_the_cell_a_point_falls_in_is_named_the_same_way_in_python_and_in_the_database(
    admin: psycopg.Connection[Any],
) -> None:
    rng = random.Random(3)
    points = [
        (51.5, -0.12),
        (40.722, -73.9868),
        (41.9138, -87.6625),
        (-33.8688, 151.2093),
        (0.0, 0.0),
        (-0.004, 0.004),
    ]
    points += [(rng.uniform(-80, 80), rng.uniform(-179, 179)) for _ in range(200)]
    for lat, lon in points:
        got = admin.execute(
            "SELECT floor(ST_X(g::geometry) * 100)::int, floor(ST_Y(g::geometry) * 100)::int"
            " FROM (SELECT ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography AS g) t",
            (lon, lat),
        ).fetchone()
        assert got == service.cell_of(lat, lon), (lat, lon)


# --------------------------------------------------------------------------------------------- who may do what
async def test_joining_needs_an_address_and_the_right_to_change_the_account(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    bare = await owner.post(
        "/businesses", json={"name": "No Address", "type": "bar", "currency": "GBP"}
    )
    business_id = bare.json()["id"]
    state = (await owner.get(f"/businesses/{business_id}/atlas")).json()
    assert state["state"] == "no_location"
    refused = await owner.put(f"/businesses/{business_id}/atlas", json={"opt_in": True})
    assert refused.status_code == 422
    assert "Add your address" in refused.json()["detail"]
    junk = await owner.put(f"/businesses/{business_id}/atlas", json={"opt_in": "yes"})
    assert junk.status_code == 422
    extra = await owner.put(
        f"/businesses/{business_id}/atlas", json={"opt_in": True, "cell": [1, 2]}
    )
    assert extra.status_code == 422

    venue = await make_venue(owner)
    viewer = await sign_up(world)
    admin.execute(
        "INSERT INTO membership (tenant_id, user_id, role) VALUES (%s, %s, 'viewer')",
        (owner.tenant_id, viewer.me["user_id"]),
    )
    root = f"/v1/tenants/{owner.tenant_id}/businesses/{venue.business_id}/atlas"
    assert (await viewer.client.get(root)).status_code == 200
    assert (
        await viewer.client.put(root, json={"opt_in": True}, headers=viewer.headers)
    ).status_code == 403
    assert admin.execute(
        "SELECT atlas_opt_in FROM business WHERE id = %s", (venue.business_id,)
    ).fetchone() == (False,)


async def test_another_account_cannot_read_or_change_a_venues_atlas(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    other = await sign_up(world)
    root = f"/v1/tenants/{other.tenant_id}/businesses/{venue.business_id}/atlas"
    assert (await other.client.get(root)).status_code == 404
    assert (
        await other.client.put(root, json={"opt_in": True}, headers=other.headers)
    ).status_code == 404
    anonymous = f"/v1/tenants/{owner.tenant_id}/businesses/{venue.business_id}/atlas"
    assert (await world.client().get(anonymous)).status_code == 401
    assert admin.execute(
        "SELECT atlas_opt_in FROM business WHERE id = %s", (venue.business_id,)
    ).fetchone() == (False,)
