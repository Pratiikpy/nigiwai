"""A guest names a favourite place (PRD M3): searched near the venue they are in, never from another venue's saved matches, never a place
that stands for something this product does not collect, stored like any other pick, read by the groups engine through its taste tags
only, and usable for the Taste Card. Qloo is scripted; every name is invented."""

from __future__ import annotations

import json
import re
from typing import Any

import psycopg
from fakeqloo import artist, search_place
from harness import World, make_venue, sign_up
from nigiwai_api.services import tribes as tribes_service
from test_picker import search, start
from test_public_survey import submission
from test_tribes import FAST, plant

PLACE = "urn:entity:place"
LONDON = {"lat": 51.5, "lon": -0.12}
PARIS = {"lat": 48.8566, "lon": 2.3522}


def searches(world: World) -> list[dict[str, str]]:
    return [dict(p) for path, p in world.qloo.calls if path == "/search"]


async def test_a_favourite_place_is_searched_near_the_venue_and_only_what_a_guest_needs_comes_back(
    world: World,
) -> None:
    world.qloo.catalogue = [
        search_place("Corner Tap", address="1 Invented Street, London", **PARIS),
        search_place("Corner Tap", address="2 Invented Road, London", **LONDON),
        search_place(
            "Cornerstone Cafe", address="3 Invented Lane, London", kind="Cafe", lat=51.51, lon=-0.13
        ),
    ]
    guest, token, nonce = await start(world)
    out = await search(guest, token, nonce, "corner", type="place")
    # the venue's own point (London) biased the search: the near one is first, the one in another city last
    assert [(i["name"], i["description"]) for i in out["items"]] == [
        ("Corner Tap", "2 Invented Road, London"),
        ("Cornerstone Cafe", "3 Invented Lane, London"),
        ("Corner Tap", "1 Invented Street, London"),
    ]
    assert out["source"] == "qloo" and all(i["type"] == "place" for i in out["items"])
    sent = searches(world)
    assert (
        len(sent) == 1
        and sent[0]["types"] == PLACE
        and sent[0]["filter.location"] == "51.5000,-0.1200"
    )
    # a guest is told a name and an address, and nothing that locates the venue, describes Qloo's data or names a tag
    body = json.dumps(out)
    for private in (
        "51.5",
        "-0.12",
        "lat",
        "lon",
        "popularity",
        "Visa",
        "Lively",
        "tags",
        "location",
    ):
        assert private not in body, private
    # asking again is served from the private cache, with no second call to Qloo
    again = await search(guest, token, nonce, "corner", type="place")
    assert [i["entity_id"] for i in again["items"]] == [i["entity_id"] for i in out["items"]]
    assert again["source"] == "cache" and len(searches(world)) == 1


async def test_places_are_never_taken_from_the_saved_index_that_every_venue_shares(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    # a place a guest at another venue, in another city, once found is in the saved index. It must not be offered here.
    admin.execute(
        "INSERT INTO qloo_entity (entity_id, type, types, name_nfc) VALUES (%s, %s, %s, 'Elsewhere Bar')",
        ("00000000-0000-4000-8000-0000000000aa", PLACE, [PLACE]),
    )
    guest, token, nonce = await start(world)
    out = await search(guest, token, nonce, "elsewhere", type="place")
    assert out["items"] == [] and "No place by that name near here" in out["message"]
    assert len(searches(world)) == 1  # it went to Qloo, which had nothing: the index was not read


async def test_all_means_every_kind_but_places_which_are_their_own_category(world: World) -> None:
    world.qloo.catalogue = [artist("Moon Act"), search_place("Moon Bar")]
    guest, token, nonce = await start(world)
    out = await search(guest, token, nonce, "moon")
    assert [i["name"] for i in out["items"]] == ["Moon Act"]
    sent = searches(world)
    assert "urn:entity:place" not in sent[0]["types"] and "filter.location" not in sent[0]


async def test_a_survey_that_does_not_ask_for_places_refuses_a_place_search(world: World) -> None:
    guest, token, nonce = await start(world, picker_types=["artist", "movie"])
    r = await guest.post(
        "/v1/public/picker", json={"token": token, "nonce": nonce, "q": "corner", "type": "place"}
    )
    assert r.status_code == 422 and "not part of this survey" in r.json()["detail"]
    assert world.qloo.calls == []


async def test_a_new_survey_asks_for_places_unless_the_owner_chose_other_kinds(
    world: World,
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    page = (await world.client().get(f"/v1/public/survey/{venue.token}")).json()
    assert "place" in page["questions"]["picker_types"]
    chosen = await make_venue(owner, questions={"picker_types": ["artist"]})
    page = (await world.client().get(f"/v1/public/survey/{chosen.token}")).json()
    assert page["questions"]["picker_types"] == ["artist"]


async def test_a_place_that_stands_for_something_never_collected_is_not_offered_and_cannot_be_stored(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    chapel = search_place("Quiet Chapel", kind="Church")
    clinic = search_place("Quiet Clinic", kind="Medical clinic")
    halal = search_place("Quiet Grill", kind="Halal restaurant")
    bar = search_place("Quiet Bar")
    # a bar called Temple is a bar: only the kind of place is read, not its name
    temple = search_place("Quiet Temple Bar", kind="Bar")
    world.qloo.catalogue = [chapel, clinic, halal, bar, temple]
    guest, token, nonce = await start(world)
    out = await search(guest, token, nonce, "quiet", type="place")
    assert [i["name"] for i in out["items"]] == ["Quiet Bar", "Quiet Temple Bar"]

    # the guest cannot choose one by hand either: the registry knows them from the search, and every route refuses them
    for hidden in (chapel, clinic, halal):
        chosen = await guest.post(
            "/v1/public/select",
            json={"token": token, "nonce": nonce, "entity_id": hidden["entity_id"]},
        )
        assert chosen.status_code == 200 and chosen.json()["eligible"] is False
    ids = [chapel["entity_id"], bar["entity_id"], temple["entity_id"]]
    sent = await guest.post("/v1/public/response", json=submission(token, nonce, ids))
    assert sent.status_code == 422 and "can't be used" in sent.json()["detail"]
    assert admin.execute("SELECT count(*) FROM response").fetchone() == (0,)


async def test_a_venue_with_no_position_says_so_and_asks_qloo_nothing(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    guest, token, nonce = await start(world)
    admin.execute("UPDATE location SET geom = NULL")
    out = await search(guest, token, nonce, "corner", type="place")
    assert out["items"] == [] and "no position on the map" in out["message"]
    assert world.qloo.calls == []


async def test_place_searches_count_toward_the_sitting_cap_and_qloo_being_down_is_said(
    make_world: Any,
) -> None:
    async with make_world(picker_calls_per_session=2) as world:
        world.qloo.catalogue = [search_place("Corner Tap")]
        guest, token, nonce = await start(world)
        assert (await search(guest, token, nonce, "corner", type="place"))["items"]
        world.qloo.down = True
        down = await search(guest, token, nonce, "tap", type="place")
        assert down["items"] == [] and "unavailable right now" in down["message"]
        world.qloo.down = False
        calls = len(world.qloo.calls)
        capped = await search(guest, token, nonce, "corn", type="place")
        assert capped["items"] == [] and "a lot of searching" in capped["message"]
        assert len(world.qloo.calls) == calls  # past the cap, Qloo is not asked


async def test_a_picked_place_is_stored_with_its_tags_and_a_response_can_hold_places_with_other_picks(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    tap = search_place("Corner Tap")
    act = artist("Lantern Hollow", tags=[("urn:tag:genre:qloo:folk", "Folk")])
    world.qloo.catalogue = [tap, act]
    guest, token, nonce = await start(world)
    await search(guest, token, nonce, "corner", type="place")
    await search(guest, token, nonce, "lantern", type="artist")
    picks = [tap["entity_id"], act["entity_id"]] + [
        search_place(f"Extra {i}")["entity_id"] for i in range(0)
    ]
    for pick in picks:
        chosen = await guest.post(
            "/v1/public/select", json={"token": token, "nonce": nonce, "entity_id": pick}
        )
        assert chosen.status_code == 200 and chosen.json()["eligible"] is True
    third = search_place("Corner Tap Two")
    world.qloo.catalogue.append(third)
    await search(guest, token, nonce, "tap two", type="place")
    picks.append(third["entity_id"])
    sent = await guest.post("/v1/public/response", json=submission(token, nonce, picks))
    assert sent.status_code == 201, sent.text
    assert admin.execute(
        "SELECT p.entity_type, p.position FROM pick p ORDER BY p.position"
    ).fetchall() == [(PLACE, 1), ("urn:entity:artist", 2), (PLACE, 3)]
    # the place's tags were kept when it was chosen (the probe did not clear them): its taste tags, and none of the facilities or
    # descriptions of other people that Qloo also lists (the fake lists payments, accessibility and customer_identity as well)
    stored = admin.execute(
        "SELECT tags FROM qloo_entity WHERE entity_id = %s", (tap["entity_id"],)
    ).fetchone()
    assert stored is not None
    assert sorted(t[0].split(":")[2] for t in stored[0]) == [
        "ambience",
        "category",
        "decor",
        "genre",
    ]


async def test_the_groups_are_built_from_a_places_taste_tags_and_never_its_facilities(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    plant(admin, venue, 70)
    # every guest also named one place; the place carries taste tags and a long list of facilities and descriptions of other people
    bars = [search_place(f"Bar {i}") for i in range(4)]
    survey = admin.execute(
        "SELECT id, version FROM survey WHERE business_id = %s AND status = 'published'",
        (venue.business_id,),
    ).fetchone()
    assert survey is not None
    for bar in bars:
        admin.execute(
            "INSERT INTO qloo_entity (entity_id, type, types, name_nfc, tags, insights_eligible) VALUES (%s, %s, %s, %s, %s::jsonb, true)",
            (
                bar["entity_id"],
                PLACE,
                [PLACE],
                bar["name"],
                json.dumps([[t["tag_id"], t["name"], t["type"]] for t in bar["tags"]]),
            ),
        )
    rows = admin.execute(
        "SELECT id FROM response WHERE tenant_id = %s", (owner.tenant_id,)
    ).fetchall()
    for i, (response_id,) in enumerate(rows):
        bar = bars[i % 4]
        admin.execute(
            "INSERT INTO pick (response_id, position, tenant_id, entity_id, entity_type) VALUES (%s, 6, %s, %s, %s)",
            (response_id, owner.tenant_id, bar["entity_id"], PLACE),
        )
    state = world.app.state.nigiwai
    out = await tribes_service.recompute(
        state.engine, None, owner.tenant_id, venue.business_id, force=True, cfg=FAST
    )
    assert out.stored
    result = admin.execute(
        "SELECT result FROM tribe_version WHERE business_id = %s ORDER BY version DESC LIMIT 1",
        (venue.business_id,),
    ).fetchone()
    assert result is not None
    blob = json.dumps(result[0])
    # taste tags of the places are in the groups' vocabulary; facilities and descriptions of other people never are
    assert "Lively" in blob or "Industrial" in blob
    for facility in ("Visa", "Wheelchair accessible entrance", "Students"):
        assert facility not in blob, facility


def test_the_guard_and_the_groups_engine_read_a_place_through_the_same_namespaces() -> None:
    """The Guard stores only these tags of a place and the engine counts only these: two copies of one list, kept equal here."""
    from nigiwai_tribes import PLACE_TASTE_NAMESPACES as engine
    from qloo_guard.parse import PLACE_TASTE_NAMESPACES as guard

    assert engine == guard


def test_places_stored_before_the_guard_kept_only_taste_tags_are_cleaned_by_the_migration(
    admin: psycopg.Connection[Any],
) -> None:
    from pathlib import Path

    from qloo_guard.parse import PLACE_TASTE_NAMESPACES

    sql = (
        Path(__file__).resolve().parents[3] / "db/migrations/sql/0022_place_tags_minimised.sql"
    ).read_text(encoding="utf-8")
    listed = set(re.findall(r"'([a-z_]+)'", sql.split("SELECT minimise_place_tags(ARRAY[", 1)[1]))
    assert listed == set(PLACE_TASTE_NAMESPACES)  # the migration's copy of the list is the Guard's

    tags = [
        ["urn:tag:ambience:qloo:lively", "Lively", "urn:tag:ambience:qloo"],
        ["urn:tag:customer_identity:qloo:students", "Students", "urn:tag:customer_identity:qloo"],
        ["urn:tag:dietary_option:qloo:halal", "Halal", "urn:tag:dietary_option:qloo"],
        ["urn:tag:genre:place:bar", "Bar", "urn:tag:genre:place"],
        ["urn:tag:payments:place:visa", "Visa", "urn:tag:payments:place"],
    ]
    admin.execute(
        "INSERT INTO qloo_entity (entity_id, type, types, name_nfc, tags) VALUES"
        " ('00000000-0000-4000-8000-0000000000b1', 'urn:entity:place', ARRAY['urn:entity:place'], 'Old Tap', %s::jsonb),"
        " ('00000000-0000-4000-8000-0000000000b2', 'urn:entity:artist', ARRAY['urn:entity:artist'], 'Old Act', %s::jsonb)",
        (json.dumps(tags), json.dumps(tags)),
    )
    changed = admin.execute("SELECT minimise_place_tags(%s)", (sorted(listed),)).fetchone()
    assert changed == (1,)
    kept = admin.execute(
        "SELECT tags FROM qloo_entity WHERE entity_id = '00000000-0000-4000-8000-0000000000b1'"
    ).fetchone()
    assert kept is not None and [t[1] for t in kept[0]] == ["Lively", "Bar"]  # the order is kept
    untouched = admin.execute(
        "SELECT jsonb_array_length(tags) FROM qloo_entity WHERE entity_id = '00000000-0000-4000-8000-0000000000b2'"
    ).fetchone()
    assert untouched == (5,)  # only places are cleaned
    assert admin.execute("SELECT minimise_place_tags(%s)", (sorted(listed),)).fetchone() == (
        0,
    )  # and it is a no-op the second time
