"""The picker: local index first, live Qloo only to fill gaps, eligibility probed on choice, all through the Guard."""

from __future__ import annotations

from typing import Any

import httpx
import psycopg
from fakeqloo import artist, movie, new_id
from harness import World, make_venue, seed_entities, sign_up

ARTIST = "urn:entity:artist"
MOVIE = "urn:entity:movie"


async def start(world: World, **survey: Any) -> tuple[httpx.AsyncClient, str, str]:
    owner = await sign_up(world)
    venue = await make_venue(owner, questions=survey or None)
    guest = world.client()
    page = (await guest.get(f"/v1/public/survey/{venue.token}")).json()
    return guest, venue.token, page["nonce"]


async def search(
    guest: httpx.AsyncClient, token: str, nonce: str, q: str, **extra: Any
) -> dict[str, Any]:
    r = await guest.post(
        "/v1/public/picker", json={"token": token, "nonce": nonce, "q": q, **extra}
    )
    assert r.status_code == 200, r.text
    return r.json()


async def test_short_and_empty_queries_say_so_and_cost_nothing(world: World) -> None:
    guest, token, nonce = await start(world)
    for q in ("", " ", "a", "  b  "):
        out = await search(guest, token, nonce, q)
        assert out["items"] == [] and out["source"] == "none" and "at least" in out["message"]
    assert world.qloo.calls == []


async def test_local_results_rank_prefix_matches_first_and_never_call_qloo(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    seed_entities(
        admin,
        [
            (new_id(), ARTIST, "The Red Lanterns"),
            (new_id(), ARTIST, "Lantern Hollow"),
            (new_id(), ARTIST, "Lantern"),
            (new_id(), ARTIST, "Blue Sparrow"),
            (new_id(), ARTIST, "Silent Lantern Society"),
            (new_id(), ARTIST, "Lanterns of Marrow"),
            (new_id(), ARTIST, "Lantern Row"),
        ],
    )
    guest, token, nonce = await start(world)
    out = await search(guest, token, nonce, "lantern")
    names = [i["name"] for i in out["items"]]
    assert names[0] == "Lantern" and set(names[:3]) >= {"Lantern", "Lantern Hollow", "Lantern Row"}
    assert "Blue Sparrow" not in names and out["source"] == "local"
    assert world.qloo.calls == []


async def test_search_is_case_accent_and_whitespace_tolerant(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    seed_entities(
        admin,
        [(new_id(), ARTIST, "Björk Guðmundsdóttir"), (new_id(), ARTIST, "Beyoncé")]
        + [(new_id(), ARTIST, f"Filler Band {i}") for i in range(7)],
    )
    guest, token, nonce = await start(world)
    assert [i["name"] for i in (await search(guest, token, nonce, "  BEYONCÉ  "))["items"]][:1] == [
        "Beyoncé"
    ]
    assert [i["name"] for i in (await search(guest, token, nonce, "björk"))["items"]][:1] == [
        "Björk Guðmundsdóttir"
    ]


async def test_like_wildcards_in_queries_are_literal(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    seed_entities(
        admin,
        [(new_id(), ARTIST, "Plain Name"), (new_id(), ARTIST, "100% Silk")]
        + [(new_id(), ARTIST, f"Filler {i}") for i in range(7)],
    )
    guest, token, nonce = await start(world)
    out = await search(guest, token, nonce, "%%")
    assert [i["name"] for i in out["items"]] == []
    out = await search(guest, token, nonce, "100% silk")
    assert out["items"] and out["items"][0]["name"] == "100% Silk"
    assert (await search(guest, token, nonce, "_____"))["items"] == []
    for hostile in ("'; DROP TABLE qloo_entity; --", "\\", "a\x00b", "😀😀", "x" * 5000):
        r = await guest.post(
            "/v1/public/picker", json={"token": token, "nonce": nonce, "q": hostile}
        )
        assert r.status_code in (200, 422), (hostile[:20], r.status_code)


async def test_only_the_asked_for_types_come_back(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    seed_entities(
        admin,
        [(new_id(), ARTIST, "Moonlight Act"), (new_id(), MOVIE, "Moonlight")]
        + [(new_id(), ARTIST, f"Moon Filler {i}") for i in range(7)],
    )
    guest, token, nonce = await start(world, picker_types=["movie"])
    out = await search(guest, token, nonce, "moon")
    assert [i["name"] for i in out["items"]] == ["Moonlight"] and out["items"][0]["type"] == "movie"
    r = await guest.post(
        "/v1/public/picker", json={"token": token, "nonce": nonce, "q": "moon", "type": "artist"}
    )
    assert r.status_code == 422  # this survey does not ask for artists


async def test_ineligible_entities_are_never_offered(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    bad = new_id()
    seed_entities(
        admin,
        [(bad, ARTIST, "Rejected Band")]
        + [(new_id(), ARTIST, f"Rejected Filler {i}") for i in range(7)],
    )
    admin.execute("UPDATE qloo_entity SET insights_eligible = false WHERE entity_id = %s", (bad,))
    guest, token, nonce = await start(world)
    names = [i["name"] for i in (await search(guest, token, nonce, "rejected band"))["items"]]
    assert "Rejected Band" not in names


async def test_sparse_local_results_are_topped_up_from_qloo_and_remembered(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    world.qloo.catalogue = [
        artist("Harbour Lights", year=1999),
        artist("Harbour Fog"),
        movie("Harbour Road"),
    ]
    guest, token, nonce = await start(world)
    first = await search(guest, token, nonce, "harbour")
    assert {i["name"] for i in first["items"]} == {"Harbour Lights", "Harbour Fog", "Harbour Road"}
    assert first["source"] == "qloo"
    assert any(path == "/search" for path, _ in world.qloo.calls)
    lights = next(i for i in first["items"] if i["name"] == "Harbour Lights")
    assert lights["year"] == 1999 and lights["description"]
    calls_after_first = len(world.qloo.calls)
    # The same query again is answered from the Guard's private cache, not sent to Qloo a second time.
    repeat = await search(guest, token, nonce, "harbour")
    assert {i["name"] for i in repeat["items"]} == {"Harbour Lights", "Harbour Fog", "Harbour Road"}
    assert len(world.qloo.calls) == calls_after_first
    # A longer query finds the saved entity first.
    again = await search(guest, token, nonce, "harbour lights")
    assert again["items"][0]["name"] == "Harbour Lights"
    rows = admin.execute(
        "SELECT count(*) FROM qloo_entity WHERE name_nfc LIKE 'Harbour%'"
    ).fetchone()
    assert rows == (3,)


async def test_every_live_search_is_traced_and_counted(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    world.qloo.catalogue = [artist("Trace Me")]
    guest, token, nonce = await start(world)
    await search(guest, token, nonce, "trace me")
    row = admin.execute(
        "SELECT purpose, endpoint, status, transport, cache, tenant_id FROM qloo_call"
    ).fetchone()
    assert row is not None and row[:4] == ("picker", "/search", "ok", "rest") and row[5] is not None
    assert admin.execute("SELECT count(*) FROM trace").fetchone() == (1,)


async def test_live_searches_are_capped_per_sitting_but_local_search_is_not(
    make_world: Any, admin: psycopg.Connection[Any]
) -> None:
    async with make_world(picker_calls_per_session=2) as world:
        world.qloo.catalogue = [
            artist(n) for n in ("Amber Wolves", "Birch Choir", "Coral Static", "Dune Parade")
        ]
        guest, token, nonce = await start(world)
        for q in ("amber", "birch", "coral", "dune"):
            await search(guest, token, nonce, q)
        searches = [c for c in world.qloo.calls if c[0] == "/search"]
        assert len(searches) == 2
        seed_entities(admin, [(new_id(), ARTIST, "Local Only")] * 1)
        assert (await search(guest, token, nonce, "local only"))["items"][0]["name"] == "Local Only"


async def test_when_qloo_is_down_the_picker_keeps_working_from_saved_matches(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    seed_entities(admin, [(new_id(), ARTIST, "Saved Act")])
    world.qloo.down = True
    guest, token, nonce = await start(world)
    out = await search(guest, token, nonce, "saved act")
    assert [i["name"] for i in out["items"]] == ["Saved Act"]
    assert "unavailable" in out["message"] and out["source"] == "local"
    nothing = await search(guest, token, nonce, "zzzz unknown")
    assert nothing["items"] == [] and nothing["source"] == "none"


async def test_selecting_probes_eligibility_once_and_remembers_it(world: World) -> None:
    good, bad = artist("Probe Good"), artist("Probe Bad")
    world.qloo.catalogue = [good, bad]
    world.qloo.ineligible = {bad["entity_id"]}
    guest, token, nonce = await start(world)
    await search(guest, token, nonce, "probe")
    ok = await guest.post(
        "/v1/public/select", json={"token": token, "nonce": nonce, "entity_id": good["entity_id"]}
    )
    assert ok.json() == {"entity_id": good["entity_id"], "eligible": True, "message": None}
    refused = await guest.post(
        "/v1/public/select", json={"token": token, "nonce": nonce, "entity_id": bad["entity_id"]}
    )
    assert (
        refused.status_code == 200
        and refused.json()["eligible"] is False
        and "choose another" in refused.json()["message"]
    )
    probes = [c for c in world.qloo.calls if c[0] == "/v2/insights"]
    assert len(probes) == 2
    await guest.post(
        "/v1/public/select", json={"token": token, "nonce": nonce, "entity_id": good["entity_id"]}
    )
    assert (
        len([c for c in world.qloo.calls if c[0] == "/v2/insights"]) == 2
    )  # remembered, no second probe
    # An ineligible item no longer shows up in search at all.
    names = [i["name"] for i in (await search(guest, token, nonce, "probe bad"))["items"]]
    assert "Probe Bad" not in names


async def test_selecting_something_never_offered_is_404(world: World) -> None:
    guest, token, nonce = await start(world)
    for entity_id in (new_id(), "x" * 36):
        r = await guest.post(
            "/v1/public/select", json={"token": token, "nonce": nonce, "entity_id": entity_id}
        )
        assert r.status_code == 404


async def test_selecting_while_qloo_is_down_accepts_the_pick_unverified(world: World) -> None:
    item = artist("Offline Pick")
    world.qloo.catalogue = [item]
    guest, token, nonce = await start(world)
    await search(guest, token, nonce, "offline pick")
    world.qloo.down = True
    r = await guest.post(
        "/v1/public/select", json={"token": token, "nonce": nonce, "entity_id": item["entity_id"]}
    )
    assert r.status_code == 200 and r.json()["eligible"] is None


async def test_picker_needs_a_valid_token_and_nonce(world: World) -> None:
    guest, token, nonce = await start(world)
    assert (
        await guest.post("/v1/public/picker", json={"token": "A" * 24, "nonce": nonce, "q": "abc"})
    ).status_code == 404
    assert (
        await guest.post(
            "/v1/public/picker", json={"token": token, "nonce": "bad.nonce.value", "q": "abc"}
        )
    ).status_code == 403
    assert (
        await guest.post("/v1/public/picker", json={"token": token, "nonce": nonce})
    ).status_code == 422
    assert (
        await guest.post(
            "/v1/public/select",
            json={"token": token, "nonce": "bad.nonce.value", "entity_id": new_id()},
        )
    ).status_code == 403
