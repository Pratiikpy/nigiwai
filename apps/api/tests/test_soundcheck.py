"""Soundcheck through the whole backend: a crowd's groups, the one Qloo call per group, the stored verdict, the
constraints, the failure paths, the suggestions job and the tenant boundary. Qloo is scripted; every name is invented."""

from __future__ import annotations

import json
import uuid
from typing import Any

import psycopg
from fakeqloo import artist
from harness import World, make_venue, sign_up
from nigiwai_api import worker
from nigiwai_api.services import soundcheck as sc
from nigiwai_api.services import tribes as tribe_service
from test_tribes import FAST, plant

ARTIST = "urn:entity:artist"


def add_artist(
    admin: psycopg.Connection[Any],
    world: World,
    name: str,
    group: int,
    *,
    tags: list[tuple[str, str]] | None = None,
    popularity: float = 0.2,
) -> str:
    """An act Qloo knows: a stored entity (so it can be checked) that the scripted Qloo scores as part of `group`."""
    entity_id = str(
        uuid.uuid5(uuid.NAMESPACE_URL, f"nigiwai-test-act/{name}")
    )  # stable, so the scripted scores are too
    tag_rows = [
        [t, n, "urn:tag:genre:qloo"] for t, n in (tags or [("urn:tag:genre:qloo:folk", "Folk")])
    ]
    admin.execute(
        "INSERT INTO qloo_entity (entity_id, type, types, name_nfc, tags, popularity, insights_eligible)"
        " VALUES (%s, %s, %s, %s, %s::jsonb, %s, true)",
        (entity_id, ARTIST, [ARTIST], name, json.dumps(tag_rows), popularity),
    )
    world.qloo.group_of[entity_id] = group
    row = artist(name, entity_id=entity_id, tags=tags or [("urn:tag:genre:qloo:folk", "Folk")])
    row["popularity"] = popularity
    world.qloo.neighbour_pool.append(row)
    return entity_id


async def crowd(world: World, admin: psycopg.Connection[Any], owner: Any, venue: Any) -> list[str]:
    """A planted guest crowd with three groups whose artists the scripted Qloo knows. Returns the planted ids."""
    ids = plant(admin, venue, 90)
    for i, e in enumerate(ids):
        world.qloo.group_of[e] = i // 24  # planted group 0, 1, 2
        world.qloo.names[e] = f"Item {i // 24}-{i % 24}"  # the names plant() stored
    await tribe_service.recompute(
        world.app.state.nigiwai.engine,
        None,
        uuid.UUID(owner.tenant_id),
        uuid.UUID(venue.business_id),
        force=True,
        cfg=FAST,
    )
    return ids


def base(owner: Any, venue: Any) -> str:
    return f"/businesses/{venue.business_id}"


def fit_calls(world: World) -> list[tuple[str, list[tuple[str, str]]]]:
    return [c for c in world.qloo.calls if "filter.results.entities" in dict(c[1])]


async def test_no_crowd_yet_says_what_to_do(world: World, admin: psycopg.Connection[Any]) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    status = (await owner.get(f"{base(owner, venue)}/soundcheck/basis")).json()
    assert status["use"] is None and status["guests"] is None and status["lineup"] is None
    cand = add_artist(admin, world, "Some Act", 0)
    res = await owner.post(f"{base(owner, venue)}/soundcheck", json={"entity_id": cand})
    assert res.status_code == 422 and "no crowd to check against" in res.json()["detail"]


async def test_an_act_in_one_planted_group_scores_high_for_that_group_and_the_verdict_is_stored(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    ids = await crowd(world, admin, owner, venue)
    cand = add_artist(admin, world, "Pale Meridian", 1)
    status = (await owner.get(f"{base(owner, venue)}/soundcheck/basis")).json()
    assert status["use"] == "guests" and status["guests"]["usable"]

    res = await owner.post(f"{base(owner, venue)}/soundcheck", json={"entity_id": cand})
    assert res.status_code == 200, res.text
    doc = res.json()
    assert doc["status"] == "ok" and isinstance(doc["score"], int)
    assert doc["band"][0] <= doc["score"] <= doc["band"][1]
    assert doc["candidate"]["name"] == "Pale Meridian" and doc["weights_version"] == "v0"
    assert doc["basis"]["kind"] == "guests" and not doc["peer_used"]

    # The act sits in planted group 1: whichever tribe holds that group ranks it above every reference.
    tribes = (await owner.get(f"{base(owner, venue)}/tribes")).json()["result"]["tribes"]
    planted = {t["index"]: ids.index(t["top_items"][0]["entity_id"]) // 24 for t in tribes}
    assert sorted(planted.values()) == [0, 1, 2]
    fits = {planted[g["index"]]: g["fit"] for g in doc["groups"] if g["status"] == "scored"}
    assert sorted(fits) == [0, 1, 2]  # every group was scored
    assert (
        fits[1] >= 0.75
    )  # the act belongs to planted group 1: it ranks near the top of that group's references
    assert fits[1] > max(
        fits[0], fits[2]
    )  # and clearly above how it ranks for the groups it does not belong to
    assert len(fit_calls(world)) == 3  # one Qloo call per group, never one per reference

    # Stored once; asking again with the same inputs returns the same row, score and hash.
    again = (await owner.post(f"{base(owner, venue)}/soundcheck", json={"entity_id": cand})).json()
    assert (again["id"], again["score"], again["input_hash"]) == (
        doc["id"],
        doc["score"],
        doc["input_hash"],
    )
    assert admin.execute("SELECT count(*) FROM soundcheck").fetchone() == (1,)
    listed = (await owner.get(f"{base(owner, venue)}/soundchecks")).json()
    assert [r["name"] for r in listed] == ["Pale Meridian"] and listed[0]["score"] == doc["score"]
    fetched = (await owner.get(f"{base(owner, venue)}/soundchecks/{doc['id']}")).json()
    assert fetched["score"] == doc["score"] and fetched["id"] == doc["id"]


async def test_an_excluded_genre_stops_the_check_before_any_qloo_call(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    await crowd(world, admin, owner, venue)
    put = await owner.put(
        f"/locations/{venue.location_id}",
        json={
            "name": "Main room",
            "lat": 51.5,
            "lon": -0.12,
            "timezone": "Europe/London",
            "excluded_genres": ["death metal"],
            "capacity": 120,
            "curfew": "23:00",
        },
    )
    assert put.status_code == 200, put.text
    bad = add_artist(
        admin, world, "Grave Choir", 0, tags=[("urn:tag:genre:qloo:dm", "Death Metal")]
    )
    before = len(fit_calls(world))
    res = (await owner.post(f"{base(owner, venue)}/soundcheck", json={"entity_id": bad})).json()
    assert res["status"] == "fails_constraint" and res["score"] is None
    assert res["reason"].startswith("Fails: Death Metal is on your excluded list")
    assert len(fit_calls(world)) == before  # no Qloo call was spent on an act that cannot be booked

    fine = add_artist(admin, world, "Quiet Folk", 0)
    ok = (await owner.post(f"{base(owner, venue)}/soundcheck", json={"entity_id": fine})).json()
    kinds = {c["name"]: c["status"] for c in ok["constraints"]}
    assert kinds == {"excluded genres": "pass", "capacity": "not_scored", "curfew": "not_scored"}
    assert any("Qloo has no stage-size" in c["detail"] for c in ok["constraints"])


async def test_what_is_not_an_artist_or_not_known_is_refused_with_a_reason(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    await crowd(world, admin, owner, venue)
    movie = str(uuid.uuid4())
    admin.execute(
        "INSERT INTO qloo_entity (entity_id, type, types, name_nfc, tags, insights_eligible)"
        " VALUES (%s, 'urn:entity:movie', ARRAY['urn:entity:movie'], 'A Film', '[]'::jsonb, true)",
        (movie,),
    )
    res = await owner.post(f"{base(owner, venue)}/soundcheck", json={"entity_id": movie})
    assert res.status_code == 422 and "pick an artist" in res.json()["detail"]
    res = await owner.post(
        f"{base(owner, venue)}/soundcheck", json={"entity_id": str(uuid.uuid4())}
    )
    assert res.status_code == 404 and "Search for the act first" in res.json()["detail"]
    junk = await owner.post(f"{base(owner, venue)}/soundcheck", json={"entity_id": "nope"})
    assert junk.status_code == 422
    extra = await owner.post(
        f"{base(owner, venue)}/soundcheck", json={"entity_id": str(uuid.uuid4()), "score": 100}
    )
    assert extra.status_code == 422  # unknown fields are refused, never ignored


async def test_qloo_being_down_gives_no_number_and_says_so(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    await crowd(world, admin, owner, venue)
    cand = add_artist(admin, world, "Offline Act", 0)
    world.qloo.down = True
    res = (await owner.post(f"{base(owner, venue)}/soundcheck", json={"entity_id": cand})).json()
    assert res["status"] in ("unscored", "insufficient") and res["score"] is None
    assert res["problems"] or res["reason"]


async def test_the_calls_behind_a_verdict_are_listed_with_what_was_sent(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    await crowd(world, admin, owner, venue)
    cand = add_artist(admin, world, "Traced Act", 2)
    doc = (await owner.post(f"{base(owner, venue)}/soundcheck", json={"entity_id": cand})).json()
    calls = (await owner.get(f"{base(owner, venue)}/soundchecks/{doc['id']}/calls")).json()
    assert len(calls) == 3 and all(
        c["purpose"] == "fit" and c["endpoint"] == "/v2/insights" for c in calls
    )
    sent = dict((k, v) for k, v in calls[0]["params"])
    assert cand in sent["filter.results.entities"].split(",")
    assert (
        len(sent["filter.results.entities"].split(",")) <= 21
        and "signal.interests.entities" in sent
    )


async def test_soundchecks_belong_to_their_account(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    other = await sign_up(world)
    venue = await make_venue(owner)
    await crowd(world, admin, owner, venue)
    cand = add_artist(admin, world, "Private Act", 0)
    doc = (await owner.post(f"{base(owner, venue)}/soundcheck", json={"entity_id": cand})).json()
    theirs = f"/v1/tenants/{owner.tenant_id}/businesses/{venue.business_id}"
    assert (await other.client.get(f"{theirs}/soundchecks")).status_code == 404
    assert (await other.client.get(f"{theirs}/soundchecks/{doc['id']}")).status_code == 404
    assert (
        await other.client.post(
            f"{theirs}/soundcheck", json={"entity_id": cand}, headers=other.headers
        )
    ).status_code == 404
    assert (await world.client().get(f"{theirs}/soundchecks")).status_code == 401
    assert (
        await world.client().post(f"{theirs}/soundcheck", json={"entity_id": cand})
    ).status_code in (401, 403)
    # and the other account has no soundchecks of its own
    own = f"/v1/tenants/{other.tenant_id}/businesses/{venue.business_id}"
    assert (await other.client.get(f"{own}/soundchecks")).status_code == 404


async def test_suggestions_build_in_the_worker_and_name_three_acts_and_a_wildcard(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    await crowd(world, admin, owner, venue)
    # Nine neighbours per group in the scripted Qloo; the unpopular ones in the two biggest groups can be the wildcard.
    for g in range(3):
        for i in range(9):
            add_artist(admin, world, f"Neighbour {g}-{i}", g, popularity=0.05 + 0.1 * i)
    assert (await owner.get(f"{base(owner, venue)}/suggestions")).json() is None
    queued = await owner.post(f"{base(owner, venue)}/suggestions")
    assert queued.status_code == 202
    admin.execute("UPDATE job SET run_after = now() WHERE state = 'pending'")
    state = world.app.state.nigiwai
    while await worker.work_once(state.engine, state.guard):
        pass
    got = (await owner.get(f"{base(owner, venue)}/suggestions")).json()
    assert got["status"] == "ready", got
    result = got["result"]
    assert len(result["top"]) == 3 and result["considered"] >= 9
    scores = [t["score"] for t in result["top"]]
    assert scores == sorted(scores, reverse=True)
    assert all(t["best_for"] and t["soundcheck_id"] for t in result["top"])
    top_ids = {t["entity_id"] for t in result["top"]}
    if result["wildcard"]:
        w = result["wildcard"]
        assert w["entity_id"] not in top_ids
        assert w["popularity"] is not None
    # every suggestion opens as a stored verdict with its own calls
    first = result["top"][0]
    opened = (await owner.get(f"{base(owner, venue)}/soundchecks/{first['soundcheck_id']}")).json()
    assert opened["score"] == first["score"] and opened["status"] == "ok"
    calls = (
        await owner.get(f"{base(owner, venue)}/soundchecks/{first['soundcheck_id']}/calls")
    ).json()
    assert len(calls) >= 3
    # refreshing twice queues one job
    await owner.post(f"{base(owner, venue)}/suggestions")
    await owner.post(f"{base(owner, venue)}/suggestions")
    assert admin.execute(
        "SELECT count(*) FROM job WHERE kind = 'suggest_acts' AND state = 'pending'"
    ).fetchone() == (1,)


async def test_suggestions_without_a_crowd_fail_with_the_reason_not_silently(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    await owner.post(f"{base(owner, venue)}/suggestions")
    admin.execute("UPDATE job SET run_after = now() WHERE state = 'pending'")
    state = world.app.state.nigiwai
    while await worker.work_once(state.engine, state.guard):
        pass
    got = (await owner.get(f"{base(owner, venue)}/suggestions")).json()
    assert got["status"] == "failed" and "no crowd to check against" in got["error"]


def test_the_wildcard_is_small_and_close_to_the_two_biggest_groups() -> None:
    def doc(name: str, pop: float, score: int, fits: tuple[float, float, float]) -> dict[str, Any]:
        groups = [
            {"index": i, "status": "scored", "share": s, "fit": f}
            for i, (s, f) in enumerate(zip((0.5, 0.3, 0.2), fits, strict=True))
        ]
        return {
            "status": "ok",
            "score": score,
            "groups": groups,
            "candidate": {"entity_id": name, "name": name, "popularity": pop},
        }

    results = [
        doc("big", 0.9, 80, (0.9, 0.9, 0.9)),  # too popular
        doc(
            "small-but-misses-a-group", 0.1, 70, (0.9, 0.3, 0.9)
        ),  # not close to the second biggest group
        doc("small-and-close", 0.1, 60, (0.7, 0.65, 0.2)),
        doc("small-and-closer", 0.2, 66, (0.8, 0.7, 0.2)),
    ]
    winner = sc.pick_wildcard(results, taken=set())
    assert winner is not None and winner["candidate"]["name"] == "small-and-closer"
    assert sc.pick_wildcard(results, taken={"small-and-closer", "small-and-close"}) is None
    assert sc.pick_wildcard([], taken=set()) is None


GENRES = {
    0: ["indie rock", "post-punk", "shoegaze", "garage rock", "lo-fi"],
    1: ["jazz", "bebop", "swing", "big band", "cool jazz"],
    2: ["techno", "house", "ambient", "minimal", "electro"],
}


def plant_lineup(
    admin: psycopg.Connection[Any],
    world: World,
    owner: Any,
    venue: Any,
    *,
    events: int = 40,
    acts_per_scene: int = 9,
    with_acts: bool = True,
) -> dict[str, int]:
    """A ready public-lineup profile for the venue: acts in three genre scenes, each stored with its Qloo tags."""
    acts: list[dict[str, Any]] = []
    group_of: dict[str, int] = {}
    for g, genres in GENRES.items():
        for i in range(acts_per_scene):
            entity_id = str(uuid.UUID(int=(0x9 << 100) + g * 1000 + i + 1))
            tags = [
                [
                    f"urn:tag:genre:qloo:{genres[(i + k) % 5]}",
                    genres[(i + k) % 5],
                    "urn:tag:genre:qloo",
                ]
                for k in range(3)
            ]
            admin.execute(
                "INSERT INTO qloo_entity (entity_id, type, types, name_nfc, tags, insights_eligible)"
                " VALUES (%s, %s, %s, %s, %s::jsonb, true) ON CONFLICT (entity_id) DO NOTHING",
                (entity_id, ARTIST, [ARTIST], f"Scene {g} Act {i}", json.dumps(tags)),
            )
            world.qloo.group_of[entity_id] = g
            world.qloo.names[entity_id] = f"Scene {g} Act {i}"
            acts.append(
                {
                    "entity_id": entity_id,
                    "name": f"Scene {g} Act {i}",
                    "mbid": str(uuid.uuid4()),
                    "events": 2 + (i % 5) + (6 if g == 0 else 0),
                    "tags": tags,
                }
            )
            group_of[entity_id] = g
    doc: dict[str, Any] = {
        "state": "profile",
        "events": {"used": events, "with_lineup": events},
        "performers": {"unique": len(acts) + 5, "resolved": len(acts)},
        "weekdays": [0, 0, 1, 2, 12, 20, 5],
    }
    if with_acts:
        doc["acts"] = acts
    admin.execute(
        "INSERT INTO lineup_profile (tenant_id, business_id, place_mbid, place_name, status, result, finished_at)"
        " VALUES (%s, %s, %s, 'Mercury Test Room', 'ready', %s::jsonb, now())",
        (owner.tenant_id, venue.business_id, str(uuid.uuid4()), json.dumps(doc)),
    )
    return group_of


async def test_a_venue_with_only_public_lineups_gets_a_provisional_soundcheck(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    plant_lineup(admin, world, owner, venue)
    status = (await owner.get(f"{base(owner, venue)}/soundcheck/basis")).json()
    assert status["use"] == "lineup" and status["lineup"]["sufficient"] and status["guests"] is None
    cand = add_artist(admin, world, "Newcomer", 1)
    doc = (await owner.post(f"{base(owner, venue)}/soundcheck", json={"entity_id": cand})).json()
    assert doc["status"] == "ok" and doc["provisional"] is True
    assert doc["basis"]["kind"] == "lineup" and "Mercury Test Room" in doc["basis"]["label"]
    assert any("Provisional" in n for n in doc["notes"])
    assert doc["suits"] and set(doc["suits"]) <= {4, 5}  # the lineup's Fridays and Saturdays
    assert any("acts" in w for w in doc["why"])  # groups of a lineup are counted in acts
    assert len(doc["groups"]) == 3 and len(fit_calls(world)) == 3


async def test_a_lineup_too_thin_for_a_score_gives_no_number_and_spends_no_calls(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    plant_lineup(admin, world, owner, venue, events=6)
    cand = add_artist(admin, world, "Newcomer", 1)
    doc = (await owner.post(f"{base(owner, venue)}/soundcheck", json={"entity_id": cand})).json()
    assert doc["status"] == "insufficient" and doc["score"] is None
    assert "6 events" in doc["reason"] and "at least 10 events" in doc["reason"]
    assert fit_calls(world) == []


async def test_a_lineup_saved_before_soundcheck_existed_asks_for_a_rebuild(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    plant_lineup(admin, world, owner, venue, with_acts=False)
    cand = add_artist(admin, world, "Newcomer", 1)
    res = await owner.post(f"{base(owner, venue)}/soundcheck", json={"entity_id": cand})
    assert res.status_code == 422 and "Rebuild it on My people" in res.json()["detail"]


async def test_an_act_the_crowd_already_favours_is_measured_against_its_other_favourites(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    ids = await crowd(world, admin, owner, venue)
    favourite = ids[0]  # an artist of planted group 0, picked by that group's guests
    doc = (
        await owner.post(f"{base(owner, venue)}/soundcheck", json={"entity_id": favourite})
    ).json()
    assert doc["status"] == "ok"
    assert all(
        g["status"] == "scored" for g in doc["groups"]
    )  # no group loses its signal to the act itself
    assert any("already among the most-picked acts" in n for n in doc["notes"])
    sent = [dict(c[1]) for c in fit_calls(world)]
    assert all(favourite not in c["signal.interests.entities"].split(",") for c in sent)
