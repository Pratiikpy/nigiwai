"""The Sound plan through the backend: stored groups with when they scan, the acts a suggestion run scored for them, and a
plan by time of week that makes no Qloo call. Qloo is scripted; every name is invented."""

from __future__ import annotations

import json
import uuid
from typing import Any

import psycopg
from harness import World, make_venue, sign_up
from nigiwai_api import worker
from nigiwai_api.services import tribes as tribe_service
from test_soundcheck import add_artist, base, plant_lineup
from test_tribes import FAST, plant

ALL_WEEK = json.dumps([{"open": "07:00", "close": "02:00"}] * 7)


async def timed_crowd(world: World, admin: psycopg.Connection[Any], owner: Any, venue: Any) -> None:
    """A hundred and fifty guests in three planted groups, each scanning at its own time: group 0 on weekday mornings, group 1 on
    weekend evenings and group 2 late on weekends. The groups are fitted after the times are set, so the groups' rhythms
    carry them."""
    ids = plant(admin, venue, 150)
    for i, e in enumerate(ids):
        world.qloo.group_of[e] = i // 24
        world.qloo.names[e] = f"Item {i // 24}-{i % 24}"
    rows = admin.execute(
        "SELECT r.id, p.entity_id FROM response r JOIN pick p ON p.response_id = r.id AND p.position = 1 ORDER BY r.id"
    ).fetchall()
    assert len(rows) == 150
    seen = {0: 0, 1: 0, 2: 0}
    for rid, entity in rows:
        g = world.qloo.group_of[str(entity)]
        k = seen[g]
        seen[g] += 1
        weekday, hour = {0: (k % 4, 9), 1: (4 + k % 3, 19), 2: (4 + k % 3, 23)}[g]
        admin.execute(
            "UPDATE response SET local_weekday = %s, local_hour = %s WHERE id = %s",
            (weekday, hour, rid),
        )
    await tribe_service.recompute(
        world.app.state.nigiwai.engine,
        None,
        uuid.UUID(owner.tenant_id),
        uuid.UUID(venue.business_id),
        force=True,
        cfg=FAST,
    )


async def build_acts(world: World, admin: psycopg.Connection[Any], owner: Any, venue: Any) -> None:
    for g in range(3):
        for i in range(9):
            add_artist(admin, world, f"Neighbour {g}-{i}", g, popularity=0.05 + 0.1 * i)
    assert (await owner.post(f"{base(owner, venue)}/suggestions")).status_code == 202
    admin.execute("UPDATE job SET run_after = now() WHERE state = 'pending'")
    state = world.app.state.nigiwai
    while await worker.work_once(state.engine, state.guard):
        pass


async def plan(owner: Any, venue: Any) -> dict[str, Any]:
    res = await owner.get(f"{base(owner, venue)}/sound")
    assert res.status_code == 200, res.text
    out: dict[str, Any] = res.json()
    return out


def cell(doc: dict[str, Any], key: str) -> dict[str, Any]:
    return next(c for c in doc["plan"]["cells"] if c["key"] == key)


async def test_each_stretch_of_the_week_gets_the_acts_of_the_group_who_comes_then(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    admin.execute("UPDATE location SET hours = %s::jsonb", (ALL_WEEK,))
    await timed_crowd(world, admin, owner, venue)
    await build_acts(world, admin, owner, venue)
    calls_before = len(world.qloo.calls)

    doc = await plan(owner, venue)
    assert doc["state"] == "ready"
    assert doc["kind"] == "timed"
    assert doc["basis"]["kind"] == "guests"
    assert doc["has_hours"] is True
    assert doc["business_type"] == "live_music_venue"
    assert doc["plan"]["acts_considered"] >= 9
    assert "Score = 100 x group fit" in doc["plan"]["formula"]
    assert any("not songs" in n for n in doc["notes"])

    morning = cell(doc, "weekdays-morning")
    assert morning["status"] == "ok"
    assert morning["scans"] >= 20
    assert morning["acts"][0]["name"].startswith("Neighbour 0-")
    evening = cell(doc, "weekend-evening")
    assert evening["acts"][0]["name"].startswith("Neighbour 1-")
    late = cell(doc, "weekend-late")
    assert late["acts"][0]["name"].startswith("Neighbour 2-")
    for c in (morning, evening, late):
        assert len(c["acts"]) <= 5
        assert all(
            "watch" in a for a in c["acts"]
        )  # each act says whether it ranks poorly for part of the stretch
        scores = [a["score"] for a in c["acts"]]
        assert scores == sorted(scores, reverse=True)
        assert c["busy_label"] in ("busy", "steady", "quiet")
        assert (
            c["mix"][0]["share"] >= 0.7
        )  # most of each stretch is one group; guests are soft members
    assert (
        cell(doc, "weekdays-afternoon")["status"] == "thin"
    )  # nobody scans then: nothing is guessed
    assert cell(doc, "weekdays-afternoon")["acts"] == []

    # the plan is read from what is stored: no Qloo call is made to show it
    assert len(world.qloo.calls) == calls_before

    # the list of suggested acts people see does not carry the wider scored pool
    got = (await owner.get(f"{base(owner, venue)}/suggestions")).json()
    assert "pool" not in got["result"]
    assert len(got["result"]["top"]) == 3


async def test_closed_hours_leave_a_stretch_out_of_the_plan(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    admin.execute(
        "UPDATE location SET hours = %s::jsonb",
        ('[{"open": "08:00", "close": "17:00"}, null, null, null, null, null, null]',),
    )
    await timed_crowd(world, admin, owner, venue)
    await build_acts(world, admin, owner, venue)
    doc = await plan(owner, venue)
    assert cell(doc, "weekend-late")["status"] == "closed"
    assert cell(doc, "weekend-late")["acts"] == []
    assert cell(doc, "weekdays-late")["status"] == "closed"


async def test_it_says_what_is_missing_instead_of_inventing_a_plan(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    none_yet = await plan(owner, venue)
    assert none_yet["state"] == "no_crowd"
    assert none_yet["plan"] is None
    assert "60 guests" in none_yet["reason"]

    await timed_crowd(world, admin, owner, venue)
    no_acts = await plan(owner, venue)
    assert no_acts["state"] == "needs_acts"
    assert no_acts["can_build"] is True

    await build_acts(world, admin, owner, venue)
    assert (await plan(owner, venue))["state"] == "ready"

    # a suggestion run kept before the pool existed has nothing to rank
    admin.execute("UPDATE act_suggestion SET result = result - 'pool'")
    assert (await plan(owner, venue))["state"] == "needs_acts"

    # acts scored for another version of the crowd are not used for this one
    admin.execute(
        "UPDATE act_suggestion SET result = jsonb_set(result, '{pool}', '[]'::jsonb), basis_ref = 'an older version'"
    )
    stale = await plan(owner, venue)
    assert stale["state"] == "stale"
    assert stale["can_build"] is True


async def test_a_room_known_only_from_public_lineups_gets_one_list_with_no_time_of_day(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    plant_lineup(admin, world, owner, venue)
    await build_acts(world, admin, owner, venue)
    doc = await plan(owner, venue)
    assert doc["state"] == "ready"
    assert doc["kind"] == "undated"
    assert doc["basis"]["provisional"] is True
    assert "cells" not in doc["plan"]
    assert doc["plan"]["acts"]
    assert "not when guests come" in doc["reason"]


async def test_another_account_cannot_read_a_venues_plan(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    other = await sign_up(world)
    res = await other.client.get(
        f"/v1/tenants/{other.tenant_id}/businesses/{venue.business_id}/sound"
    )
    assert res.status_code == 404
    anonymous = await world.client().get(
        f"/v1/tenants/{owner.tenant_id}/businesses/{venue.business_id}/sound"
    )
    assert anonymous.status_code == 401
