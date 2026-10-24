"""Grow through the backend: ghost customers from Qloo's neighbouring acts, and the places Qloo lists around the venue, with the
checks that decide what each list may claim. Qloo is scripted; every name is invented."""

from __future__ import annotations

import json
import uuid
from typing import Any

import psycopg
from fakeqloo import place
from harness import World, make_venue, sign_up
from nigiwai_api import worker
from test_sound import timed_crowd
from test_soundcheck import add_artist, base, plant_lineup

GENRE = "urn:tag:genre:qloo"
GHOSTS = [
    (f"{GENRE}:shoegaze", "Shoegaze"),
    (f"{GENRE}:dream_pop", "Dream pop"),
    (f"{GENRE}:doom", "Doom"),
]
RADIUS = 800


def add_neighbours(admin: psycopg.Connection[Any], world: World) -> None:
    """Nine acts Qloo lists next to each planted group, carrying two of that group's own genres and the group's ghost genre."""
    for g in range(3):
        for i in range(9):
            add_artist(
                admin,
                world,
                f"Neighbour {g}-{i}",
                g,
                tags=[
                    (f"{GENRE}:t{g}_{i % 14}", f"t{g}_{i % 14}"),
                    (f"{GENRE}:t{g}_{(i + 5) % 14}", f"t{g}_{(i + 5) % 14}"),
                    GHOSTS[g],
                ],
                popularity=0.3,
            )


def script_places(world: World, mode: str) -> dict[str, int]:
    """How Qloo answers place questions. Thirty bars inside the radius and thirty further out, group 0 liking every third from 0,
    group 1 from 1, group 2 from 2.

    - "near": the same answer whatever the signal (Qloo ignoring the crowd's taste)
    - "shared": with any signal, one answer that differs from the plain list but is the same for every group
    - "apart": each group's signal puts that group's own bars first
    - "gap": like "apart", except group 2's first ten are five of group 0's and five of group 1's
    - "flat": every seeded answer scores every place the same, which Qloo's guard flags as an ineffective signal
    Returns bar index by entity id, so a test can say which bar it found."""
    # scores differ a little from place to place, as Qloo's do; identical scores would be flagged as an ineffective signal
    inside = [place(f"Bar {k}", distance=60 + 24 * k, affinity=0.9 - 0.002 * k) for k in range(30)]
    far = [
        place(f"Far bar {k}", distance=1200 + 100 * k, affinity=0.9 - 0.002 * k) for k in range(30)
    ]
    index = {p["entity_id"]: k for k, p in enumerate(inside)}
    index.update({p["entity_id"]: 100 + k for k, p in enumerate(far)})
    home = {p["entity_id"]: k % 3 for k, p in enumerate(inside)}
    home.update({p["entity_id"]: k % 3 for k, p in enumerate(far)})

    def group_of_signal(seeds: list[str]) -> int | None:
        votes: dict[int, int] = {}
        for s in seeds:
            g = world.qloo.group_of.get(s)
            if g is not None:
                votes[g] = votes.get(g, 0) + 1
        if not votes:
            return None
        top = sorted(votes.items(), key=lambda kv: (-kv[1], kv[0]))
        return top[0][0] if len(top) == 1 or top[0][1] > top[1][1] else None

    def answer(seeds: list[str], radius: int, take: int) -> list[dict[str, Any]]:
        pool = [p for p in [*inside, *far] if p["query"]["distance"] <= radius]
        if not seeds:
            rows = [{**p, "query": {"distance": p["query"]["distance"]}} for p in pool]
            return rows[:take]
        if mode == "near":
            return pool[:take]
        if mode == "flat":
            return [{**p, "query": {**p["query"], "affinity": 0.5}} for p in reversed(pool)][:take]
        g = group_of_signal(seeds)
        if mode == "shared" or g is None:
            return list(reversed(pool))[:take]
        own = [p for p in pool if home[p["entity_id"]] == g]
        rest = [p for p in pool if home[p["entity_id"]] != g]
        if mode == "gap" and g == 2:
            first = [p for p in pool if home[p["entity_id"]] == 0][:5]
            second = [p for p in pool if home[p["entity_id"]] == 1][:5]
            used = {p["entity_id"] for p in [*first, *second]}
            return [*first, *second, *(p for p in pool if p["entity_id"] not in used)][:take]
        return [*own, *rest][:take]

    world.qloo.place_answer = answer
    return index


async def run(
    world: World, owner: Any, venue: Any, admin: psycopg.Connection[Any]
) -> dict[str, Any]:
    queued = await owner.post(f"{base(owner, venue)}/grow")
    assert queued.status_code == 202, queued.text
    admin.execute("UPDATE job SET run_after = now() WHERE state = 'pending'")
    state = world.app.state.nigiwai
    while await worker.work_once(state.engine, state.guard):
        pass
    got = await owner.get(f"{base(owner, venue)}/grow")
    assert got.status_code == 200, got.text
    out: dict[str, Any] = got.json()
    return out


async def ready(
    world: World, admin: psycopg.Connection[Any], mode: str = "near"
) -> tuple[Any, Any]:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    await timed_crowd(world, admin, owner, venue)
    add_neighbours(admin, world)
    script_places(world, mode)
    return owner, venue


# ------------------------------------------------------------------------------------------- the page and its states
async def test_there_is_nothing_to_read_until_a_crowd_exists(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    doc = (await owner.get(f"{base(owner, venue)}/grow")).json()
    assert doc["state"] == "no_crowd"
    assert doc["can_build"] is False
    assert "60 guests" in doc["reason"]
    assert doc["run"] is None
    refused = await owner.post(f"{base(owner, venue)}/grow")
    assert refused.status_code == 422
    assert "60 guests" in refused.json()["detail"]
    assert world.qloo.calls == []
    assert (await owner.get(f"{base(owner, venue)}/grow/calls")).status_code == 404


async def test_opening_the_page_before_a_run_costs_nothing(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner, venue = await ready(world, admin)
    before = len(world.qloo.calls)
    doc = (await owner.get(f"{base(owner, venue)}/grow")).json()
    assert doc["state"] == "not_run"
    assert doc["can_build"] is True
    assert doc["basis_now"]["kind"] == "guests"
    assert len(world.qloo.calls) == before


# ---------------------------------------------------------------------------------------------- ghost customers
async def test_each_group_gets_the_genre_its_neighbours_share_and_the_crowd_lacks(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner, venue = await ready(world, admin)
    doc = await run(world, owner, venue, admin)
    assert doc["state"] == "ready"
    assert doc["reason"] == ""
    run_doc = doc["run"]
    assert run_doc["basis"]["kind"] == "guests"
    assert run_doc["basis"]["provisional"] is True
    ghosts = run_doc["ghosts"]
    assert ghosts["status"] == "ok"
    assert ghosts["unit"] == "guests"
    assert ghosts["act_similarity"] is not None and ghosts["act_similarity"] <= 0.5
    # each group is shown the one genre its own neighbours carry, with the acts that carry it
    by_tag = {g["tag"]: g for g in ghosts["items"]}
    assert set(by_tag) == {"Shoegaze", "Dream pop", "Doom"}
    planted = {"Shoegaze": 0, "Dream pop": 1, "Doom": 2}
    for tag, ghost in by_tag.items():
        assert ghost["acts"], tag
        assert all(a["name"].startswith(f"Neighbour {planted[tag]}-") for a in ghost["acts"])
        assert len(ghost["acts"]) <= 3
        assert (
            ghost["carrying"] is None
        )  # nobody in the crowd carries it, and a count under 10 is never shown
        assert ghost["neighbours_with_tag"] == 9
        assert ghost["bridges"]
        assert tag not in ghost["bridges"]
    assert {g["group_index"] for g in ghosts["items"]} == {g["index"] for g in run_doc["groups"]}


async def test_the_stored_record_holds_our_own_derived_facts_and_no_raw_qloo_answer(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner, venue = await ready(world, admin, "apart")
    doc = await run(world, owner, venue, admin)
    text = json.dumps(doc["run"])
    for raw in ("affinity", "popularity", '"tags"', "query", "properties", "is_closed"):
        assert raw not in text, raw
    row = admin.execute("SELECT status, basis_kind, basis_ref FROM grow_run").fetchone()
    assert row is not None and row[0] == "ready" and row[1] == "guests"


async def test_opening_a_finished_run_makes_no_qloo_call(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner, venue = await ready(world, admin)
    await run(world, owner, venue, admin)
    before = len(world.qloo.calls)
    again = (await owner.get(f"{base(owner, venue)}/grow")).json()
    calls = (await owner.get(f"{base(owner, venue)}/grow/calls")).json()
    assert again["state"] == "ready"
    assert len(world.qloo.calls) == before
    assert {c["endpoint"] for c in calls} == {"/v2/insights", "/entities"}
    # eligibility is already known for the planted acts, so there are no probes: 3 neighbour lists, 7 place lists, 1+ closure
    assert {c["purpose"] for c in calls} == {"board"}
    assert len(calls) >= 11
    assert all(c["status"] == "ok" for c in calls), [(c["endpoint"], c["status"]) for c in calls]


async def test_qloo_giving_every_group_the_same_acts_shows_no_ghosts(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    await timed_crowd(world, admin, owner, venue)
    add_neighbours(admin, world)
    # one group for every signal: Qloo cannot tell the groups apart
    for e in list(world.qloo.group_of):
        world.qloo.group_of[e] = 0
    script_places(world, "near")
    doc = await run(world, owner, venue, admin)
    ghosts = doc["run"]["ghosts"]
    assert ghosts["status"] == "not_group_specific"
    assert ghosts["items"] == []
    assert "mostly the same neighbouring acts" in ghosts["reason"]


# -------------------------------------------------------------------------------------------------------- places
async def test_places_that_ignore_the_crowds_taste_are_called_near_you(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner, venue = await ready(world, admin, "near")
    run_doc = (await run(world, owner, venue, admin))["run"]
    near = run_doc["places"]["nearby"]
    assert near["status"] == "ok"
    assert near["mode"] == "near"
    assert near["seed_effect"] == 0.0
    assert near["told_apart"] is False
    assert near["by_group"] is None
    assert near["gaps"] == []
    assert "places near you, not places matched to your crowd" in near["note"]
    assert len(near["items"]) == 5
    assert all(p["distance_m"] <= RADIUS for p in near["items"])
    far = run_doc["places"]["elsewhere"]
    assert far["mode"] == "near"
    assert "not lookalikes" in far["note"]
    assert all(p["distance_m"] > RADIUS for p in far["items"])
    assert run_doc["places"]["radius_m"] == RADIUS
    assert run_doc["places"]["wide_radius_m"] == 4000
    assert run_doc["places"]["category"] == "bar"


async def test_places_matched_to_the_crowd_are_listed_for_the_crowd_when_groups_were_not_told_apart(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner, venue = await ready(world, admin, "shared")
    places = (await run(world, owner, venue, admin))["run"]["places"]
    near = places["nearby"]
    assert near["mode"] == "taste"
    assert near["seed_effect"] == 1.0
    assert near["similarity"] == 1.0
    assert near["told_apart"] is False
    assert near["by_group"] is None
    assert near["gaps"] == []
    assert "mostly the same places" in near["note"]
    assert places["elsewhere"]["mode"] == "taste"
    assert places["elsewhere"]["by_group"] is None
    assert "ties to your crowd's taste" in places["elsewhere"]["note"]


async def test_a_place_list_with_no_spread_in_its_scores_is_not_taken_as_matched(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner, venue = await ready(world, admin, "flat")
    places = (await run(world, owner, venue, admin))["run"]["places"]
    near = places["nearby"]
    # Qloo's guard flagged the seeded lists as ineffective, so the crowd list falls back to the plain one
    assert near["mode"] == "near"
    assert near["seed_effect"] == 0.0
    assert near["told_apart"] is False
    assert places["elsewhere"]["mode"] == "near"


async def test_groups_told_apart_get_their_own_places_and_the_lookalikes_follow(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner, venue = await ready(world, admin, "apart")
    run_doc = (await run(world, owner, venue, admin))["run"]
    near = run_doc["places"]["nearby"]
    assert near["mode"] == "taste"
    assert near["told_apart"] is True
    assert near["similarity"] == 0.0
    assert len(near["by_group"]) == 3
    assert all(g["own"] for g in near["by_group"])
    assert near["gaps"] == []
    firsts = [g["items"][0]["name"] for g in near["by_group"]]
    assert len(set(firsts)) == 3
    far = run_doc["places"]["elsewhere"]
    assert far["told_apart"] is True
    assert len(far["by_group"]) == 3
    assert all(p["distance_m"] > RADIUS for g in far["by_group"] for p in g["items"])


async def test_a_group_with_no_place_of_its_own_is_a_gap_candidate(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner, venue = await ready(world, admin, "gap")
    near = (await run(world, owner, venue, admin))["run"]["places"]["nearby"]
    assert near["told_apart"] is True
    assert len(near["gaps"]) == 1
    gap_label = near["gaps"][0]["group"]
    row = next(g for g in near["by_group"] if g["group"] == gap_label)
    assert row["own"] is False
    assert len(row["items"]) == 5


async def test_closed_places_and_the_venue_itself_are_left_out(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner, venue = await ready(world, admin, "near")
    answer = world.qloo.place_answer
    assert answer is not None
    shut = place("Shut Bar", distance=70, affinity=0.9, closed=True)
    itself = place("The Lantern", distance=300, affinity=0.9)
    next_door = place("Next Door", distance=20, affinity=0.9)  # at the venue's own point

    def with_extras(seeds: list[str], radius: int, take: int) -> list[dict[str, Any]]:
        return [shut, itself, next_door, *answer(seeds, radius, take)]

    world.qloo.place_answer = with_extras
    run_doc = (await run(world, owner, venue, admin))["run"]
    names = [
        p["name"]
        for section in ("nearby", "elsewhere")
        for p in run_doc["places"][section]["items"]
    ]
    assert "Shut Bar" not in names
    assert "The Lantern" not in names
    assert "Next Door" not in names
    assert (
        run_doc["places"]["dropped_closed"] == 1
    )  # one place, counted once however many lists it was in
    assert run_doc["places"]["closure_unanswered"] is False


async def test_a_business_kind_with_no_place_category_gets_ghosts_but_no_places(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner, venue = await ready(world, admin)
    admin.execute("UPDATE business SET type = 'retail'")
    run_doc = (await run(world, owner, venue, admin))["run"]
    assert run_doc["ghosts"]["status"] == "ok"
    assert run_doc["places"]["status"] == "unavailable"
    assert "bar, live music venue, cafe, restaurant or hotel bar" in run_doc["places"]["reason"]
    assert not [c for c in world.qloo.calls if dict(c[1]).get("filter.type") == "urn:entity:place"]


# -------------------------------------------------------------------------------------------- public lineups
async def test_a_room_known_only_from_public_lineups_is_read_from_its_acts(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    plant_lineup(admin, world, owner, venue)
    add_neighbours(admin, world)
    script_places(world, "near")
    doc = await run(world, owner, venue, admin)
    assert doc["state"] == "ready"
    run_doc = doc["run"]
    assert run_doc["basis"]["kind"] == "lineup"
    assert run_doc["basis"]["provisional"] is True
    assert run_doc["ghosts"]["unit"] == "acts"
    assert run_doc["places"]["status"] == "ok"


# ------------------------------------------------------------------------------------------ stale and failed runs
async def test_a_run_made_for_older_groups_says_so(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner, venue = await ready(world, admin)
    await run(world, owner, venue, admin)
    admin.execute("UPDATE grow_run SET basis_ref = 'an older version'")
    doc = (await owner.get(f"{base(owner, venue)}/grow")).json()
    assert doc["state"] == "stale"
    assert doc["run"] is not None
    assert "older version of your groups" in doc["reason"]
    assert doc["can_build"] is True


async def test_qloo_being_down_fails_the_run_with_a_plain_reason_and_a_later_run_recovers(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner, venue = await ready(world, admin)
    world.qloo.down = True
    failed = await run(world, owner, venue, admin)
    assert failed["state"] == "failed"
    assert failed["run"] is None
    assert "no neighbouring acts" in failed["reason"]
    world.qloo.down = False
    admin.execute(
        "DELETE FROM qloo_response"
    )  # the failed answers must not be served from the cache
    again = await run(world, owner, venue, admin)
    assert again["state"] == "ready"


async def test_places_not_answering_leaves_the_ghosts_standing(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner, venue = await ready(world, admin)
    world.qloo.place_answer = lambda seeds, radius, take: []
    run_doc = (await run(world, owner, venue, admin))["run"]
    assert run_doc["ghosts"]["status"] == "ok"
    assert run_doc["places"]["nearby"]["status"] == "empty"
    assert "no open places" in run_doc["places"]["nearby"]["note"]
    assert run_doc["places"]["elsewhere"]["status"] == "empty"


# ------------------------------------------------------------------------------------- who may do what, and limits
async def test_only_someone_who_can_change_the_account_may_ask_for_a_run(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner, venue = await ready(world, admin)
    root = f"/v1/tenants/{owner.tenant_id}/businesses/{venue.business_id}/grow"
    other = await sign_up(world)
    assert (
        await other.client.get(f"/v1/tenants/{other.tenant_id}/businesses/{venue.business_id}/grow")
    ).status_code == 404
    assert (await world.client().get(root)).status_code == 401
    assert (await world.client().post(root)).status_code in (401, 403)

    viewer = await sign_up(world)
    admin.execute(
        "INSERT INTO membership (tenant_id, user_id, role) VALUES (%s, %s, 'viewer')",
        (owner.tenant_id, viewer.me["user_id"]),
    )
    assert (await viewer.client.get(root)).status_code == 200
    assert (await viewer.client.post(root, headers=viewer.headers)).status_code == 403
    assert admin.execute("SELECT count(*) FROM job WHERE kind = 'grow'").fetchone() == (0,)


async def test_asking_twice_queues_one_job_and_a_seventh_request_is_refused(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner, venue = await ready(world, admin)
    url = f"{base(owner, venue)}/grow"
    for _ in range(6):
        assert (await owner.post(url)).status_code == 202
    assert admin.execute(
        "SELECT count(*) FROM job WHERE kind = 'grow' AND state = 'pending'"
    ).fetchone() == (1,)
    assert (await owner.post(url)).status_code == 429
    row = admin.execute("SELECT status FROM grow_run").fetchone()
    assert row == ("queued",)


async def test_a_server_without_qloo_says_so(world: World, admin: psycopg.Connection[Any]) -> None:
    owner, venue = await ready(world, admin)
    world.app.state.nigiwai.guard = None
    res = await owner.post(f"{base(owner, venue)}/grow")
    assert res.status_code == 503
    assert "Qloo is not configured" in res.json()["detail"]


async def test_a_worker_without_qloo_stores_a_failure_not_a_crash(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner, venue = await ready(world, admin)
    assert (await owner.post(f"{base(owner, venue)}/grow")).status_code == 202
    admin.execute("UPDATE job SET run_after = now() WHERE state = 'pending'")
    state = world.app.state.nigiwai
    while await worker.work_once(state.engine, None):
        pass
    doc = (await owner.get(f"{base(owner, venue)}/grow")).json()
    assert doc["state"] == "failed"
    assert "not configured" in doc["reason"]
    assert uuid.UUID(venue.business_id)
