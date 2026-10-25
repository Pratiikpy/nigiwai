"""The crowd map data: pins, group mix, catchment hexes, what is around, the timeline, and above all the rule that nothing
about fewer than ten guests leaves the server. Qloo and Nominatim are scripted; every name is invented."""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
import psycopg
import pytest
from harness import World, make_venue, sign_up
from nigiwai_api.services.geocode import Geocoder, normalise_district
from test_brief import ready_brief
from test_soundcheck import base, crowd


@pytest.fixture(autouse=True)
def fast_geocoder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        Geocoder, "INTERVAL", 0.0
    )  # the policy's one-a-second wait is not what is under test


class Nominatim:
    """Stands in for nominatim.openstreetmap.org: knows a few districts, records every question."""

    def __init__(self, known: dict[str, tuple[float, float]], *, down: bool = False) -> None:
        self.known = {normalise_district(k): v for k, v in known.items()}
        self.asked: list[dict[str, str]] = []
        self.down = down

    def install(self, world: World) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.asked.append(
                {**dict(request.url.params), "agent": request.headers.get("user-agent", "")}
            )
            if self.down:
                return httpx.Response(503, text="busy")
            hit = self.known.get(normalise_district(request.url.params["q"]))
            if hit is None:
                return httpx.Response(200, json=[])
            return httpx.Response(
                200,
                json=[
                    {
                        "lat": str(hit[0]),
                        "lon": str(hit[1]),
                        "name": request.url.params["q"],
                        "display_name": "x",
                    }
                ],
            )

        state = world.app.state.nigiwai
        state.geocoder = Geocoder(
            state.engine,
            "http://nominatim.test",
            "tests",
            httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )


async def second_location(owner: Any, venue: Any) -> tuple[str, str]:
    loc = await owner.post(
        f"/businesses/{venue.business_id}/locations",
        json={"name": "Garden", "lat": 51.52, "lon": -0.1, "timezone": "Europe/London"},
    )
    assert loc.status_code == 201, loc.text
    qr = await owner.post(f"/locations/{loc.json()['id']}/qr-points", json={"label": "Patio"})
    assert qr.status_code == 201, qr.text
    return loc.json()["id"], qr.json()["id"]


def add_responses(
    admin: psycopg.Connection[Any],
    venue: Any,
    qr_id: str,
    ids: list[str],
    n: int,
    *,
    district: str | None = None,
) -> None:
    survey = admin.execute(
        "SELECT id, version FROM survey WHERE business_id = %s AND status = 'published'",
        (venue.business_id,),
    ).fetchone()
    assert survey is not None
    artists = [i for i, e in enumerate(ids) if i % 3 == 0]
    for k in range(n):
        picks = [ids[artists[(k + j) % len(artists)]] for j in range(3)]
        admin.execute(
            "SELECT public_insert_response(%s, %s, %s, 'v1', NULL, %s, NULL, 'ok', %s, %s, %s)",
            (
                qr_id,
                survey[0],
                survey[1],
                district,
                picks,
                ["urn:entity:artist"] * 3,
                uuid.uuid4().bytes,
            ),
        )


async def get_map(owner: Any, venue: Any, period: str = "all") -> Any:
    return await owner.get(f"{base(owner, venue)}/map", params={"period": period})


async def test_a_venue_with_no_guests_is_a_pin_and_what_is_around_it(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    doc = (await get_map(owner, venue)).json()
    assert doc["business"] == "The Lantern" and doc["grouping"]["state"] == "none"
    [pin] = doc["locations"]
    assert (
        pin["name"] == "Main room"
        and pin["scans"] is None
        and pin["hidden"] is True
        and pin["mix"] == []
    )
    assert doc["groups"] == [] and doc["catchment"] == [] and doc["timeline"]["total"] == 0
    assert "around" not in doc  # the map never waits for Qloo: what is around comes separately
    around = (await owner.get(f"{base(owner, venue)}/map/around")).json()
    assert around["status"] == "ok" and len(around["places"]) == 3
    assert all({"name", "lat", "lon", "distance_m"} <= set(p) for p in around["places"])
    assert any(c["endpoint"] == "/v2/insights" and c["purpose"] == "board" for c in around["calls"])


async def test_a_place_under_ten_guests_is_a_pin_with_no_figures_and_the_rest_show_their_mix(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    ids = await crowd(world, admin, owner, venue)  # 90 guests at the first location
    loc_b, qr_b = await second_location(owner, venue)
    add_responses(admin, venue, qr_b, ids, 7)  # only seven at the second
    doc = (await get_map(owner, venue)).json()
    assert doc["grouping"]["state"] in ("provisional", "named") and len(doc["groups"]) == 3
    by_name = {p["name"]: p for p in doc["locations"]}
    main, garden = by_name["Main room"], by_name["Garden"]
    assert main["scans"] == 90 and main["hidden"] is False
    assert main["mix"] and sum(m["share"] for m in main["mix"]) == pytest.approx(1.0, abs=0.02)
    assert [q["label"] for q in main["qr_points"]] == ["Bar end"] and main["qr_points"][0][
        "scans"
    ] == 90
    # seven guests: the pin exists, and nothing else about it is sent
    assert (
        garden["scans"] is None
        and garden["hidden"] is True
        and garden["mix"] == []
        and garden["qr_points"] == []
    )
    assert garden.keys() == {
        "id",
        "name",
        "address",
        "lat",
        "lon",
        "radius_m",
        "scans",
        "hidden",
        "mix",
        "qr_points",
    }


async def test_the_period_narrows_the_scans_and_the_timeline(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    await crowd(world, admin, owner, venue)
    admin.execute(
        "UPDATE response SET local_date = current_date - 90 WHERE id IN (SELECT id FROM response LIMIT 50)"
    )
    everything = (await get_map(owner, venue, "all")).json()
    recent = (await get_map(owner, venue, "4w")).json()
    assert everything["locations"][0]["scans"] == 90 and recent["locations"][0]["scans"] == 40
    assert recent["timeline"]["unit"] == "week" and everything["timeline"]["total"] == 90
    assert sum(b["scans"] for b in recent["timeline"]["buckets"]) == 40
    week = (await get_map(owner, venue, "7d")).json()
    assert week["timeline"]["unit"] == "day"
    assert (await get_map(owner, venue, "forever")).status_code == 422


async def test_districts_become_hexes_only_from_ten_guests_and_smaller_ones_are_only_counted(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    ids = await crowd(world, admin, owner, venue)
    nominatim = Nominatim({"Hackney": (51.545, -0.055), "Peckham": (51.47, -0.07)})
    nominatim.install(world)
    # 30 name Hackney in three spellings, 6 name Peckham, 12 name a place Nominatim does not know.
    rows = [r[0] for r in admin.execute("SELECT id FROM response ORDER BY id").fetchall()]
    for rid, name in zip(
        rows[:30], ["Hackney"] * 10 + ["hackney "] * 10 + ["HACKNEY"] * 10, strict=True
    ):
        admin.execute("UPDATE response SET district = %s WHERE id = %s", (name, rid))
    for rid in rows[30:36]:
        admin.execute("UPDATE response SET district = 'Peckham' WHERE id = %s", (rid,))
    for rid in rows[36:48]:
        admin.execute("UPDATE response SET district = 'Atlantis' WHERE id = %s", (rid,))
    assert ids  # a crowd exists, so groups exist

    doc = (await get_map(owner, venue)).json()
    [hexcell] = doc["catchment"]
    assert (hexcell["guests"] == 30 and hexcell["districts"] == ["Hackney"]) or hexcell[
        "districts"
    ] == ["hackney "]
    assert (
        len(hexcell["boundary"]) == 6 and hexcell["main_label"]
    )  # a hexagon, coloured by its main group
    assert doc["catchment_hidden"] == {"districts": 1, "guests": 6}
    assert doc["catchment_pending"] == 0
    asked = sorted(a["q"].strip().lower() for a in nominatim.asked)
    assert asked == [
        "atlantis",
        "hackney",
    ]  # Peckham (six guests) was never looked up, and Hackney once, not three times
    assert all(
        a["bounded"] == "1" and "viewbox" in a and a["agent"].startswith("Nigiwai/0.1")
        for a in nominatim.asked
    )
    blob = json.dumps(doc)
    assert (
        "Peckham" not in blob and "Atlantis" not in blob
    )  # a district under ten, or unknown to the map, is not named

    again = (await get_map(owner, venue)).json()
    assert (
        again["catchment"] == doc["catchment"] and len(nominatim.asked) == 2
    )  # cached: no second question


async def test_when_the_place_finder_is_down_nothing_is_guessed_and_the_map_says_it_is_still_locating(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    await crowd(world, admin, owner, venue)
    admin.execute(
        "UPDATE response SET district = 'Hackney' WHERE id IN (SELECT id FROM response LIMIT 20)"
    )
    down = Nominatim({}, down=True)
    down.install(world)
    doc = (await get_map(owner, venue)).json()
    assert doc["catchment"] == [] and doc["catchment_pending"] == 1  # asked, failed, nothing cached
    up = Nominatim({"Hackney": (51.545, -0.055)})
    up.install(world)
    healed = (await get_map(owner, venue)).json()
    assert len(healed["catchment"]) == 1 and healed["catchment_pending"] == 0


async def test_at_most_three_districts_are_looked_up_per_request(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    await crowd(world, admin, owner, venue)
    names = ["North Hill", "South Hill", "East Hill", "West Hill", "Mid Hill"]
    rows = [r[0] for r in admin.execute("SELECT id FROM response ORDER BY id").fetchall()]
    for i, name in enumerate(names):
        for rid in rows[i * 12 : (i + 1) * 12]:
            admin.execute("UPDATE response SET district = %s WHERE id = %s", (name, rid))
    nominatim = Nominatim({n: (51.5 + 0.02 * i, -0.12 + 0.02 * i) for i, n in enumerate(names)})
    nominatim.install(world)
    first = (await get_map(owner, venue)).json()
    assert (
        len(nominatim.asked) == 3
        and len(first["catchment"]) == 3
        and first["catchment_pending"] == 2
    )
    second = (await get_map(owner, venue)).json()
    assert (
        len(second["catchment"]) == 5
        and second["catchment_pending"] == 0
        and len(nominatim.asked) == 5
    )


async def test_a_qloo_outage_leaves_the_map_and_says_around_you_is_unavailable(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    world.qloo.down = True
    doc = (await get_map(owner, venue)).json()
    assert len(doc["locations"]) == 1  # the pin and the rest of the map do not depend on Qloo
    around = (await owner.get(f"{base(owner, venue)}/map/around")).json()
    assert around["status"] == "unavailable" and around["places"] == []


async def test_the_map_belongs_to_its_account(world: World, admin: psycopg.Connection[Any]) -> None:
    owner = await sign_up(world)
    other = await sign_up(world)
    venue = await make_venue(owner)
    theirs = f"/v1/tenants/{owner.tenant_id}/businesses/{venue.business_id}/map"
    assert (await other.client.get(theirs)).status_code == 404
    assert (await world.client().get(theirs)).status_code == 401
    assert (await owner.get(f"/businesses/{uuid.uuid4()}/map")).status_code == 404
    assert (await other.client.get(f"{theirs}/around")).status_code == 404
    assert (await owner.get(f"/businesses/{uuid.uuid4()}/map/around")).status_code == 404


def test_district_names_are_counted_without_case_accents_or_spacing() -> None:
    assert normalise_district("  Hackney ") == normalise_district("HACKNEY") == "hackney"
    assert normalise_district("Saint-Denis") == normalise_district("saint  denis") == "saint denis"
    assert normalise_district("Zürich") == "zurich"


async def test_the_map_carries_a_gap_candidate_and_the_moves_only_when_they_are_real(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    """Gaps come from the last Grow run, only while it belongs to the groups as they are, and only for groups the run itself found
    without a place of their own. Moves are the owner's own flags. Nothing is asked of Qloo to draw either."""
    from test_today import plant_ghost_run

    owner = await sign_up(world)
    venue = await make_venue(owner)
    await ready_brief(world, admin, owner, venue)
    root = f"/v1/tenants/{owner.tenant_id}/businesses/{venue.business_id}"
    doc = (await owner.client.get(f"{root}/map")).json()
    assert doc["gaps"] is None and doc["moves"] == []
    made = await owner.client.post(
        f"{root}/moves",
        headers=owner.headers,
        json={"kind": "act", "title": "Booked a band", "started_on": "2026-10-02"},
    )
    assert made.status_code == 201, made.text
    doc = (await owner.client.get(f"{root}/map")).json()
    assert [(m["title"], m["started_on"], m["ended_on"]) for m in doc["moves"]] == [
        ("Booked a band", "2026-10-02", None)
    ]
    # a run whose places were told apart, with one group that has none of its own
    await plant_ghost_run(world, admin, owner, venue)
    run = admin.execute("SELECT result FROM grow_run").fetchone()[0]  # type: ignore[index]
    run["places"] = {
        "status": "ok",
        "category": "bar",
        "radius_m": 900,
        "wide_radius_m": 4000,
        "nearby": {
            "told_apart": True,
            "by_group": [],
            "gaps": [{"group_index": 1, "group": "Group B"}],
        },
        "elsewhere": {},
        "dropped_closed": 0,
        "closure_unanswered": False,
    }
    admin.execute("UPDATE grow_run SET result = %s::jsonb", (json.dumps(run),))
    calls_before = len(world.qloo.calls)
    doc = (await owner.client.get(f"{root}/map")).json()
    assert doc["gaps"]["groups"] == [{"index": 1, "label": "Group B"}]
    assert doc["gaps"]["radius_m"] == 900 and doc["gaps"]["category"] == "bar"
    assert (doc["gaps"]["lat"], doc["gaps"]["lon"]) == (51.5, -0.12)
    assert len(world.qloo.calls) == calls_before  # drawn from stored rows
    # a run made for older groups, a run that never told the groups apart, or one with no gap: no gap is drawn
    admin.execute("UPDATE grow_run SET basis_ref = 'older'")
    assert (await owner.client.get(f"{root}/map")).json()["gaps"] is None
    admin.execute("UPDATE grow_run SET basis_ref = %s", (run["basis"]["ref"],))
    run["places"]["nearby"]["gaps"] = []
    admin.execute("UPDATE grow_run SET result = %s::jsonb", (json.dumps(run),))
    assert (await owner.client.get(f"{root}/map")).json()["gaps"] is None
