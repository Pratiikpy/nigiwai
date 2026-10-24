"""Opening hours: seven days, Monday first, stored with the location, validated at the door."""

from __future__ import annotations

from typing import Any

import psycopg
from harness import World, make_venue, sign_up

OPEN = {"open": "12:00", "close": "23:00"}
LATE = {"open": "18:00", "close": "02:00"}  # closes after midnight


def room(**extra: Any) -> dict[str, Any]:
    return {"name": "Main room", "lat": 51.5, "lon": -0.12, "timezone": "Europe/London", **extra}


async def test_a_week_of_hours_is_kept_and_read_back_and_an_empty_week_means_unset(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    path = f"/locations/{venue.location_id}"
    week = [OPEN, OPEN, OPEN, OPEN, OPEN, LATE, None]  # closed on Sunday

    res = await owner.put(path, json=room(hours=week))
    assert res.status_code == 200, res.text
    assert res.json()["hours"] == week
    listed = (await owner.get(f"/businesses/{venue.business_id}/locations")).json()[0]
    assert listed["hours"] == week and (listed["lat"], listed["lon"]) == (51.5, -0.12)
    assert admin.execute("SELECT hours FROM location").fetchone() == (week,)

    # saying nothing again clears it: the venue goes back to "not said", never to "closed all week"
    res = await owner.put(path, json=room())
    assert res.status_code == 200 and res.json()["hours"] == []
    assert admin.execute("SELECT hours FROM location").fetchone() == ({},)

    # a new location can be created with hours too
    made = await owner.post(
        f"/businesses/{venue.business_id}/locations", json=room(name="Terrace", hours=week)
    )
    assert made.status_code == 201 and made.json()["hours"] == week


async def test_hours_that_are_not_a_week_of_valid_times_are_refused_and_nothing_changes(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    path = f"/locations/{venue.location_id}"
    assert (await owner.put(path, json=room(hours=[OPEN] * 7))).status_code == 200
    kept = [OPEN] * 7

    def week_with(first: Any) -> list[Any]:
        return [first, *([None] * 6)]

    bad: list[Any] = [
        [OPEN] * 6,  # not seven days
        [OPEN] * 8,
        week_with({"open": "25:00", "close": "23:00"}),
        week_with({"open": "12:60", "close": "23:00"}),
        week_with({"open": "9:00", "close": "17:00"}),  # not zero-padded
        week_with({"open": "12:00", "close": "12:00"}),  # no span at all
        week_with({"open": "12:00"}),
        week_with({"open": "12:00", "close": "23:00", "extra": 1}),
        week_with({"open": 12, "close": 23}),
        week_with("12:00-23:00"),
        "monday",
        {"0": OPEN},
        [None] * 8,
    ]
    for hours in bad:
        res = await owner.put(path, json=room(hours=hours))
        assert res.status_code == 422, (hours, res.status_code)
    assert admin.execute("SELECT hours FROM location").fetchone() == (kept,)


async def test_only_someone_who_can_change_the_venue_can_change_its_hours(world: World) -> None:
    owner = await sign_up(world)
    other = await sign_up(world)
    venue = await make_venue(owner)
    path = f"/v1/tenants/{owner.tenant_id}/locations/{venue.location_id}"
    res = await other.client.put(path, json=room(hours=[OPEN] * 7), headers=other.headers)
    assert res.status_code == 404  # not a member of that account: it does not exist for them
    assert (await world.client().put(path, json=room(hours=[OPEN] * 7))).status_code in (401, 403)
