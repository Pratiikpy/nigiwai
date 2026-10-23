"""The guest's side: open the survey, search, pick, submit, delete. Every state, including the hostile ones."""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any

import httpx
import psycopg
from fakeqloo import new_id
from harness import World, make_venue, seed_entities, sign_up
from nigiwai_api.security import make_nonce, token_hash

ARTIST = "urn:entity:artist"
MOVIE = "urn:entity:movie"


def seed_picks(admin: psycopg.Connection[Any], n: int = 6) -> list[str]:
    ids = [new_id() for _ in range(n)]
    seed_entities(admin, [(i, ARTIST, f"Invented Act {k}") for k, i in enumerate(ids)])
    return ids


async def open_survey(client: httpx.AsyncClient, token: str) -> dict[str, Any]:
    r = await client.get(f"/v1/public/survey/{token}")
    assert r.status_code == 200, r.text
    return r.json()


def submission(token: str, nonce: str, picks: list[str], **over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"token": token, "nonce": nonce, "picks": picks, "consent": True}
    body.update(over)
    return body


async def test_the_full_guest_journey_stores_exactly_what_was_promised(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(
        owner, reward={"title": "A free coffee", "detail": "Show this screen."}
    )
    ids = seed_picks(admin)
    guest = world.client()

    page = await open_survey(guest, venue.token)
    assert page["business_name"] == "The Lantern" and page["location_name"] == "Main room"
    assert page["reward"]["title"] == "A free coffee"
    assert "no" in page["consent_body"].lower() and page["consent_text_version"]

    found = (
        await guest.post(
            "/v1/public/picker",
            json={"token": venue.token, "nonce": page["nonce"], "q": "invented"},
        )
    ).json()
    assert {i["entity_id"] for i in found["items"]} >= set(ids[:5])
    for entity_id in ids[:5]:
        sel = await guest.post(
            "/v1/public/select",
            json={"token": venue.token, "nonce": page["nonce"], "entity_id": entity_id},
        )
        assert sel.status_code == 200

    r = await guest.post(
        "/v1/public/response",
        json=submission(
            venue.token, page["nonce"], ids[:5], age_band="25-34", district="Eastside", budget=2
        ),
        headers={"x-forwarded-for": "203.0.113.9", "user-agent": "GuestPhone/1.0"},
    )
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["ok"] and len(out["receipt"]) >= 20 and out["reward"]["title"] == "A free coffee"

    row = admin.execute(
        "SELECT age_band, district, budget, quality_flag, local_weekday, local_hour, consent_text_version FROM response"
    ).fetchall()
    assert len(row) == 1
    age, district, budget, quality, weekday, hour, consent = row[0]
    assert (age, district, budget, quality) == ("25-34", "Eastside", 2, "ok")
    assert 0 <= weekday <= 6 and 0 <= hour <= 23 and consent == page["consent_text_version"]
    picks = admin.execute(
        "SELECT position, entity_id, entity_type FROM pick ORDER BY position"
    ).fetchall()
    assert [p[1] for p in picks] == ids[:5] and {p[2] for p in picks} == {ARTIST}
    assert [p[0] for p in picks] == [1, 2, 3, 4, 5]


async def test_nothing_identifying_is_stored_with_a_response(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    """Schema and data check: no IP, user agent, device id or exact timestamp column exists on the answer tables,
    and the address and user agent a guest sent appear nowhere in the database."""
    owner = await sign_up(world)
    venue = await make_venue(owner)
    ids = seed_picks(admin)
    guest = world.client()
    page = await open_survey(guest, venue.token)
    r = await guest.post(
        "/v1/public/response",
        json=submission(venue.token, page["nonce"], ids[:3]),
        headers={
            "x-forwarded-for": "198.51.100.77",
            "user-agent": "UniqueAgent/9.9 (Secret Device)",
        },
    )
    assert r.status_code == 201
    for table in ("response", "pick"):
        cols = {
            c[0]
            for c in admin.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = %s", (table,)
            ).fetchall()
        }
        assert not {
            c
            for c in cols
            if re.search(r"ip|agent|device|created_at|submitted|timestamp|cookie|fingerprint", c)
        }, cols
    dump = ""
    for (table,) in admin.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
    ).fetchall():
        for row in admin.execute(f'SELECT t::text FROM "{table}" t').fetchall():
            dump += row[0]
    assert "198.51.100.77" not in dump and "UniqueAgent" not in dump and "Secret Device" not in dump


async def test_a_nonce_works_once(world: World, admin: psycopg.Connection[Any]) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    ids = seed_picks(admin)
    guest = world.client()
    page = await open_survey(guest, venue.token)
    body = submission(venue.token, page["nonce"], ids[:3])
    assert (await guest.post("/v1/public/response", json=body)).status_code == 201
    again = await guest.post("/v1/public/response", json=body)
    assert again.status_code == 409
    assert admin.execute("SELECT count(*) FROM response").fetchone() == (1,)


async def test_concurrent_submits_of_one_nonce_store_one_response(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    ids = seed_picks(admin)
    page = await open_survey(world.client(), venue.token)
    body = submission(venue.token, page["nonce"], ids[:3])
    results = await asyncio.gather(
        *[world.client().post("/v1/public/response", json=body) for _ in range(8)]
    )
    assert sorted(r.status_code for r in results).count(201) == 1
    assert admin.execute("SELECT count(*) FROM response").fetchone() == (1,)


async def test_forged_expired_and_foreign_nonces_are_refused(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    one = await make_venue(owner)
    two = await make_venue(owner)
    ids = seed_picks(admin)
    guest = world.client()
    page_one = await open_survey(guest, one.token)
    secret = world.settings.secret_key
    qr_hash = token_hash(one.token).hex()
    expired = make_nonce(secret, qr_hash, 3600, now=time.time() - 7200)
    forged = page_one["nonce"][:-3] + ("AAA" if not page_one["nonce"].endswith("AAA") else "BBB")
    for nonce in (forged, expired, "garbage", "a.b.c", page_one["nonce"] + "x"):
        r = await guest.post("/v1/public/response", json=submission(one.token, nonce, ids[:3]))
        assert r.status_code in (403, 422), (nonce, r.status_code)
    # A nonce minted for QR point one is useless at QR point two.
    r = await guest.post(
        "/v1/public/response", json=submission(two.token, page_one["nonce"], ids[:3])
    )
    assert r.status_code == 403
    assert admin.execute("SELECT count(*) FROM response").fetchone() == (0,)


async def test_consent_is_required(world: World, admin: psycopg.Connection[Any]) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    ids = seed_picks(admin)
    guest = world.client()
    page = await open_survey(guest, venue.token)
    r = await guest.post(
        "/v1/public/response", json=submission(venue.token, page["nonce"], ids[:3], consent=False)
    )
    assert r.status_code == 422
    assert admin.execute("SELECT count(*) FROM response").fetchone() == (0,)
    # The failed attempt did not burn the sitting: the guest can fix it and send again.
    assert (
        await guest.post(
            "/v1/public/response", json=submission(venue.token, page["nonce"], ids[:3])
        )
    ).status_code == 201


async def test_pick_validation(world: World, admin: psycopg.Connection[Any]) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner, questions={"min_picks": 3, "max_picks": 4})
    ids = seed_picks(admin, 8)
    admin.execute(
        "UPDATE qloo_entity SET insights_eligible = false WHERE entity_id = %s", (ids[7],)
    )
    guest = world.client()
    page = await open_survey(guest, venue.token)
    cases = {
        "too few": ids[:2],
        "too many": ids[:5],
        "duplicate": [ids[0], ids[0], ids[1]],
        "never offered": [ids[0], ids[1], new_id()],
        "not an id": [ids[0], ids[1], "x" * 36],
        "ineligible": [ids[0], ids[1], ids[7]],
        "empty": [],
    }
    for name, picks in cases.items():
        r = await guest.post(
            "/v1/public/response", json=submission(venue.token, page["nonce"], picks)
        )
        assert r.status_code == 422, (name, r.status_code, r.text)
    assert admin.execute("SELECT count(*) FROM response").fetchone() == (0,)


async def test_a_pick_of_a_kind_the_survey_does_not_ask_for_is_refused(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner, questions={"picker_types": ["artist"], "min_picks": 3})
    ids = seed_picks(admin, 2)
    film = new_id()
    seed_entities(admin, [(film, MOVIE, "Invented Film")])
    guest = world.client()
    page = await open_survey(guest, venue.token)
    r = await guest.post(
        "/v1/public/response", json=submission(venue.token, page["nonce"], [*ids, film])
    )
    assert r.status_code == 422


async def test_district_cannot_carry_personal_details(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    ids = seed_picks(admin)
    guest = world.client()
    page = await open_survey(guest, venue.token)
    for bad in (
        "me@example.com",
        "https://x.test",
        "Flat 12, 10 Downing Street 12345",
        "x" * 61,
        "line\nbreak",
    ):
        r = await guest.post(
            "/v1/public/response",
            json=submission(venue.token, page["nonce"], ids[:3], district=bad),
        )
        assert r.status_code == 422, (bad, r.status_code)
    ok = await guest.post(
        "/v1/public/response",
        json=submission(venue.token, page["nonce"], ids[:3], district="  St  Pauls "),
    )
    assert ok.status_code == 201
    assert admin.execute("SELECT district FROM response").fetchone() == ("St Pauls",)


async def test_answers_the_survey_does_not_ask_for_are_dropped(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(
        owner, questions={"ask_age_band": False, "ask_district": False, "ask_budget": False}
    )
    ids = seed_picks(admin)
    guest = world.client()
    page = await open_survey(guest, venue.token)
    r = await guest.post(
        "/v1/public/response",
        json=submission(
            venue.token, page["nonce"], ids[:3], age_band="18-24", district="Eastside", budget=3
        ),
    )
    assert r.status_code == 201
    assert admin.execute("SELECT age_band, district, budget FROM response").fetchone() == (
        None,
        None,
        None,
    )


async def test_junk_bodies_are_422_never_500(world: World, admin: psycopg.Connection[Any]) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    ids = seed_picks(admin)
    guest = world.client()
    page = await open_survey(guest, venue.token)
    good = submission(venue.token, page["nonce"], ids[:3])
    junk = [
        {},
        {**good, "extra": 1},
        {**good, "picks": "not-a-list"},
        {**good, "age_band": "teen"},
        {**good, "budget": 9},
        {**good, "budget": "high"},
        {**good, "consent": "yes"},
        {**good, "token": "short"},
        {**good, "token": "../../etc/passwd" + "x" * 8},
        {**good, "nonce": ""},
        {**good, "picks": [None, None, None]},
    ]
    for body in junk:
        r = await guest.post("/v1/public/response", json=body)
        assert r.status_code in (422, 403, 404), (body, r.status_code)
    for raw in (b"{", b"null", b"[]", b"\xff\xfe"):
        r = await guest.post(
            "/v1/public/response", content=raw, headers={"content-type": "application/json"}
        )
        assert r.status_code == 422, (raw, r.status_code)
    assert admin.execute("SELECT count(*) FROM response").fetchone() == (0,)


async def test_a_filled_honeypot_looks_like_success_and_stores_nothing(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    ids = seed_picks(admin)
    guest = world.client()
    page = await open_survey(guest, venue.token)
    r = await guest.post(
        "/v1/public/response",
        json=submission(venue.token, page["nonce"], ids[:3], website="http://spam.test"),
    )
    assert r.status_code == 201 and r.json()["ok"]
    assert admin.execute("SELECT count(*) FROM response").fetchone() == (0,)


async def test_a_response_faster_than_a_person_is_held_for_review(
    make_world: Any, admin: psycopg.Connection[Any]
) -> None:
    async with make_world(min_completion_seconds=30.0) as world:
        owner = await sign_up(world)
        venue = await make_venue(owner)
        ids = seed_picks(admin)
        guest = world.client()
        page = await open_survey(guest, venue.token)
        r = await guest.post(
            "/v1/public/response", json=submission(venue.token, page["nonce"], ids[:3])
        )
        assert r.status_code == 201
        assert admin.execute("SELECT quality_flag FROM response").fetchone() == ("quarantined",)
        stats = (await owner.get(f"/businesses/{venue.business_id}/stats")).json()
        assert stats["responses"] == 0 and stats["held_for_review"] == 1


async def test_a_burst_to_one_qr_point_is_held_for_review(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    ids = seed_picks(admin)
    for _ in range(43):
        guest = world.client()
        page = await open_survey(guest, venue.token)
        r = await guest.post(
            "/v1/public/response", json=submission(venue.token, page["nonce"], ids[:3])
        )
        assert r.status_code == 201
    flags = dict(admin.execute("SELECT quality_flag, count(*) FROM response GROUP BY 1").fetchall())
    assert flags == {"ok": 40, "quarantined": 3}


async def test_the_receipt_deletes_the_answers_and_only_those(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    ids = seed_picks(admin)
    receipts = []
    for _ in range(2):
        guest = world.client()
        page = await open_survey(guest, venue.token)
        r = await guest.post(
            "/v1/public/response", json=submission(venue.token, page["nonce"], ids[:3])
        )
        receipts.append(r.json()["receipt"])
    assert admin.execute("SELECT count(*) FROM pick").fetchone() == (6,)
    anyone = world.client()
    assert (
        await anyone.post("/v1/public/response/delete", json={"receipt": receipts[0]})
    ).json() == {"removed": True}
    assert admin.execute(
        "SELECT count(*), (SELECT count(*) FROM pick) FROM response"
    ).fetchone() == (1, 3)
    assert (
        await anyone.post("/v1/public/response/delete", json={"receipt": receipts[0]})
    ).json() == {"removed": False}
    assert (await anyone.post("/v1/public/response/delete", json={"receipt": "x" * 24})).json() == {
        "removed": False
    }
    assert (
        await anyone.post("/v1/public/response/delete", json={"receipt": "short"})
    ).status_code == 422
    assert admin.execute("SELECT count(*) FROM response").fetchone() == (1,)


async def test_receipt_is_stored_only_as_a_hash(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    ids = seed_picks(admin)
    guest = world.client()
    page = await open_survey(guest, venue.token)
    receipt = (
        await guest.post(
            "/v1/public/response", json=submission(venue.token, page["nonce"], ids[:3])
        )
    ).json()["receipt"]
    (stored,) = admin.execute("SELECT delete_token_hash FROM response").fetchone()  # type: ignore[misc]
    assert bytes(stored) == token_hash(receipt) and receipt.encode() not in bytes(stored)


async def test_unknown_revoked_and_unpublished_qr_codes_are_all_the_same_404(world: World) -> None:
    owner = await sign_up(world)
    live = await make_venue(owner)
    draft = await make_venue(owner, publish=False)
    revoked = await make_venue(owner)
    assert (await owner.post(f"/qr-points/{revoked.qr['id']}/revoke")).status_code == 200
    guest = world.client()
    bodies = set()
    for token in ("A" * 24, "short", draft.token, revoked.token):
        r = await guest.get(f"/v1/public/survey/{token}")
        assert r.status_code == 404, (token, r.status_code)
        bodies.add(r.text)
    assert len(bodies) == 1  # nothing distinguishes "never existed" from "turned off"
    assert (await guest.get("/v1/public/survey/../../../etc/passwd")).status_code == 404
    assert (await guest.get(f"/v1/public/survey/{live.token}")).status_code == 200


async def test_rotating_a_qr_code_kills_the_old_one_immediately(world: World) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    guest = world.client()
    assert (await guest.get(f"/v1/public/survey/{venue.token}")).status_code == 200
    rotated = (await owner.post(f"/qr-points/{venue.qr['id']}/rotate")).json()
    new_token = rotated["url"].rsplit("/", 1)[1]
    assert new_token != venue.token
    assert (await guest.get(f"/v1/public/survey/{venue.token}")).status_code == 404
    assert (await guest.get(f"/v1/public/survey/{new_token}")).status_code == 200
    # Revoked then rotated comes back to life under a new secret.
    await owner.post(f"/qr-points/{venue.qr['id']}/revoke")
    assert (await guest.get(f"/v1/public/survey/{new_token}")).status_code == 404
    again = (await owner.post(f"/qr-points/{venue.qr['id']}/rotate")).json()
    assert again["status"] == "active"
    assert (
        await guest.get(f"/v1/public/survey/{again['url'].rsplit('/', 1)[1]}")
    ).status_code == 200


async def test_a_new_survey_version_replaces_the_old_for_new_guests_only(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner, questions={"min_picks": 3, "max_picks": 5})
    ids = seed_picks(admin)
    guest = world.client()
    page_v1 = await open_survey(guest, venue.token)
    assert (
        await guest.post(
            "/v1/public/response", json=submission(venue.token, page_v1["nonce"], ids[:3])
        )
    ).status_code == 201
    v2 = await owner.put(
        f"/businesses/{venue.business_id}/survey",
        json={"questions": {"min_picks": 4, "max_picks": 6}, "publish": True},
    )
    assert v2.json()["version"] == 2
    page_v2 = await open_survey(world.client(), venue.token)
    assert page_v2["questions"]["min_picks"] == 4
    versions = dict(admin.execute("SELECT version, status FROM survey").fetchall())
    assert versions == {1: "archived", 2: "published"}
    assert admin.execute("SELECT survey_version FROM response").fetchone() == (
        1,
    )  # the first answer keeps its questions
    # A draft does not go live.
    await owner.put(
        f"/businesses/{venue.business_id}/survey",
        json={"questions": {"min_picks": 5, "max_picks": 7}, "publish": False},
    )
    assert (await open_survey(world.client(), venue.token))["questions"]["min_picks"] == 4


async def test_public_endpoints_are_rate_limited_per_address(world: World) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    guest = world.client()
    codes = [(await guest.get(f"/v1/public/survey/{venue.token}")).status_code for _ in range(95)]
    assert codes[:90] == [200] * 90 and set(codes[90:]) == {429}
    # Another address is not affected.
    other = await world.client().get(f"/v1/public/survey/{venue.token}", headers={})
    assert other.status_code == 429  # same test client address in this harness
    world.app.state.nigiwai.settings.trust_proxy = True
    elsewhere = await world.client().get(
        f"/v1/public/survey/{venue.token}", headers={"x-forwarded-for": "192.0.2.55"}
    )
    assert elsewhere.status_code == 200


async def test_forwarded_for_is_ignored_unless_the_proxy_is_trusted(world: World) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    guest = world.client()
    # Rotating the header must not buy extra requests when no trusted proxy sits in front.
    codes = [
        (
            await guest.get(
                f"/v1/public/survey/{venue.token}",
                headers={"x-forwarded-for": f"198.51.100.{i % 250}"},
            )
        ).status_code
        for i in range(95)
    ]
    assert 429 in codes


async def test_oversized_bodies_are_refused_before_parsing(world: World) -> None:
    guest = world.client()
    r = await guest.post(
        "/v1/public/response",
        content=b'{"x":"' + b"a" * 200_000 + b'"}',
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 413

    # Streamed with no declared length.
    async def stream():  # type: ignore[no-untyped-def]
        for _ in range(300):
            yield b"a" * 1024

    r = await guest.post(
        "/v1/public/response", content=stream(), headers={"content-type": "application/json"}
    )
    assert r.status_code == 413


async def test_survey_page_without_a_qloo_key_still_works(
    make_world: Any, admin: psycopg.Connection[Any]
) -> None:
    async with make_world(with_qloo=False) as world:
        owner = await sign_up(world)
        venue = await make_venue(owner)
        ids = seed_picks(admin)
        guest = world.client()
        page = await open_survey(guest, venue.token)
        found = (
            await guest.post(
                "/v1/public/picker",
                json={"token": venue.token, "nonce": page["nonce"], "q": "invented act 2"},
            )
        ).json()
        assert found["items"] and found["source"] == "local"
        sel = await guest.post(
            "/v1/public/select",
            json={"token": venue.token, "nonce": page["nonce"], "entity_id": ids[2]},
        )
        assert sel.status_code == 200 and sel.json()["eligible"] is None
        assert (
            await guest.post(
                "/v1/public/response", json=submission(venue.token, page["nonce"], ids[:3])
            )
        ).status_code == 201
