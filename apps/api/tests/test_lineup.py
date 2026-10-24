"""The public-lineup start: MusicBrainz in (mocked at the network edge), exact matches to Qloo, an honest profile out."""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from typing import Any

import httpx
import psycopg
import pytest
import respx
from fakeqloo import artist
from harness import World, make_venue, sign_up
from nigiwai_api import worker
from nigiwai_api.services import lineup
from nigiwai_api.services.lineup import MusicBrainz, exact_match, normalise_name

MB = "https://musicbrainz.test/ws/2"
PLACE = "d7cb3789-c62f-4f5c-a0e0-9e1ceb525114"


@pytest.fixture(autouse=True)
def fast_musicbrainz(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(MusicBrainz, "INTERVAL", 0.0)


def mbid(n: int) -> str:
    return str(uuid.UUID(int=n + (0xAB << 100)))


def entity(n: int) -> str:
    return str(uuid.UUID(int=n + (0xEF << 100)))


def events_body(n_events: int, pool: int, per_event: int = 3) -> dict[str, Any]:
    events = []
    for e in range(n_events):
        acts = [(e * 2 + k) % pool for k in range(per_event)]
        events.append(
            {
                "id": str(uuid.UUID(int=e + (0xCD << 100))),
                "name": f"Night {e}",
                "life-span": {"begin": f"2025-{1 + e % 12:02d}-{1 + e % 27:02d}"},
                "relations": [
                    {
                        "type": "main performer" if k == 0 else "support act",
                        "artist": {"id": mbid(a), "name": f"Act {a}"},
                    }
                    for k, a in enumerate(acts)
                ],
            }
        )
    return {"event-count": n_events, "events": events}


def mock_musicbrainz(router: respx.MockRouter, events: dict[str, Any]) -> None:
    router.get(f"{MB}/place").mock(
        return_value=httpx.Response(
            200,
            json={
                "places": [
                    {
                        "id": PLACE,
                        "name": "Mercury Lounge",
                        "type": "Venue",
                        "address": "217 East Houston St.",
                        "area": {"name": "Lower East Side"},
                    },
                    {
                        "id": mbid(999),
                        "name": "Mercury Lounge",
                        "disambiguation": "venue, Austin, TX",
                        "area": {"name": "Austin"},
                    },
                ]
            },
        )
    )
    router.get(f"{MB}/event").mock(return_value=httpx.Response(200, json=events))


def qloo_knows(world: World, acts: range, *, skip: frozenset[int] = frozenset()) -> None:
    world.qloo.catalogue = [
        artist(
            f"Act {a}",
            entity_id=entity(a),
            mbid=mbid(a),
            tags=[
                (f"urn:tag:genre:qloo:g{a % 3}", f"Genre {a % 3}"),
                (f"urn:tag:genre:qloo:s{a % 5}", f"Style {a % 5}"),
            ],
        )
        for a in acts
        if a not in skip
    ]


async def run(world: World, admin: psycopg.Connection[Any]) -> None:
    admin.execute("UPDATE job SET run_after = now() WHERE state = 'pending'")
    state = world.app.state.nigiwai
    while await worker.work_once(state.engine, state.guard, state.musicbrainz):
        pass


async def start(owner: Any, business_id: str) -> Any:
    return await owner.post(
        f"/businesses/{business_id}/lineup",
        json={"mbid": PLACE, "name": "Mercury Lounge", "area": "Lower East Side"},
    )


@pytest.mark.parametrize(
    ("a", "b", "same"),
    [
        ("The Black Keys", "Black Keys", True),
        ("Beyoncé", "Beyonce", True),
        ("Simon & Garfunkel", "Simon and Garfunkel", True),
        ("M.I.A.", "MIA", True),
        ("Alex English", "Alex Clare", False),
        ("Blur", "Blurt", False),
        ("!!!", "!!!", True),
        ("!!!", "???", False),
        ("", "x", False),
    ],
)
def test_names_match_only_when_they_are_the_same_act(a: str, b: str, same: bool) -> None:
    assert exact_match(a, b) is same
    assert normalise_name("  The   Cure ") == "cure"


async def test_searching_for_a_venue_lists_candidates_with_their_places(
    make_world: Any, admin: psycopg.Connection[Any]
) -> None:
    async with make_world(musicbrainz_url=MB) as world:
        owner = await sign_up(world)
        venue = await make_venue(owner)
        with respx.mock(assert_all_called=False) as router:
            mock_musicbrainz(router, events_body(3, 5))
            r = await owner.get(
                f"/businesses/{venue.business_id}/lineup/search", params={"q": "Mercury Lounge"}
            )
            sent = router.calls.last.request
        assert r.status_code == 200
        assert [c["area"] for c in r.json()] == ["Lower East Side", "Austin"]
        assert r.json()[0]["mbid"] == PLACE
        assert sent.headers["user-agent"].startswith(
            "Nigiwai/0.1 ("
        )  # MusicBrainz requires an identifying agent
        assert (
            await owner.get(f"/businesses/{venue.business_id}/lineup/search", params={"q": "x"})
        ).status_code == 422


async def test_a_profile_is_built_from_public_lineups_with_exact_matches_only(
    make_world: Any, admin: psycopg.Connection[Any]
) -> None:
    async with make_world(musicbrainz_url=MB) as world:
        owner = await sign_up(world)
        venue = await make_venue(owner)
        qloo_knows(world, range(0, 40), skip=frozenset({5, 6}))  # Qloo holds 38 of the 40 acts
        with respx.mock(assert_all_called=False) as router:
            mock_musicbrainz(router, events_body(20, 40))
            assert (await start(owner, venue.business_id)).status_code == 202
            queued = (await owner.get(f"/businesses/{venue.business_id}/lineup")).json()
            assert queued["status"] == "queued" and queued["result"] is None
            await run(world, admin)
        got = (await owner.get(f"/businesses/{venue.business_id}/lineup")).json()
        assert got["status"] == "ready", got
        res = got["result"]
        assert res["label"] == "Modelled from public lineups" and res["state"] == "profile"
        assert res["events"]["used"] == 20 and res["events"]["with_lineup"] == 20
        assert res["events"]["first"] <= res["events"]["last"]
        assert res["performers"]["unique"] == 40 and res["performers"]["resolved"] == 38
        assert res["performers"]["rate"] == 0.95
        assert res["source"]["licence"].startswith("CC0")
        assert res["top_tags"] and all(t["acts"] >= 2 for t in res["top_tags"])
        assert res["groups"] is None  # 20 events cannot support groups
        # An act Qloo does not hold keeps its MusicBrainz name and has no Qloo id: nothing is invented for it.
        unresolved = [a for a in res["top_acts"] if a["entity_id"] is None]
        assert all(a["name"].startswith("Act ") for a in unresolved)
        # Every Qloo item shown exists in the local index, which only holds what Qloo returned.
        ids = [a["entity_id"] for a in res["top_acts"] if a["entity_id"]]
        known = admin.execute(
            "SELECT count(*) FROM qloo_entity WHERE entity_id = ANY(%s)", (ids,)
        ).fetchone()[0]  # type: ignore[index]
        assert known == len(ids)
        assert 0 < res["qloo_calls"] <= 60


async def test_too_few_events_say_not_enough_public_data_yet(
    make_world: Any, admin: psycopg.Connection[Any]
) -> None:
    async with make_world(musicbrainz_url=MB) as world:
        owner = await sign_up(world)
        venue = await make_venue(owner)
        qloo_knows(world, range(0, 30))
        with respx.mock(assert_all_called=False) as router:
            mock_musicbrainz(router, events_body(6, 30))
            await start(owner, venue.business_id)
            await run(world, admin)
        res = (await owner.get(f"/businesses/{venue.business_id}/lineup")).json()["result"]
        assert res["state"] == "insufficient" and "Not enough public data yet" in res["reason"]
        assert res["groups"] is None and res["events"]["used"] == 6


async def test_a_near_name_is_never_taken_for_the_act(
    make_world: Any, admin: psycopg.Connection[Any]
) -> None:
    async with make_world(musicbrainz_url=MB) as world:
        owner = await sign_up(world)
        venue = await make_venue(owner)
        # Qloo's answer to "Act 3" is a different, similar-looking artist with a different MusicBrainz id.
        world.qloo.catalogue = [
            artist(
                "Act 3 Revival",
                entity_id=entity(77),
                mbid=mbid(500),
                tags=[("urn:tag:genre:qloo:x", "X")],
            )
        ]
        with respx.mock(assert_all_called=False) as router:
            mock_musicbrainz(router, events_body(12, 6))
            await start(owner, venue.business_id)
            await run(world, admin)
        res = (await owner.get(f"/businesses/{venue.business_id}/lineup")).json()["result"]
        assert res["performers"]["resolved"] == 0 and res["state"] == "insufficient"


async def test_the_musicbrainz_id_matches_even_when_the_names_differ(
    make_world: Any, admin: psycopg.Connection[Any]
) -> None:
    async with make_world(musicbrainz_url=MB) as world:
        owner = await sign_up(world)
        venue = await make_venue(owner)
        tags = [("urn:tag:genre:qloo:a", "A")]
        world.qloo.catalogue = [
            artist("Act 0", entity_id=entity(0), mbid=mbid(0), tags=tags),
            # The same MusicBrainz artist under a stage name: found by searching "Act 1", matched on the id.
            artist("Act 1 (stage name)", entity_id=entity(1), mbid=mbid(1), tags=tags),
        ]
        with respx.mock(assert_all_called=False) as router:
            mock_musicbrainz(router, events_body(12, 2, per_event=2))
            await start(owner, venue.business_id)
            await run(world, admin)
        res = (await owner.get(f"/businesses/{venue.business_id}/lineup")).json()["result"]
        assert res["performers"]["resolved"] == 2


async def test_enough_events_also_give_groups_of_acts_that_play_together(
    make_world: Any, admin: psycopg.Connection[Any]
) -> None:
    async with make_world(musicbrainz_url=MB) as world:
        owner = await sign_up(world)
        venue = await make_venue(owner)
        # Three scenes of 20 acts: a night always draws its three acts from one scene.
        events = []
        for e in range(150):
            scene = e % 3
            acts = [scene * 20 + (e * 7 + k * 5) % 20 for k in range(3)]
            events.append(
                {
                    "id": str(uuid.UUID(int=e + (0xCD << 100))),
                    "name": f"Night {e}",
                    "life-span": {"begin": f"2024-{1 + e % 12:02d}-10"},
                    "relations": [
                        {"type": "main performer", "artist": {"id": mbid(a), "name": f"Act {a}"}}
                        for a in acts
                    ],
                }
            )
        world.qloo.catalogue = [
            artist(
                f"Act {a}",
                entity_id=entity(a),
                mbid=mbid(a),
                tags=[
                    (f"urn:tag:genre:qloo:scene{a // 20}_{j}", f"Scene {a // 20} sound {j}")
                    for j in (a % 7, (a % 5) + 7, (a % 3) + 12, 20 + a % 4)
                ],
            )
            for a in range(60)
        ]
        with respx.mock(assert_all_called=False) as router:
            mock_musicbrainz(router, {"events": events})
            await start(owner, venue.business_id)
            await run(world, admin)
        res = (await owner.get(f"/businesses/{venue.business_id}/lineup")).json()["result"]
        assert res["state"] == "profile" and res["groups"] is not None
        assert res["groups"]["state"] in ("provisional", "named")
        assert len(res["groups"]["tribes"]) == 3


async def test_the_results_are_cached_so_a_rebuild_does_not_ask_again(
    make_world: Any, admin: psycopg.Connection[Any]
) -> None:
    async with make_world(musicbrainz_url=MB) as world:
        owner = await sign_up(world)
        venue = await make_venue(owner)
        qloo_knows(world, range(0, 40))
        with respx.mock(assert_all_called=False) as router:
            mock_musicbrainz(router, events_body(15, 40))
            await start(owner, venue.business_id)
            await run(world, admin)
            first = router.calls.call_count
            await start(owner, venue.business_id)
            await run(world, admin)
            assert router.calls.call_count == first
        assert (await owner.get(f"/businesses/{venue.business_id}/lineup")).json()[
            "status"
        ] == "ready"


async def test_the_qloo_calls_are_capped_and_the_rest_reported_unresolved(
    make_world: Any, admin: psycopg.Connection[Any]
) -> None:
    async with make_world(musicbrainz_url=MB) as world:
        owner = await sign_up(world)
        venue = await make_venue(owner)
        qloo_knows(world, range(0, 150))
        with respx.mock(assert_all_called=False) as router:
            mock_musicbrainz(router, events_body(75, 150, per_event=4))
            await start(owner, venue.business_id)
            await run(world, admin)
        res = (await owner.get(f"/businesses/{venue.business_id}/lineup")).json()["result"]
        assert res["qloo_calls"] <= 60
        assert res["performers"]["unique"] == 150 and res["performers"]["resolved"] <= 60


async def test_musicbrainz_being_down_fails_the_job_and_says_why(
    make_world: Any, admin: psycopg.Connection[Any]
) -> None:
    async with make_world(musicbrainz_url=MB) as world:
        owner = await sign_up(world)
        venue = await make_venue(owner)
        with respx.mock(assert_all_called=False) as router:
            router.get(f"{MB}/event").mock(return_value=httpx.Response(500))
            await start(owner, venue.business_id)
            await run(world, admin)
        got = (await owner.get(f"/businesses/{venue.business_id}/lineup")).json()
        assert got["status"] == "failed" and "500" in got["error"]
        row = admin.execute(
            "SELECT state, attempts FROM job WHERE kind = 'build_lineup'"
        ).fetchone()
        assert row == ("pending", 1)  # retried later


async def test_a_busy_musicbrainz_is_waited_for_not_given_up_on(
    make_world: Any, admin: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def no_sleep(_s: float) -> None:
        return None

    # Only this module's waits are skipped; the rest of the process keeps its real clock.
    monkeypatch.setattr(lineup, "asyncio", SimpleNamespace(sleep=no_sleep, Lock=asyncio.Lock))
    async with make_world(musicbrainz_url=MB) as world:
        owner = await sign_up(world)
        venue = await make_venue(owner)
        qloo_knows(world, range(0, 40))
        with respx.mock(assert_all_called=False) as router:
            router.get(f"{MB}/event").mock(
                side_effect=[
                    httpx.Response(503),
                    httpx.Response(429),
                    httpx.Response(200, json=events_body(15, 40)),
                ]
            )
            await start(owner, venue.business_id)
            await run(world, admin)
        assert (await owner.get(f"/businesses/{venue.business_id}/lineup")).json()[
            "status"
        ] == "ready"


async def test_roles_tenants_and_junk(make_world: Any, admin: psycopg.Connection[Any]) -> None:
    async with make_world(musicbrainz_url=MB) as world:
        owner = await sign_up(world)
        other = await sign_up(world)
        viewer = await sign_up(world)
        venue = await make_venue(owner)
        admin.execute(
            "INSERT INTO membership (tenant_id, user_id, role) VALUES (%s, %s, 'viewer')",
            (owner.tenant_id, viewer.me["user_id"]),
        )
        base = f"/v1/tenants/{owner.tenant_id}/businesses/{venue.business_id}/lineup"
        body = {"mbid": PLACE, "name": "x"}
        assert (
            await viewer.client.post(base, headers=viewer.headers, json=body)
        ).status_code == 403
        assert (await other.client.post(base, headers=other.headers, json=body)).status_code == 404
        assert (await other.client.get(base)).status_code == 404
        for junk in (
            {},
            {"mbid": "not-a-uuid", "name": "x"},
            {"mbid": PLACE, "name": ""},
            {"mbid": PLACE, "name": "x", "extra": 1},
        ):
            assert (
                await owner.client.post(base, headers=owner.headers, json=junk)
            ).status_code == 422, junk
        assert (await viewer.client.get(base)).json() is None
        ok = await owner.client.post(
            base, headers=owner.headers, json={"mbid": PLACE, "name": "Mercury Lounge"}
        )
        assert ok.status_code == 202
        assert (await viewer.client.delete(base, headers=viewer.headers)).status_code == 403
        assert (await owner.client.delete(base, headers=owner.headers)).status_code == 204
        assert (await owner.client.get(base)).json() is None
