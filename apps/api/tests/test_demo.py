"""Judge mode: the demo venues are built from public lineups and Qloo, shown to anyone without an account, and cannot
reach or change anything else. MusicBrainz is mocked at the network edge, Qloo is scripted, and every name is invented."""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from typing import Any

import httpx
import psycopg
import pypdfium2 as pdfium
import pytest
import respx
from fakeqloo import artist
from harness import World, sign_up
from nigiwai_api import demo as demo_cli
from nigiwai_api import worker
from nigiwai_api.routers import demo as demo_router
from nigiwai_api.services import demo as demo_service
from nigiwai_api.services import lineup
from nigiwai_api.services import soundcheck as sc
from nigiwai_api.services.lineup import MusicBrainz
from test_lineup import MB, PLACE, entity, events_body, mbid
from test_soundcheck import add_artist, plant_lineup

DEMO = demo_service.DEMO_TENANT_ID
SPEC = demo_service.SPECS[0]  # Mercury Lounge, New York
API = "/v1/public/demo"


@pytest.fixture(autouse=True)
def fast_musicbrainz(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(MusicBrainz, "INTERVAL", 0.0)


def mock_place(
    router: respx.MockRouter,
    *,
    area: str = "New York",
    city: str = "New York",
    coordinates: bool = True,
) -> None:
    here: dict[str, Any] = {
        "id": PLACE,
        "name": "Mercury Lounge",
        "type": "Venue",
        "address": f"217 East Houston St., {city}, NY 10002",
        "area": {"name": area},
    }
    if coordinates:
        here["coordinates"] = {"latitude": "40.7222", "longitude": "-73.9871"}
    decoy = {
        "id": mbid(999),
        "name": "Mercury Lounge",
        "area": {"name": "Austin"},
        "coordinates": {"latitude": "30.26", "longitude": "-97.74"},
    }
    router.get(f"{MB}/place").mock(return_value=httpx.Response(200, json={"places": [decoy, here]}))


def three_scenes(world: World, acts: range) -> None:
    """Acts Qloo resolves by name, in three clearly different scenes, each scripted as its own group."""
    world.qloo.catalogue = [
        artist(
            f"Act {a}",
            entity_id=entity(a),
            mbid=mbid(a),
            tags=[
                (f"urn:tag:genre:qloo:g{a % 3}", f"Genre {a % 3}"),
                (f"urn:tag:genre:qloo:s{a % 3}", f"Style {a % 3}"),
                (f"urn:tag:genre:qloo:m{a % 3}", f"Mood {a % 3}"),
            ],
        )
        for a in acts
    ]
    for a in acts:
        world.qloo.group_of[entity(a)] = a % 3


def neighbours(admin: psycopg.Connection[Any], world: World) -> None:
    for g in range(3):
        for i in range(9):
            add_artist(admin, world, f"Neighbour {g}-{i}", g, popularity=0.05 + 0.1 * i)


def state_of(world: World) -> Any:
    return world.app.state.nigiwai


async def build(world: World, spec: demo_service.Spec = SPEC) -> dict[str, Any]:
    st = state_of(world)
    return await demo_service.build_venue(
        st.engine, st.guard, st.musicbrainz, st.llm, st.limiter, 100, spec
    )


def plant_demo(
    admin: psycopg.Connection[Any],
    world: World,
    *,
    slug: str = "mercury-lounge",
    status: str = "ready",
) -> uuid.UUID:
    """A demo venue as a build leaves it, planted directly: a located business under the demo tenant with a ready lineup
    profile of three scenes and a row in the demo list. Suggestions are built separately (see `suggest`)."""
    business_id = uuid.uuid4()
    admin.execute(
        "INSERT INTO business (id, tenant_id, name, type) VALUES (%s, %s, 'Mercury Test Room', 'live_music_venue')",
        (business_id, DEMO),
    )
    admin.execute(
        "INSERT INTO location (tenant_id, business_id, name, geom, timezone, radius_m)"
        " VALUES (%s, %s, 'Mercury Test Room', ST_SetSRID(ST_MakePoint(-73.9871, 40.7222), 4326)::geography,"
        " 'America/New_York', 800)",
        (DEMO, business_id),
    )
    plant_lineup(
        admin,
        world,
        SimpleNamespace(tenant_id=str(DEMO)),
        SimpleNamespace(business_id=str(business_id)),
    )
    admin.execute(
        "INSERT INTO demo_venue (slug, name, city, blurb, business_id, status, summary, refreshed_at)"
        " VALUES (%s, 'Mercury Test Room', 'New York', 'An invented room.', %s, %s, %s::jsonb, now())",
        (slug, business_id, status, json.dumps({"events": 40})),
    )
    return business_id


async def suggest(admin: psycopg.Connection[Any], world: World, business_id: uuid.UUID) -> None:
    neighbours(admin, world)
    st = state_of(world)
    await sc.run_suggest_job(st.engine, st.guard, DEMO, business_id)
    got = await sc.suggestions(st.engine, DEMO, business_id)
    assert got is not None and got["status"] == "ready", got


def business_of(admin: psycopg.Connection[Any], slug: str = SPEC.slug) -> Any:
    row = admin.execute("SELECT business_id FROM demo_venue WHERE slug = %s", (slug,)).fetchone()
    assert row is not None
    return row[0]


def strings(value: Any) -> str:
    return json.dumps(value)


# ---------------------------------------------------------------------------------------------------- building
async def test_a_demo_venue_is_built_end_to_end_from_public_lineups(
    make_world: Any, admin: psycopg.Connection[Any]
) -> None:
    async with make_world(musicbrainz_url=MB) as world:
        three_scenes(world, range(30))
        neighbours(admin, world)
        with respx.mock(assert_all_called=False) as router:
            mock_place(router)
            router.get(f"{MB}/event").mock(
                return_value=httpx.Response(200, json=events_body(30, 30))
            )
            summary = await build(world)

        assert summary["place"] == "Mercury Lounge" and summary["area"] == "New York"
        assert summary["events"] == 30 and summary["acts_matched"] == 30
        assert 1 <= len(summary["top"]) <= 3
        row = admin.execute(
            "SELECT status, error, refreshed_at IS NOT NULL, tenant_id FROM demo_venue WHERE slug = %s",
            (SPEC.slug,),
        ).fetchone()
        assert row == ("ready", None, True, DEMO)
        # the venue is a real located business under the demo tenant, positioned from the place, not from a guess
        located = admin.execute(
            "SELECT b.type, b.tenant_id, round(ST_Y(l.geom::geometry)::numeric, 4)::float8,"
            " round(ST_X(l.geom::geometry)::numeric, 4)::float8, l.timezone"
            " FROM business b JOIN location l ON l.business_id = b.id"
        ).fetchall()
        assert located == [("live_music_venue", DEMO, 40.7222, -73.9871, "America/New_York")]
        # the Austin place with the same name was not taken
        assert admin.execute("SELECT place_mbid FROM lineup_profile").fetchall() == [(PLACE,)]
        # what a first view needs is stored: suggestions, and a comparison for every suggested act
        shown = len(summary["top"]) + (1 if summary["wildcard"] else 0)
        assert admin.execute("SELECT count(*) FROM soundcheck_comparison").fetchone() == (shown,)
        listed = (await world.client().get(API)).json()
        assert [v["slug"] for v in listed] == [SPEC.slug]
        assert listed[0]["summary"]["top"] == summary["top"]

        # building again changes nothing structural: still one venue, one business, one row
        with respx.mock(assert_all_called=False) as router:
            mock_place(router)
            router.get(f"{MB}/event").mock(
                return_value=httpx.Response(200, json=events_body(30, 30))
            )
            await build(world)
        assert admin.execute("SELECT count(*) FROM demo_venue").fetchone() == (1,)
        assert admin.execute("SELECT count(*) FROM business").fetchone() == (1,)


async def test_the_city_may_be_in_the_address_rather_than_the_area_name(
    make_world: Any, admin: psycopg.Connection[Any]
) -> None:
    # The real MusicBrainz record for Mercury Lounge has the area "Lower East Side" and the city only in its address.
    async with make_world(musicbrainz_url=MB) as world:
        with respx.mock(assert_all_called=False) as router:
            mock_place(router, area="Lower East Side")
            st = state_of(world)
            found = await demo_service.find_place(st.musicbrainz, SPEC)
        assert found.mbid == PLACE and found.lat == pytest.approx(40.7222)


async def test_a_place_with_an_impossible_position_is_never_chosen(make_world: Any) -> None:
    # MusicBrainz is hand-edited and holds a Mercury Lounge whose longitude is -457.
    async with make_world(musicbrainz_url=MB) as world:
        bad = {
            "id": mbid(998),
            "name": "Mercury Lounge",
            "area": {"name": "New York"},
            "address": "Nowhere, New York",
            "coordinates": {"latitude": "30.267644", "longitude": "-457.740759"},
        }
        good = {
            "id": PLACE,
            "name": "Mercury Lounge",
            "area": {"name": "Lower East Side"},
            "address": "217 East Houston St., New York, NY 10002",
            "coordinates": {"latitude": "40.721998", "longitude": "-73.986842"},
        }
        with respx.mock(assert_all_called=False) as router:
            router.get(f"{MB}/place").mock(
                return_value=httpx.Response(200, json={"places": [bad, good]})
            )
            st = state_of(world)
            assert (await st.musicbrainz.search_places("Mercury Lounge"))[0].lat is None
            assert (await demo_service.find_place(st.musicbrainz, SPEC)).mbid == PLACE


async def test_a_place_that_cannot_be_placed_is_refused_and_leaves_nothing_behind(
    make_world: Any, admin: psycopg.Connection[Any]
) -> None:
    async with make_world(musicbrainz_url=MB) as world:
        for kwargs in ({"area": "Austin", "city": "Austin"}, {"coordinates": False}):
            with respx.mock(assert_all_called=False) as router:
                mock_place(router, **kwargs)
                with pytest.raises(demo_service.DemoError, match="no place called Mercury Lounge"):
                    await build(world)
        assert admin.execute("SELECT count(*) FROM demo_venue").fetchone() == (0,)
        assert admin.execute("SELECT count(*) FROM business").fetchone() == (0,)


async def test_a_lineup_too_thin_to_build_from_marks_the_venue_failed_and_hides_it(
    make_world: Any, admin: psycopg.Connection[Any]
) -> None:
    async with make_world(musicbrainz_url=MB) as world:
        three_scenes(world, range(30))
        with respx.mock(assert_all_called=False) as router:
            mock_place(router)
            router.get(f"{MB}/event").mock(
                return_value=httpx.Response(200, json=events_body(4, 30))
            )
            with pytest.raises(demo_service.DemoError, match="Not enough public data"):
                await build(world)
        status, error = admin.execute("SELECT status, error FROM demo_venue").fetchone()  # type: ignore[misc]
        assert status == "failed" and "Not enough public data" in error
        anon = world.client()
        assert (await anon.get(API)).json() == []
        res = await anon.get(f"{API}/{SPEC.slug}")
        assert res.status_code == 503 and "not available right now" in res.json()["detail"]


async def test_without_qloo_nothing_is_built(
    make_world: Any, admin: psycopg.Connection[Any]
) -> None:
    async with make_world(with_qloo=False) as world:
        with pytest.raises(demo_service.DemoError, match="Qloo is not configured"):
            await build(world)


async def test_a_failed_rebuild_keeps_what_the_venue_showed_and_says_why(
    make_world: Any, admin: psycopg.Connection[Any]
) -> None:
    async with make_world(musicbrainz_url=MB) as world:
        three_scenes(world, range(30))
        neighbours(admin, world)
        with respx.mock(assert_all_called=False) as router:
            mock_place(router)
            router.get(f"{MB}/event").mock(
                return_value=httpx.Response(200, json=events_body(30, 30))
            )
            first = await build(world)
        before = admin.execute(
            "SELECT p.result, g.result FROM lineup_profile p, act_suggestion g"
        ).fetchone()

        admin.execute("DELETE FROM external_cache")  # force the next build to ask MusicBrainz again
        with respx.mock(assert_all_called=False) as router:
            router.get(f"{MB}/event").mock(return_value=httpx.Response(500))
            with pytest.raises(lineup.LineupError):
                await build(world)

        status, error = admin.execute("SELECT status, error FROM demo_venue").fetchone()  # type: ignore[misc]
        assert status == "ready" and "LineupError" in error and "500" in error
        after = admin.execute(
            "SELECT p.result, g.result FROM lineup_profile p, act_suggestion g"
        ).fetchone()
        assert after == before  # the lineup and the suggestions are exactly what they were
        anon = world.client()
        assert (await anon.get(f"{API}/{SPEC.slug}/suggestions")).json()["status"] == "ready"
        basis = (await anon.get(f"{API}/{SPEC.slug}/soundcheck/basis")).json()
        assert basis["use"] == "lineup"
        assert [v["slug"] for v in (await anon.get(API)).json()] == [SPEC.slug]

        # and the next good build clears the error
        with respx.mock(assert_all_called=False) as router:
            router.get(f"{MB}/event").mock(
                return_value=httpx.Response(200, json=events_body(30, 30))
            )
            again = await build(world)
        assert again["top"] == first["top"]
        assert admin.execute("SELECT error FROM demo_venue").fetchone() == (None,)


async def test_old_checks_are_dropped_on_a_rebuild_and_recent_ones_kept(
    make_world: Any, admin: psycopg.Connection[Any]
) -> None:
    async with make_world(musicbrainz_url=MB) as world:
        three_scenes(world, range(30))
        neighbours(admin, world)
        with respx.mock(assert_all_called=False) as router:
            mock_place(router)
            router.get(f"{MB}/event").mock(
                return_value=httpx.Response(200, json=events_body(30, 30))
            )
            await build(world)
            st = state_of(world)
            built = await sc.suggestions(st.engine, DEMO, uuid.UUID(str(business_of(admin))))
            assert built is not None
            suggested = [t["soundcheck_id"] for t in built["result"]["top"]]
            # a visitor's own check, and one of the suggested checks, both a month old
            visitor = add_artist(admin, world, "Newcomer", 1)
            own = (
                await world.client().post(
                    f"{API}/{SPEC.slug}/soundcheck", json={"entity_id": visitor}
                )
            ).json()["id"]
            admin.execute(
                "UPDATE soundcheck SET created_at = now() - interval '30 days' WHERE id = ANY(%s::uuid[])",
                ([own, suggested[0]],),
            )
            await build(world)
        # the visitor's old check is dropped; the suggested one is kept even though it is older than the window,
        # because the rebuilt suggestions still point at it
        assert admin.execute(
            "SELECT count(*) FROM soundcheck WHERE id = %s", (own,)
        ).fetchone() == (0,)
        after = await sc.suggestions(st.engine, DEMO, uuid.UUID(str(business_of(admin))))
        assert after is not None
        for s in [*after["result"]["top"], after["result"]["wildcard"]]:
            if s:
                assert admin.execute(
                    "SELECT count(*) FROM soundcheck WHERE id = %s", (s["soundcheck_id"],)
                ).fetchone() == (1,), s["name"]
        assert admin.execute(
            "SELECT count(*) FROM soundcheck WHERE id = %s", (suggested[0],)
        ).fetchone() == (1,)


# ---------------------------------------------------------------------------------------------------- the public routes
async def test_anyone_can_open_a_ready_demo_venue_and_nothing_in_it_names_the_tenant(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    business_id = plant_demo(admin, world)
    await suggest(admin, world, business_id)
    anon = world.client()  # no account, no cookie
    seen: dict[str, Any] = {}
    for name, path in {
        "venue": f"{API}/{SPEC.slug}",
        "basis": f"{API}/{SPEC.slug}/soundcheck/basis",
        "suggestions": f"{API}/{SPEC.slug}/suggestions",
        "recent": f"{API}/{SPEC.slug}/soundchecks",
        "map": f"{API}/{SPEC.slug}/map",
        "around": f"{API}/{SPEC.slug}/map/around",
        "brief": f"{API}/{SPEC.slug}/brief",
    }.items():
        res = await anon.get(path)
        assert res.status_code == 200, (name, res.text)
        seen[name] = res.json()
    # neither id of the underlying venue appears in anything a visitor receives
    blob = strings(seen)
    assert str(DEMO) not in blob and str(business_id) not in blob

    assert seen["venue"]["name"] == "Mercury Test Room" and seen["venue"]["city"] == "New York"
    assert set(seen["venue"]) == {"slug", "name", "city", "blurb", "summary", "refreshed_at"}
    assert seen["basis"]["use"] == "lineup" and seen["basis"]["lineup"]["sufficient"]
    result = seen["suggestions"]["result"]
    assert seen["suggestions"]["status"] == "ready" and len(result["top"]) == 3
    # the checks the demo was built with are listed, in the same order and with the same scores
    acts = [*result["top"], *([result["wildcard"]] if result["wildcard"] else [])]
    assert [r["id"] for r in seen["recent"]] == [a["soundcheck_id"] for a in acts]
    assert [r["score"] for r in seen["recent"]] == [a["score"] for a in acts]
    # Qloo's popularity figure is never sent
    assert "popularity" not in strings(seen["suggestions"])
    assert seen["brief"]["status"] == "ok" and seen["map"]["business"] == "Mercury Test Room"


async def test_a_visitor_sees_a_full_verdict_its_calls_and_the_comparison_without_qloos_descriptive_fields(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    business_id = plant_demo(admin, world)
    await suggest(admin, world, business_id)
    anon = world.client()
    top = (await anon.get(f"{API}/{SPEC.slug}/soundchecks")).json()[0]
    verdict = await anon.get(f"{API}/{SPEC.slug}/soundchecks/{top['id']}")
    assert verdict.status_code == 200
    doc = verdict.json()
    assert doc["status"] == "ok" and doc["score"] == top["score"] and doc["groups"]
    assert "description" not in doc["candidate"] and "popularity" not in doc["candidate"]
    assert doc["candidate"]["name"] == top["name"]

    calls = await anon.get(f"{API}/{SPEC.slug}/soundchecks/{top['id']}/calls")
    assert calls.status_code == 200 and calls.json() and all("endpoint" in c for c in calls.json())

    before = len(world.qloo.calls)
    first = await anon.get(f"{API}/{SPEC.slug}/soundchecks/{top['id']}/compare")
    assert first.status_code == 200
    body = first.json()
    assert body["qloo"]["available"] is True and body["qloo"]["items"]
    assert body["ai"]["available"] is False and "no AI service" in body["ai"]["reason"]
    spent = len(world.qloo.calls) - before
    again = await anon.get(f"{API}/{SPEC.slug}/soundchecks/{top['id']}/compare")
    assert (
        again.json() == body and len(world.qloo.calls) - before == spent
    )  # stored: the second look costs nothing


async def test_the_demo_brief_downloads_as_a_pdf_without_an_account(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    business_id = plant_demo(admin, world)
    await suggest(admin, world, business_id)
    anon = world.client()
    pdf = await anon.get(f"{API}/{SPEC.slug}/brief.pdf")
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
    assert pdf.headers["content-disposition"].startswith(
        'attachment; filename="booking-brief-mercury-test-room-'
    )
    assert pdf.headers["x-content-type-options"] == "nosniff"
    doc = pdfium.PdfDocument(pdf.content)
    assert len(doc) == 1
    text = " ".join(doc[0].get_textpage().get_text_range().split())
    assert "Mercury Test Room".upper() in text.upper() and "Three acts to consider" in text


async def test_a_visitor_can_check_any_act_and_the_check_is_stored_but_not_listed(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    business_id = plant_demo(admin, world)
    await suggest(admin, world, business_id)
    anon = world.client()
    cand = add_artist(admin, world, "Newcomer", 1)
    listed_before = (await anon.get(f"{API}/{SPEC.slug}/soundchecks")).json()

    res = await anon.post(f"{API}/{SPEC.slug}/soundcheck", json={"entity_id": cand})
    assert res.status_code == 200, res.text
    doc = res.json()
    assert doc["status"] == "ok" and doc["provisional"] is True and doc["basis"]["kind"] == "lineup"
    assert "description" not in doc["candidate"] and "popularity" not in doc["candidate"]
    assert str(DEMO) not in strings(doc) and str(business_id) not in strings(doc)
    # it can be opened again by its id, and it does not push the built-in checks out of the list
    assert (await anon.get(f"{API}/{SPEC.slug}/soundchecks/{doc['id']}")).json()["id"] == doc["id"]
    assert (await anon.get(f"{API}/{SPEC.slug}/soundchecks")).json() == listed_before

    # the same act again returns the stored verdict and makes no new Qloo call
    before = len(world.qloo.calls)
    same = await anon.post(f"{API}/{SPEC.slug}/soundcheck", json={"entity_id": cand})
    assert same.json()["id"] == doc["id"] and len(world.qloo.calls) == before


async def test_searching_for_an_act_works_without_an_account_and_junk_is_refused(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    plant_demo(admin, world)
    add_artist(admin, world, "Newcomer", 1)
    anon = world.client()
    found = await anon.get(f"{API}/{SPEC.slug}/soundcheck/search", params={"q": "Newcomer"})
    assert found.status_code == 200
    assert any(i["name"] == "Newcomer" for i in found.json()["items"])
    for q in ("a", "x" * 81, ""):
        assert (
            await anon.get(f"{API}/{SPEC.slug}/soundcheck/search", params={"q": q})
        ).status_code == 422
    assert (await anon.get(f"{API}/{SPEC.slug}/soundcheck/search")).status_code == 422


async def test_junk_input_to_a_check_is_refused_before_anything_is_spent(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    business_id = plant_demo(admin, world)
    await suggest(admin, world, business_id)
    anon = world.client()
    before = len(world.qloo.calls)
    for body in (
        {},
        {"entity_id": "short"},
        {"entity_id": "x" * 36, "extra": 1},
        {"entity_id": str(uuid.uuid4()), "basis": "nonsense"},
        {"entity_id": 7},
    ):
        res = await anon.post(f"{API}/{SPEC.slug}/soundcheck", json=body)
        assert res.status_code == 422, (body, res.text)
    unknown = await anon.post(
        f"{API}/{SPEC.slug}/soundcheck", json={"entity_id": str(uuid.uuid4())}
    )
    assert unknown.status_code in (404, 422)  # an act this server has never seen
    assert len(world.qloo.calls) == before


# ---------------------------------------------------------------------------------------------------- limits
async def test_each_network_can_run_only_a_few_checks_and_the_rest_of_the_site_is_unaffected(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    business_id = plant_demo(admin, world)
    await suggest(admin, world, business_id)
    cand = add_artist(admin, world, "Newcomer", 1)
    anon = world.client()
    codes = [
        (await anon.post(f"{API}/{SPEC.slug}/soundcheck", json={"entity_id": cand})).status_code
        for _ in range(9)
    ]
    assert codes[:8] == [200] * 8 and codes[8] == 429
    # reading is a separate allowance
    assert (await anon.get(f"{API}/{SPEC.slug}/suggestions")).status_code == 200


async def test_a_daily_cap_for_the_whole_site_stops_new_checks_for_everyone(
    make_world: Any, admin: psycopg.Connection[Any]
) -> None:
    async with make_world(demo_runs_per_day=2, trust_proxy=True) as world:
        business_id = plant_demo(admin, world)
        await suggest(admin, world, business_id)
        cand = add_artist(admin, world, "Newcomer", 1)
        anon = world.client()
        codes = [
            (await anon.post(f"{API}/{SPEC.slug}/soundcheck", json={"entity_id": cand})).status_code
            for _ in range(3)
        ]
        assert codes == [200, 200, 429]
        busy = await anon.post(f"{API}/{SPEC.slug}/soundcheck", json={"entity_id": cand})
        assert busy.json()["detail"] == demo_router.BUSY
        # another network is stopped by the site-wide cap, not by its own allowance
        other = world.client()
        other.headers["x-forwarded-for"] = "203.0.113.7"
        assert (
            await other.post(f"{API}/{SPEC.slug}/soundcheck", json={"entity_id": cand})
        ).status_code == 429


def test_the_site_caps_are_defaults_an_operator_can_change() -> None:
    from nigiwai_api.settings import Settings

    s = Settings(env="test")
    assert (s.demo_runs_per_day, s.demo_searches_per_day, s.demo_compares_per_day) == (60, 300, 100)


async def test_reading_is_rate_limited_too(world: World, admin: psycopg.Connection[Any]) -> None:
    plant_demo(admin, world)
    anon = world.client()
    codes = {(await anon.get(f"{API}/{SPEC.slug}")).status_code for _ in range(250)}
    assert codes == {200, 429}


# ---------------------------------------------------------------------------------------------------- boundaries
async def test_unknown_malformed_and_unready_venues_answer_without_leaking(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    plant_demo(admin, world, slug="mercury-lounge")
    plant_demo(admin, world, slug="still-building", status="building")
    plant_demo(admin, world, slug="went-wrong", status="failed")
    anon = world.client()
    assert (await anon.get(f"{API}/no-such-venue")).status_code == 404
    for slug in ("still-building", "went-wrong"):
        for suffix in ("", "/suggestions", "/soundchecks", "/map", "/brief", "/brief.pdf"):
            res = await anon.get(f"{API}/{slug}{suffix}")
            assert res.status_code == 503, (slug, suffix)
    for bad in ("Bad_Slug", "x", "a" * 41, "has space", "../etc", "UPPER"):
        res = await anon.get(f"{API}/{bad}")
        assert res.status_code in (404, 422), bad
    # only ready venues are listed
    assert [v["slug"] for v in (await anon.get(API)).json()] == ["mercury-lounge"]
    # ids of the underlying venue are not slugs
    business_id = admin.execute(
        "SELECT business_id FROM demo_venue WHERE slug = 'mercury-lounge'"
    ).fetchone()[0]  # type: ignore[index]
    assert (await anon.get(f"{API}/{business_id}")).status_code in (404, 422)


async def test_a_visitor_cannot_rebuild_share_or_leave_feedback_and_other_routes_stay_closed(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    business_id = plant_demo(admin, world)
    await suggest(admin, world, business_id)
    anon = world.client()
    for method, suffix in (
        ("post", "/suggestions"),
        ("post", "/brief/shares"),
        ("get", "/brief/shares"),
        ("post", "/feedback"),
        ("put", "/brief"),
        ("delete", f"/soundchecks/{uuid.uuid4()}"),
    ):
        res = await getattr(anon, method)(f"{API}/{SPEC.slug}{suffix}")
        assert res.status_code in (404, 405), (method, suffix, res.status_code)
    assert admin.execute("SELECT count(*) FROM brief_share").fetchone() == (0,)
    # the owner routes still need an account, and a different account is not a member of the demo tenant
    mine = f"/v1/tenants/{DEMO}/businesses/{business_id}"
    assert (await anon.get(f"{mine}/brief")).status_code == 401
    other = await sign_up(world)
    assert (await other.client.get(f"{mine}/brief")).status_code == 404
    assert (await other.client.get(f"{mine}/suggestions")).status_code == 404
    assert (
        await other.client.post(f"{mine}/suggestions", headers=other.headers)
    ).status_code == 404


async def test_a_demo_row_cannot_point_at_anyone_elses_venue(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    business = (await owner.post("/businesses", json={"name": "Private", "type": "bar"})).json()
    with pytest.raises(psycopg.errors.CheckViolation):
        admin.execute(
            "INSERT INTO demo_venue (slug, name, city, blurb, tenant_id, business_id)"
            " VALUES ('stolen', 'x', 'y', 'z', %s, %s)",
            (owner.tenant_id, business["id"]),
        )
    with pytest.raises(psycopg.errors.CheckViolation):
        admin.execute(
            "INSERT INTO demo_venue (slug, name, city, blurb, business_id) VALUES ('Bad Slug', 'x', 'y', 'z', %s)",
            (business["id"],),
        )


async def test_the_demo_tenant_has_no_users_and_nobody_can_sign_in_to_it(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    assert admin.execute(
        "SELECT count(*) FROM membership WHERE tenant_id = %s", (DEMO,)
    ).fetchone() == (0,)
    assert admin.execute("SELECT count(*) FROM tenant WHERE id = %s", (DEMO,)).fetchone() == (1,)


# ---------------------------------------------------------------------------------------------------- refreshing
async def test_only_ready_venues_a_week_old_are_due_and_a_failure_is_recorded_not_raised(
    make_world: Any, admin: psycopg.Connection[Any]
) -> None:
    async with make_world(musicbrainz_url=MB) as world:
        stale = plant_demo(admin, world, slug="mercury-lounge")
        plant_demo(admin, world, slug="the-hideout")  # ready and fresh
        plant_demo(admin, world, slug="empty-bottle", status="failed")
        admin.execute(
            "UPDATE demo_venue SET refreshed_at = now() - interval '8 days' WHERE business_id = %s",
            (stale,),
        )
        admin.execute(
            "UPDATE demo_venue SET refreshed_at = now() - interval '30 days' WHERE slug = 'empty-bottle'"
        )
        st = state_of(world)
        assert await demo_service.due_for_rebuild(st.engine) == ["mercury-lounge"]

        # the worker's pass: the rebuild fails (MusicBrainz is down), is recorded, and does not stop the worker
        refresh = worker.DemoRefresh(None, st.limiter, 100)
        admin.execute("DELETE FROM external_cache")
        with respx.mock(assert_all_called=False) as router:
            router.get(f"{MB}/event").mock(return_value=httpx.Response(500))
            router.get(f"{MB}/place").mock(return_value=httpx.Response(500))
            assert await worker.refresh_demo(st.engine, st.guard, st.musicbrainz, refresh) == []
        row = admin.execute(
            "SELECT status, error FROM demo_venue WHERE slug = 'mercury-lounge'"
        ).fetchone()
        assert row is not None and row[0] == "ready" and row[1]
        assert admin.execute(
            "SELECT status FROM demo_venue WHERE slug = 'the-hideout'"
        ).fetchone() == ("ready",)


async def test_the_worker_only_rebuilds_venues_it_knows_how_to_build(
    make_world: Any, admin: psycopg.Connection[Any]
) -> None:
    async with make_world(musicbrainz_url=MB) as world:
        plant_demo(admin, world, slug="invented-slug")
        admin.execute("UPDATE demo_venue SET refreshed_at = now() - interval '30 days'")
        st = state_of(world)
        assert await demo_service.due_for_rebuild(st.engine) == ["invented-slug"]
        refresh = worker.DemoRefresh(None, st.limiter, 100)
        assert await worker.refresh_demo(st.engine, st.guard, st.musicbrainz, refresh) == []


def test_the_command_refuses_an_unknown_venue_before_touching_anything(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert demo_cli.main(["no-such-venue"]) == 2
    err = capsys.readouterr().err
    assert "unknown demo venue" in err and "mercury-lounge" in err


def test_every_demo_venue_has_a_usable_spec() -> None:
    slugs = [s.slug for s in demo_service.SPECS]
    assert len(slugs) == len(set(slugs)) == 3
    for s in demo_service.SPECS:
        assert s.query and s.area_hint and s.city and s.blurb
        assert s.timezone.startswith(("America/", "Europe/"))
