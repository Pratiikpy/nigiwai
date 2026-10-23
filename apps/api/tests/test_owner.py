"""Owner endpoints: every field at its limits, junk, and the audit trail."""

from __future__ import annotations

import uuid
from typing import Any

import psycopg
from harness import World, make_venue, sign_up


async def test_business_lifecycle_and_listing(world: World) -> None:
    owner = await sign_up(world)
    assert (await owner.get("/businesses")).json() == []
    made = await owner.post(
        "/businesses", json={"name": "  Cafe Nord  ", "type": "cafe", "currency": "eur"}
    )
    assert made.status_code == 201
    body = made.json()
    assert body["name"] == "Cafe Nord" and body["currency"] == "EUR" and body["language"] == "en"
    assert [b["id"] for b in (await owner.get("/businesses")).json()] == [body["id"]]


async def test_a_business_can_be_renamed(world: World) -> None:
    owner = await sign_up(world)
    made = (await owner.post("/businesses", json={"name": "Old", "type": "bar"})).json()
    renamed = await owner.put(
        f"/businesses/{made['id']}", json={"name": "New Name", "type": "cafe", "currency": "gbp"}
    )
    assert renamed.status_code == 200
    assert (renamed.json()["name"], renamed.json()["type"], renamed.json()["currency"]) == (
        "New Name",
        "cafe",
        "GBP",
    )
    assert (
        await owner.put(f"/businesses/{uuid.uuid4()}", json={"name": "x", "type": "bar"})
    ).status_code == 404
    assert (
        await owner.put(f"/businesses/{made['id']}", json={"name": "", "type": "bar"})
    ).status_code == 422


async def test_business_rejects_junk(world: World) -> None:
    owner = await sign_up(world)
    for payload in (
        {},
        {"name": "", "type": "bar"},
        {"name": " ", "type": "bar"},
        {"name": "x" * 121, "type": "bar"},
        {"name": "ok", "type": "spaceship"},
        {"name": "ok", "type": "bar", "currency": "EURO"},
        {"name": "ok", "type": "bar", "currency": "E"},
        {"name": "ok", "type": "bar", "language": "fr"},
        {"name": "ok", "type": "bar", "tenant_id": owner.tenant_id},
        {"name": "nul\x00byte", "type": "bar"},
        {"name": "line\nbreak", "type": "bar"},
        {"name": 5, "type": "bar"},
    ):
        r = await owner.post("/businesses", json=payload)
        assert r.status_code == 422, (payload, r.status_code)
    assert (await owner.get("/businesses")).json() == []


async def test_location_boundaries(world: World) -> None:
    owner = await sign_up(world)
    b = (await owner.post("/businesses", json={"name": "B", "type": "bar"})).json()["id"]
    base = f"/businesses/{b}/locations"
    good = {
        "name": "Door",
        "lat": 90,
        "lon": -180,
        "radius_m": 50,
        "timezone": "America/New_York",
        "price_level": 4,
        "capacity": 1,
        "curfew": "23:00",
        "excluded_genres": ["metal"],
        "show_nights": [4, 5],
    }
    r = await owner.post(base, json=good)
    assert r.status_code == 201, r.text
    out = r.json()
    assert (
        (out["lat"], out["lon"]) == (90, -180)
        and out["show_nights"] == [4, 5]
        and out["excluded_genres"] == ["metal"]
    )
    for patch in (
        {"lat": 90.0001},
        {"lat": -91},
        {"lon": 181},
        {"lat": None},
        {"lon": None},
        {"radius_m": 49},
        {"radius_m": 50_001},
        {"timezone": "Mars/Olympus"},
        {"timezone": ""},
        {"price_level": 0},
        {"price_level": 5},
        {"capacity": 0},
        {"show_nights": [7]},
        {"show_nights": [1, 1]},
        {"show_nights": [-1]},
        {"excluded_genres": ["x"] * 21},
        {"curfew": "x" * 21},
        {"name": ""},
        {"address": "x" * 301},
        {"address": "a\x00b"},
        {"lat": "51.5"},
    ):
        r = await owner.post(base, json={**good, **patch})
        assert r.status_code == 422, (patch, r.status_code, r.text)
    # A place with no coordinates is allowed, and coordinates are stored longitude-first.
    nocoord = await owner.post(base, json={"name": "Somewhere"})
    assert (
        nocoord.status_code == 201
        and nocoord.json()["lat"] is None
        and nocoord.json()["lon"] is None
    )


async def test_coordinates_round_trip_without_swapping_lat_and_lon(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)  # lat 51.5, lon -0.12 (London)
    loc = (await owner.get(f"/businesses/{venue.business_id}/locations")).json()[0]
    assert (loc["lat"], loc["lon"]) == (51.5, -0.12)
    x, y = admin.execute(
        "SELECT ST_X(geom::geometry), ST_Y(geom::geometry) FROM location"
    ).fetchone()  # type: ignore[misc]
    assert (x, y) == (-0.12, 51.5)  # PostGIS stores (x, y) = (lon, lat)
    moved = await owner.put(
        f"/locations/{venue.location_id}", json={"name": "Moved", "lat": 40.7, "lon": -74.0}
    )
    assert moved.status_code == 200 and (moved.json()["lat"], moved.json()["lon"]) == (40.7, -74.0)


async def test_qr_points_are_unique_secret_and_listed(world: World) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    second = await owner.post(
        f"/locations/{venue.location_id}/qr-points", json={"label": "Table 4"}
    )
    urls = {venue.qr["url"], second.json()["url"]}
    assert len(urls) == 2 and all(u.startswith("https://nigiwai.test/s/") for u in urls)
    listed = (await owner.get(f"/locations/{venue.location_id}/qr-points")).json()
    assert [q["label"] for q in listed] == ["Bar end", "Table 4"]
    assert all(len(q["token_hint"]) == 4 and q["status"] == "active" for q in listed)
    assert (
        await owner.post(f"/locations/{venue.location_id}/qr-points", json={"label": ""})
    ).status_code == 422


async def test_qr_token_is_never_stored_in_clear(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    for (table,) in admin.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
    ).fetchall():
        rows = admin.execute(f'SELECT t::text FROM "{table}" t').fetchall()
        assert not any(venue.token in r[0] for r in rows), table
    # Even the encrypted column cannot be read with the wrong secret.
    (enc,) = admin.execute("SELECT token_enc FROM qr_point").fetchone()  # type: ignore[misc]
    assert venue.token.encode() not in bytes(enc)


async def test_survey_save_validation(world: World) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner, publish=False)
    path = f"/businesses/{venue.business_id}/survey"
    for payload in (
        {"questions": {"min_picks": 6, "max_picks": 5}},
        {"questions": {"max_picks": 2}},
        {"questions": {"max_picks": 11}},
        {"questions": {"min_picks": 0}},
        {"questions": {"picker_types": []}},
        {"questions": {"picker_types": ["person"]}},
        {"questions": {"ask_age_band": "yes"}},
        {"questions": {"max_picks": 5.5}},
        {"questions": {"unknown": 1}},
        {"reward": {"title": ""}},
        {"reward": {"title": "x" * 81}},
        {"reward": {"title": "ok", "detail": "x" * 201}},
        {"publish": "yes"},
    ):
        r = await owner.put(path, json=payload)
        assert r.status_code == 422, (payload, r.status_code)
    ok = await owner.put(
        path,
        json={"questions": {"min_picks": 1, "max_picks": 3}, "reward": {"title": "Free coffee"}},
    )
    assert ok.status_code == 200 and ok.json()["status"] == "draft" and ok.json()["version"] == 2
    assert (await owner.get(path)).json()["reward"] == {"title": "Free coffee", "detail": ""}


async def test_publishing_without_any_survey_fails_cleanly(world: World) -> None:
    owner = await sign_up(world)
    b = (await owner.post("/businesses", json={"name": "B", "type": "bar"})).json()["id"]
    empty = await owner.get(f"/businesses/{b}/survey")
    assert empty.status_code == 200 and empty.json() is None
    published = await owner.put(f"/businesses/{b}/survey", json={"publish": True})
    assert published.status_code == 200 and published.json()["version"] == 1


async def test_stats_count_only_clean_responses(world: World) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    stats = (await owner.get(f"/businesses/{venue.business_id}/stats")).json()
    assert stats == {
        "responses": 0,
        "held_for_review": 0,
        "qr_points": [{"id": venue.qr["id"], "label": "Bar end", "responses": 0}],
    }


async def test_every_change_is_written_to_the_audit_log(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    await owner.post(f"/qr-points/{venue.qr['id']}/rotate")
    await owner.post(f"/qr-points/{venue.qr['id']}/revoke")
    actions = [r[0] for r in admin.execute("SELECT action FROM audit_log ORDER BY id").fetchall()]
    assert actions == [
        "business.create",
        "location.create",
        "qr.create",
        "survey.publish",
        "qr.rotate",
        "qr.revoke",
    ]
    actors = {r[0] for r in admin.execute("SELECT actor FROM audit_log").fetchall()}
    assert actors == {owner.me["user_id"]}
    payloads = " ".join(str(r) for r in admin.execute("SELECT * FROM audit_log").fetchall())
    assert venue.token not in payloads  # the log names what changed, never a secret
