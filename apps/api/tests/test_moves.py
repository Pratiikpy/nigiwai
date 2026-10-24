"""Moves through the backend: logging a change, the same slot before and after from the stored scans, the mix of groups when
there are groups, and every refusal. Every name is invented."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

import psycopg
from harness import World, make_venue, sign_up
from nigiwai_api.services import tribes as tribe_service
from test_soundcheck import base
from test_tribes import FAST, plant


def friday_ago(weeks: int) -> date:
    today = date.today()
    return today - timedelta(days=(today.weekday() - 4) % 7 + 7 * weeks)


def put_scans(admin: psycopg.Connection[Any], plan: list[tuple[date, int, int]]) -> None:
    """Give the planted responses, in order, exactly these dates and hours: (date, hour, how many)."""
    ids = [r[0] for r in admin.execute("SELECT id FROM response ORDER BY id").fetchall()]
    cells = [(d, hour) for d, hour, n in plan for _ in range(n)]
    assert len(ids) == len(cells), (len(ids), len(cells))
    for rid, (d, hour) in zip(ids, cells, strict=True):
        admin.execute(
            "UPDATE response SET local_date = %s, local_weekday = %s, local_hour = %s WHERE id = %s",
            (d, d.weekday(), hour, rid),
        )


def body(**over: Any) -> dict[str, Any]:
    started = friday_ago(3)
    return {
        "kind": "act",
        "title": "Book The Quiet Engines for Friday evening",
        "started_on": started.isoformat(),
        "weekdays": [4],
        "hour_from": 18,
        "hour_to": 22,
        **over,
    }


async def listing(owner: Any, venue: Any) -> dict[str, Any]:
    res = await owner.get(f"{base(owner, venue)}/moves")
    assert res.status_code == 200, res.text
    out: dict[str, Any] = res.json()
    return out


async def test_a_move_is_logged_listed_changed_and_removed(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    assert (await listing(owner, venue))["moves"] == []
    made = await owner.post(f"{base(owner, venue)}/moves", json=body(note="A trial month."))
    assert made.status_code == 201, made.text
    move_id = made.json()["id"]
    doc = await listing(owner, venue)
    (move,) = doc["moves"]
    assert move["title"] == "Book The Quiet Engines for Friday evening"
    assert move["slot"] == {"weekdays": [4], "from": 18, "to": 22, "text": "Friday 18:00 to 22:00"}
    assert move["source"] == "manual"
    assert move["note"] == "A trial month."
    assert move["result"]["verdict"] == "too_early"  # no scans yet: nothing is guessed
    assert doc["ledger"]["moves"] == 1
    assert doc["weeks"] == 4

    changed = await owner.put(
        f"{base(owner, venue)}/moves/{move_id}",
        json=body(
            title="Residency every Friday",
            kind="event",
            ended_on=(friday_ago(1)).isoformat(),
            weekdays=[4, 5],
        ),
    )
    assert changed.status_code == 204
    (move,) = (await listing(owner, venue))["moves"]
    assert move["title"] == "Residency every Friday"
    assert move["kind"] == "event"
    assert move["ended_on"] == friday_ago(1).isoformat()
    assert move["slot"]["weekdays"] == [4, 5]

    gone = await owner.client.delete(
        owner.url(f"{base(owner, venue)}/moves/{move_id}"), headers=owner.headers
    )
    assert gone.status_code == 204
    assert (await listing(owner, venue))["moves"] == []
    assert (
        await owner.client.delete(
            owner.url(f"{base(owner, venue)}/moves/{move_id}"), headers=owner.headers
        )
    ).status_code == 404
    actions = [
        r[0]
        for r in admin.execute(
            "SELECT action FROM audit_log WHERE action LIKE 'move.%' ORDER BY at"
        ).fetchall()
    ]
    assert actions == ["move.create", "move.update", "move.delete"]


async def test_scans_in_the_slot_before_and_after_are_compared_with_an_interval_and_a_caveat(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    plant(admin, venue, 4 * 2 + 3 * 10 + 6)
    before = [(friday_ago(w), 19, 2) for w in (7, 6, 5, 4)]
    after = [(friday_ago(w), 19, 10) for w in (3, 2, 1)]
    elsewhere = [(friday_ago(2), 12, 6)]  # Friday lunchtime: outside the slot
    put_scans(admin, [*before, *after, *elsewhere])
    await owner.post(f"{base(owner, venue)}/moves", json=body())
    (move,) = (await listing(owner, venue))["moves"]
    r = move["result"]
    assert r["before"]["scans"] == 8
    assert r["after"]["scans"] == 30
    assert r["before"]["days"] == 4
    assert r["after"]["days"] in (3, 4)
    assert r["verdict"] == "more"
    assert r["rate"]["low"] > 1.0
    assert "does not show the change caused it" in r["text"]
    assert r["interval"] == "90%"
    assert r["mix"] is None  # no groups yet, so no mix is shown


async def test_a_small_difference_is_inconclusive_and_the_ledger_says_so(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    plant(admin, venue, 4 + 8)
    put_scans(
        admin,
        [
            *[(friday_ago(w), 19, 1) for w in (7, 6, 5, 4)],
            *[(friday_ago(w), 19, 4) for w in (3, 2)],
        ],
    )
    await owner.post(f"{base(owner, venue)}/moves", json=body())
    await owner.post(
        f"{base(owner, venue)}/moves",
        json=body(kind="menu", title="A new weekend menu", started_on=friday_ago(0).isoformat()),
    )
    doc = await listing(owner, venue)
    by_title = {m["title"]: m for m in doc["moves"]}
    assert (
        by_title["Book The Quiet Engines for Friday evening"]["result"]["verdict"] == "inconclusive"
    )
    assert (
        by_title["A new weekend menu"]["result"]["verdict"] == "too_early"
    )  # only one Friday since it started
    kinds = {k["kind"]: k for k in doc["ledger"]["kinds"]}
    assert kinds["act"] == {
        "kind": "act",
        "moves": 1,
        "more": 0,
        "fewer": 0,
        "inconclusive": 1,
        "waiting": 0,
    }
    assert kinds["menu"]["waiting"] == 1


async def test_the_mix_of_groups_is_shown_for_each_period_only_with_enough_scans(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    ids = plant(admin, venue, 90)
    for i, e in enumerate(ids):
        world.qloo.group_of[e] = i // 24
        world.qloo.names[e] = f"Item {i // 24}-{i % 24}"
    before = [(friday_ago(w), 19, 5) for w in (7, 6, 5, 4)]  # 20 scans
    after = [
        (friday_ago(3), 19, 30),
        (friday_ago(2), 19, 30),
        (friday_ago(0), 19, 10),
    ]  # 70 scans, 60 of them before today
    put_scans(admin, [*before, *after])
    await tribe_service.recompute(
        world.app.state.nigiwai.engine,
        None,
        uuid.UUID(owner.tenant_id),
        uuid.UUID(venue.business_id),
        force=True,
        cfg=FAST,
    )
    await owner.post(f"{base(owner, venue)}/moves", json=body())
    (move,) = (await listing(owner, venue))["moves"]
    mix = move["result"]["mix"]
    assert mix["before"]["shown"] is True
    assert mix["after"]["shown"] is True
    for period in ("before", "after"):
        shares = [g["share"] for g in mix[period]["groups"]]
        assert abs(sum(shares) - 1.0) < 0.01
        assert shares == sorted(shares, reverse=True)
        assert mix[period]["scans"] >= 10
    # a slot with under ten scans in a period shows no mix for it
    await owner.post(
        f"{base(owner, venue)}/moves",
        json=body(title="Tuesday lunch", weekdays=[1], hour_from=12, hour_to=14),
    )
    quiet = next(m for m in (await listing(owner, venue))["moves"] if m["title"] == "Tuesday lunch")
    assert quiet["result"]["mix"]["before"] == {"scans": 0, "shown": False, "groups": []}


async def test_a_move_the_product_cannot_judge_is_refused_with_a_reason(
    world: World,
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    url = f"{base(owner, venue)}/moves"
    cases = [
        (body(started_on=(date.today() - timedelta(days=400)).isoformat()), "more than a year ago"),
        (body(started_on=(date.today() + timedelta(days=90)).isoformat()), "up to 60 days before"),
        (body(ended_on=(friday_ago(5)).isoformat()), "cannot be before the start"),
        (body(weekdays=[4, 4]), "each day of the week once"),
        (body(weekdays=[7]), "each day of the week once"),
        (body(hour_to=None), "both the first and last hour"),
        (body(hour_from=20, hour_to=19), "must end after it starts"),
        (body(title="   "), None),
        (body(kind="gift"), None),
        ({**body(), "extra": 1}, None),
    ]
    for payload, fragment in cases:
        res = await owner.post(url, json=payload)
        assert res.status_code == 422, (payload, res.text)
        if fragment:
            assert fragment in res.json()["detail"], res.json()
    assert (await listing(owner, venue))["moves"] == []


async def test_moves_belong_to_their_account_and_only_writers_change_them(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    made = await owner.post(f"{base(owner, venue)}/moves", json=body())
    move_id = made.json()["id"]
    viewer = await sign_up(world)
    admin.execute(
        "INSERT INTO membership (tenant_id, user_id, role) VALUES (%s, %s, 'viewer')",
        (owner.tenant_id, viewer.me["user_id"]),
    )
    root = f"/v1/tenants/{owner.tenant_id}{base(owner, venue)}/moves"
    assert (await viewer.client.get(root)).status_code == 200
    assert (await viewer.client.post(root, json=body(), headers=viewer.headers)).status_code == 403
    assert (
        await viewer.client.put(f"{root}/{move_id}", json=body(), headers=viewer.headers)
    ).status_code == 403
    assert (
        await viewer.client.delete(f"{root}/{move_id}", headers=viewer.headers)
    ).status_code == 403

    stranger = await sign_up(world)
    theirs = f"/v1/tenants/{stranger.tenant_id}{base(owner, venue)}/moves"
    assert (await stranger.client.get(theirs)).status_code == 404
    assert (
        await stranger.client.put(f"{theirs}/{move_id}", json=body(), headers=stranger.headers)
    ).status_code == 404
    assert (await world.client().get(root)).status_code == 401
    # the move is still there, untouched
    assert (await listing(owner, venue))["moves"][0][
        "title"
    ] == "Book The Quiet Engines for Friday evening"
