"""The Today board: opening hours and scans in, a few honest actions out, decisions kept per week. Qloo is scripted and
every name is invented."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import psycopg
from harness import World, make_venue, sign_up
from nigiwai_api.services import today as service
from test_brief import ready_brief
from test_soundcheck import base, plant_lineup

DAY = {"open": "12:00", "close": "23:00"}
WEEK = [DAY] * 7


def open_all_week(admin: psycopg.Connection[Any]) -> None:
    admin.execute("UPDATE location SET hours = %s::jsonb", (json.dumps(WEEK),))


def set_rhythm(admin: psycopg.Connection[Any]) -> None:
    """Give the planted responses an exact week: one scan in every open hour, none on Wednesday 14:00 to 17:00, and a
    Friday evening and a Saturday 19:00 that are busy. 90 scans in all, the number `crowd` plants."""
    cells: list[tuple[int, int]] = []
    for day in range(7):
        for hour in range(12, 23):
            n = 1
            if day == 2 and 14 <= hour <= 16:
                n = 0
            if day == 4 and 18 <= hour <= 20:
                n += 4
            if day == 5 and hour == 19:
                n += 4
            cells += [(day, hour)] * n
    ids = [r[0] for r in admin.execute("SELECT id FROM response ORDER BY id").fetchall()]
    assert len(ids) == len(cells) == 90, (len(ids), len(cells))
    for rid, (day, hour) in zip(ids, cells, strict=True):
        admin.execute(
            "UPDATE response SET local_weekday = %s, local_hour = %s WHERE id = %s",
            (day, hour, rid),
        )


async def board(owner: Any, venue: Any) -> dict[str, Any]:
    res = await owner.get(f"{base(owner, venue)}/today")
    assert res.status_code == 200, res.text
    out: dict[str, Any] = res.json()
    return out


async def full_board(
    world: World, admin: psycopg.Connection[Any], owner: Any, venue: Any
) -> dict[str, Any]:
    await ready_brief(world, admin, owner, venue)
    open_all_week(admin)
    set_rhythm(admin)
    return await board(owner, venue)


async def test_a_venue_with_nothing_yet_is_day_zero_and_says_what_would_unlock_the_first_picture(
    world: World,
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    doc = await board(owner, venue)
    assert doc["state"] == "day0" and doc["actions"] == [] and doc["hold"] is None
    assert doc["status"]["scans"] == 0 and doc["status"]["since"] is None
    assert doc["status"]["unlock"] == {
        "title": "Your first quiet-hours picture at 10 scans",
        "v": 0,
        "max": 10,
        "text": "10 more scans. Until then Nigiwai shows nothing here rather than guess.",
    }
    assert (
        doc["hours"]["set"] is False and doc["hours"]["quiet"] == [] and doc["hours"]["cells"] == []
    )


async def test_a_real_crowd_with_hours_gets_its_quietest_stretch_and_two_actions_with_labelled_evidence(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    calls_before = len(world.qloo.calls)
    doc = await full_board(world, admin, owner, venue)
    calls_made_by_the_board = len(world.qloo.calls)
    assert (
        doc["state"] == "ready"
        and doc["status"]["scans"] == 90
        and doc["status"]["basis"] == "guests"
    )

    hours = doc["hours"]
    assert hours["set"] and (hours["from"], hours["to"]) == (12, 23) and len(hours["cells"]) == 7
    assert (
        hours["cells"][2][14 - 12] == 0 and hours["cells"][4][18 - 12] == 5
    )  # Wednesday empty, Friday busy
    assert [(q["weekday"], q["start"], q["end"], q["scans"]) for q in hours["quiet"]] == [
        (2, 14, 17, 0)
    ]
    assert hours["quiet"][0]["text"] == "Wednesday 14:00 to 17:00"
    assert hours["early"] is False and hours["picture"] is True

    fill, book = doc["actions"]
    assert fill["kind"] == "Fill an empty chair" and "Wednesday 14:00 to 17:00" in fill["title"]
    assert book["kind"] == "Book an act" and "Friday evening" in book["title"]
    assert fill["act"]["entity_id"] != book["act"]["entity_id"]  # two different acts
    for action in doc["actions"]:
        assert action["key"] and action["decision"] is None and action["logged"] is False
        assert {e["label"] for e in action["evidence"]} <= {"measured", "modelled", "observed"}
        assert action["evidence"][0]["label"] in ("measured",) or action is book
        assert action["fit"] is not None and 0 <= action["fit"]["score"] <= 100
        assert action["fit"]["groups"] and action["fit"]["soundcheck_id"]
    assert (
        fill["evidence"][0]["label"] == "measured"
        and "0 of 90 scans" in fill["evidence"][0]["text"]
    )
    assert "30 of 90" not in json.dumps(
        book
    )  # the busiest stretch is Friday 18:00 to 21:00 with 15 scans
    assert "15 of 90 scans came on Friday 18:00 to 21:00" in book["evidence"][0]["text"]

    # the board is read from what is stored: opening it again, and again, makes no Qloo call
    for _ in range(3):
        await board(owner, venue)
    assert len(world.qloo.calls) == calls_made_by_the_board > calls_before


async def test_with_no_opening_hours_nothing_is_called_quiet_and_the_board_asks_for_them(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    await ready_brief(world, admin, owner, venue)
    set_rhythm(admin)  # plenty of scans, but the venue has not said when it is open
    doc = await board(owner, venue)
    assert (
        doc["hours"]["set"] is False
        and doc["hours"]["quiet"] == []
        and doc["hours"]["picture"] is False
    )
    assert not any(a["kind"] == "Fill an empty chair" for a in doc["actions"])
    assert doc["status"]["scans"] == 90


async def test_a_venue_with_only_public_lineups_gets_a_provisional_book_action_for_its_busiest_lineup_day(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    plant_lineup(admin, world, owner, venue)
    from nigiwai_api import worker
    from test_soundcheck import add_artist

    for g in range(3):
        for i in range(9):
            add_artist(admin, world, f"Neighbour {g}-{i}", g, popularity=0.05 + 0.1 * i)
    await owner.post(f"{base(owner, venue)}/suggestions")
    admin.execute("UPDATE job SET run_after = now() WHERE state = 'pending'")
    state = world.app.state.nigiwai
    while await worker.work_once(state.engine, state.guard):
        pass
    doc = await board(owner, venue)
    assert (
        doc["state"] == "ready"
        and doc["status"]["scans"] == 0
        and doc["status"]["basis"] == "lineup"
    )
    (book,) = doc["actions"]
    assert "Saturday evening" in book["title"]  # plant_lineup's lineups skew to Saturday
    assert "past public lineups" in book["why"]
    assert any("public lineups" in (e["note"] or "") for e in book["evidence"])
    assert all(
        e["label"] != "measured" for e in book["evidence"]
    )  # nothing here was counted from guests


async def test_accept_dismiss_and_undo_are_kept_for_the_week_and_only_for_actions_on_the_board(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    doc = await full_board(world, admin, owner, venue)
    fill, book = doc["actions"]
    path = f"{base(owner, venue)}/today/actions"

    res = await owner.client.put(
        f"/v1/tenants/{owner.tenant_id}{path}/{fill['key']}",
        json={"state": "accepted"},
        headers=owner.headers,
    )
    assert res.status_code == 200 and res.json() == {"key": fill["key"], "state": "accepted"}
    res = await owner.client.put(
        f"/v1/tenants/{owner.tenant_id}{path}/{book['key']}",
        json={"state": "dismissed"},
        headers=owner.headers,
    )
    assert res.status_code == 200
    again = await board(owner, venue)
    assert [a["decision"] for a in again["actions"]] == ["accepted", "dismissed"]

    undo = await owner.client.put(
        f"/v1/tenants/{owner.tenant_id}{path}/{book['key']}",
        json={"state": None},
        headers=owner.headers,
    )
    assert undo.status_code == 200
    assert [a["decision"] for a in (await board(owner, venue))["actions"]] == ["accepted", None]
    assert admin.execute("SELECT count(*) FROM board_decision").fetchone() == (1,)

    # an action that is not on the board cannot be decided on, whatever its shape
    for key in ("fill:2:14:" + str(uuid.uuid4()), "book:9:9:" + str(uuid.uuid4())):
        res = await owner.client.put(
            f"/v1/tenants/{owner.tenant_id}{path}/{key}",
            json={"state": "accepted"},
            headers=owner.headers,
        )
        assert res.status_code == 404, key
    for key in ("x", "FILL:1", "fill:../../x", "a" * 121):
        res = await owner.client.put(
            f"/v1/tenants/{owner.tenant_id}{path}/{key}",
            json={"state": "accepted"},
            headers=owner.headers,
        )
        assert res.status_code in (404, 422), key
    for body in ({"state": "maybe"}, {}, {"state": "accepted", "extra": 1}, "accepted"):
        res = await owner.client.put(
            f"/v1/tenants/{owner.tenant_id}{path}/{fill['key']}", json=body, headers=owner.headers
        )
        assert res.status_code == 422, body
    assert admin.execute("SELECT count(*) FROM board_decision").fetchone() == (1,)


async def test_an_accepted_action_is_logged_as_one_move_and_not_before(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    fill, _ = (await full_board(world, admin, owner, venue))["actions"]
    root = f"/v1/tenants/{owner.tenant_id}{base(owner, venue)}/today/actions/{fill['key']}"

    early = await owner.client.post(f"{root}/log", headers=owner.headers)
    assert early.status_code == 409 and "Accept the action first" in early.json()["detail"]
    await owner.client.put(root, json={"state": "accepted"}, headers=owner.headers)
    first = await owner.client.post(f"{root}/log", headers=owner.headers)
    assert first.status_code == 200 and first.json() == {
        "key": fill["key"],
        "logged": True,
        "new": True,
    }
    second = await owner.client.post(f"{root}/log", headers=owner.headers)
    assert second.json()["new"] is False  # logging twice makes no second move
    row = admin.execute("SELECT kind, title, source, source_key FROM move").fetchall()
    assert row == [("act", fill["title"], "today", fill["key"])]
    # the move carries the slot the action was about: the quiet Wednesday afternoon
    assert admin.execute("SELECT weekdays, hour_from, hour_to FROM move").fetchall() == [
        ([2], 14, 17)
    ]
    assert (await board(owner, venue))["actions"][0]["logged"] is True


async def test_a_decision_belongs_to_its_week(world: World, admin: psycopg.Connection[Any]) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    doc = await full_board(world, admin, owner, venue)
    fill = doc["actions"][0]
    await owner.client.put(
        f"/v1/tenants/{owner.tenant_id}{base(owner, venue)}/today/actions/{fill['key']}",
        json={"state": "accepted"},
        headers=owner.headers,
    )
    st = world.app.state.nigiwai
    here = await service.build(st.engine, uuid.UUID(owner.tenant_id), uuid.UUID(venue.business_id))
    later = await service.build(
        st.engine,
        uuid.UUID(owner.tenant_id),
        uuid.UUID(venue.business_id),
        now=datetime(2027, 3, 3, 12, tzinfo=UTC),
    )
    assert here is not None and later is not None
    assert here["actions"][0]["decision"] == "accepted" and later["week"] != here["week"]
    assert all(a["decision"] is None for a in later["actions"])  # a new week starts undecided


def test_weeks_follow_the_iso_calendar_and_dayparts_the_clock() -> None:
    from datetime import date

    assert service.week_of(date(2026, 10, 24)) == "2026-W43"
    assert (
        service.week_of(date(2027, 1, 1)) == "2026-W53"
    )  # the ISO year differs from the calendar year
    assert [service.daypart(h) for h in (3, 9, 14, 19, 23)] == [
        "late night",
        "morning",
        "afternoon",
        "evening",
        "late night",
    ]
    assert service.unlock_for(5)["max"] == 10 and service.unlock_for(25)["max"] == 60
    assert service.unlock_for(60)["max"] == 200 and service.unlock_for(200) is None
    assert "1 more scan." in service.unlock_for(9)["text"]  # type: ignore[index]


async def test_the_board_is_private_to_its_account_and_its_writes_need_an_account(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    other = await sign_up(world)
    venue = await make_venue(owner)
    doc = await full_board(world, admin, owner, venue)
    key = doc["actions"][0]["key"]
    theirs = f"/v1/tenants/{owner.tenant_id}{base(owner, venue)}/today"
    assert (await other.client.get(theirs)).status_code == 404
    assert (
        await other.client.put(
            f"{theirs}/actions/{key}", json={"state": "accepted"}, headers=other.headers
        )
    ).status_code == 404
    assert (
        await other.client.post(f"{theirs}/actions/{key}/log", headers=other.headers)
    ).status_code == 404
    anon = world.client()
    assert (await anon.get(theirs)).status_code == 401
    assert (
        await anon.put(f"{theirs}/actions/{key}", json={"state": "accepted"})
    ).status_code == 401
    # a business of another account is not found even with the right tenant in the address
    mine = await sign_up(world)
    assert (await mine.get(f"{base(owner, venue)}/today")).status_code == 404
    assert (await mine.get(f"/businesses/{uuid.uuid4()}/today")).status_code == 404
    assert admin.execute("SELECT count(*) FROM board_decision").fetchone() == (0,)


async def test_a_cafe_is_offered_an_idea_from_its_own_scans_and_picks_and_no_act_to_book(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    await ready_brief(world, admin, owner, venue)
    admin.execute("UPDATE business SET type = 'cafe'")
    open_all_week(admin)
    set_rhythm(admin)
    doc = await board(owner, venue)
    assert doc["venue"]["music"] is False
    kinds = [a["kind"] for a in doc["actions"]]
    assert kinds[0] == "Aim something at a quiet stretch"
    assert "Book an act" not in kinds  # a cafe is not asked to book a band
    idea = doc["actions"][0]
    assert idea["title"] == "Aim something at Wednesday afternoon"
    assert idea["act"] is None and idea["fit"] is None  # no act, so no fit to show
    assert idea["slot"] == {"weekdays": [2], "from": 14, "to": 17}
    assert "Wednesday 14:00 to 17:00 is your quietest stretch" in idea["why"]
    assert "% of the guests who answered" in idea["why"] and "picks " in idea["why"]
    # only what the venue itself measured, and one line saying what is only a hypothesis
    assert [e["label"] for e in idea["evidence"]] == ["measured", "measured", "modelled"]
    assert "0 of 90 scans" in idea["evidence"][0]["text"]
    assert "observed" not in json.dumps(idea["evidence"])  # nothing here is a claim from Qloo
    assert idea["prov"][-1] == "Your guests' own picks"
    # it can be accepted and logged as a move for its slot, and is not a source for drafts about an act
    root = f"/v1/tenants/{owner.tenant_id}{base(owner, venue)}/today/actions/{idea['key']}"
    assert (
        await owner.client.put(root, json={"state": "accepted"}, headers=owner.headers)
    ).status_code == 200
    assert (await owner.client.post(f"{root}/log", headers=owner.headers)).json()["new"] is True
    assert admin.execute("SELECT weekdays, hour_from, hour_to FROM move").fetchall() == [
        ([2], 14, 17)
    ]
    drafts = (await owner.get(f"{base(owner, venue)}/drafts")).json()
    assert all(a["key"] != idea["key"] for a in drafts["sources"]["actions"])


async def test_without_groups_there_is_no_idea_and_a_music_room_with_two_act_actions_gets_no_third(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    doc = await full_board(world, admin, owner, venue)
    assert [a["kind"] for a in doc["actions"]] == ["Fill an empty chair", "Book an act"]
    # a venue with scans but no fitted groups yet has nothing to build an idea from
    other = await sign_up(world)
    bare = await make_venue(other)
    admin.execute("UPDATE business SET type = 'cafe' WHERE id = %s", (bare.business_id,))
    admin.execute(
        "UPDATE location SET hours = %s::jsonb WHERE business_id = %s",
        (json.dumps(WEEK), bare.business_id),
    )
    assert (await board(other, bare))["actions"] == []
