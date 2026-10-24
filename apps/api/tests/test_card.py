"""The Taste Card: instant, honest, and authorised by the receipt alone."""

from __future__ import annotations

import uuid
from typing import Any

import psycopg
from harness import World, make_venue, sign_up
from nigiwai_api.services import card as card_service
from nigiwai_api.services import tribes as service
from nigiwai_tribes import TribesConfig
from test_tribes import FAST, plant

ARTIST = "urn:entity:artist"
MOVIE = "urn:entity:movie"


def guest(
    admin: psycopg.Connection[Any], venue: Any, picks: list[str], *, quality: str = "ok"
) -> tuple[str, bytes]:
    """One guest's response, made the way the survey makes it. Returns (receipt, hash)."""
    import secrets

    from nigiwai_api.security import token_hash

    receipt = secrets.token_urlsafe(16)
    survey = admin.execute(
        "SELECT id, version FROM survey WHERE business_id = %s AND status = 'published'",
        (venue.business_id,),
    ).fetchone()
    types = [
        admin.execute("SELECT type FROM qloo_entity WHERE entity_id = %s", (p,)).fetchone()[0]  # type: ignore[index]
        for p in picks
    ]
    admin.execute(
        "SELECT public_insert_response(%s, %s, %s, 'v1', NULL, NULL, NULL, %s, %s, %s, %s)",
        (venue.qr["id"], survey[0], survey[1], quality, picks, types, token_hash(receipt)),  # type: ignore[index]
    )
    return receipt, token_hash(receipt)


def known(admin: psycopg.Connection[Any], name: str, kind: str = ARTIST, tags: bool = True) -> str:
    entity_id = str(uuid.uuid4())
    tag_json = '[["urn:tag:genre:qloo:folk","Folk","urn:tag:genre:qloo"]]' if tags else "[]"
    admin.execute(
        "INSERT INTO qloo_entity (entity_id, type, types, name_nfc, tags, insights_eligible)"
        " VALUES (%s, %s, %s, %s, %s::jsonb, true)",
        (entity_id, kind, [kind], name, tag_json),
    )
    return entity_id


async def card(world: World, receipt: str, path: str = "/v1/public/card") -> Any:
    return await world.client().post(path, json={"receipt": receipt})


async def test_a_venue_with_no_crowd_yet_gives_a_simple_honest_card(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner, reward={"title": "A free coffee", "detail": "At the bar."})
    picks = [known(admin, f"Pick {i}") for i in range(4)]
    receipt, _ = guest(admin, venue, picks)
    r = await card(world, receipt)
    assert r.status_code == 200
    body = r.json()
    assert body["venue"] == "The Lantern"
    assert body["group"]["status"] == "forming" and body["group"]["label"] is None
    assert body["group"]["n"] == 0 and body["group"]["needed"] == 60
    assert [p["name"] for p in body["picks"]] == [
        "Pick 0",
        "Pick 1",
        "Pick 2",
    ]  # no group to rank by: their own order
    assert body["reward"]["title"] == "A free coffee"
    assert world.qloo.calls == []  # the instant card costs nothing


async def test_with_groups_the_card_names_the_nearest_without_claiming_anything_about_the_person(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    flat = plant(admin, venue, 90, seed=11)
    await service.recompute(
        world.app.state.nigiwai.engine,
        None,
        uuid.UUID(owner.tenant_id),
        uuid.UUID(venue.business_id),
        force=True,
        cfg=FAST,
    )
    labels = set()
    for t in range(3):
        mine = flat[t * 24 : (t + 1) * 24][:5]
        receipt, _ = guest(admin, venue, mine)
        body = (await card(world, receipt)).json()
        assert body["group"]["status"] == "matched" and body["group"]["provisional"] is True
        assert body["group"]["label"].startswith("Group ")
        assert (
            body["group"]["share_text"].startswith("About ")
            and "in 10 guests here pick like this" in body["group"]["share_text"]
        )
        labels.add(body["group"]["label"])
        assert len(body["picks"]) == 3
    assert len(labels) == 3  # three different crowds of picks land in three different groups
    assert "you" not in body["group"]["share_text"].lower().replace(
        "guests", ""
    )  # says nothing about the person


async def test_a_wrong_removed_or_junk_receipt_is_the_same_404(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    receipt, h = guest(admin, venue, [known(admin, f"P{i}") for i in range(3)])
    assert (await card(world, receipt)).status_code == 200
    admin.execute("SELECT public_delete_response(%s)", (h,))
    bodies = set()
    for bad in (receipt, "x" * 24, "not-a-receipt-at-all"):
        r = await card(world, bad)
        assert r.status_code == 404, bad
        bodies.add(r.text)
    assert len(bodies) == 1
    assert (await card(world, "short")).status_code == 422
    assert (await card(world, receipt, "/v1/public/card/extras")).status_code == 404


async def test_a_held_response_still_gets_a_card(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    receipt, _ = guest(
        admin, venue, [known(admin, f"Q{i}") for i in range(3)], quality="quarantined"
    )
    assert (await card(world, receipt)).status_code == 200


async def test_the_fill_in_is_at_most_three_calls_cached_and_only_from_qloo(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    picks = [known(admin, "Folk Act"), known(admin, "Quiet Film", MOVIE), known(admin, "Third")]
    receipt, _ = guest(admin, venue, picks)
    r = await card(world, receipt, "/v1/public/card/extras")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "ok" and out["calls"] <= 3
    insight_calls = [c for c in world.qloo.calls if c[0] == "/v2/insights"]
    assert 2 <= len(insight_calls) <= 3
    assert [p["name"] for p in out["near"]] == [
        "Invented Bar 0",
        "Invented Bar 1",
        "Invented Bar 2",
    ]
    assert [p["distance_m"] for p in out["near"]] == [150, 300, 450]
    assert out["related"] and all(rel["items"] and rel["because"] for rel in out["related"])
    # Everything shown was in a Qloo answer: the names are the fake's, not invented by the product.
    assert all(i["name"].startswith("Neighbour") for rel in out["related"] for i in rel["items"])
    # Traced to the venue's tenant under the card purpose.
    assert admin.execute(
        "SELECT count(*) FROM qloo_call WHERE purpose = 'card' AND tenant_id = %s",
        (owner.tenant_id,),
    ).fetchone() == (len(insight_calls),)
    # The same card again is served from the private cache, not Qloo.
    before = len(world.qloo.calls)
    again = await card(world, receipt, "/v1/public/card/extras")
    assert again.json()["related"] == out["related"] and len(world.qloo.calls) == before


async def test_the_fill_in_is_skipped_when_qloo_is_down_slow_or_absent(
    world: World, admin: psycopg.Connection[Any], monkeypatch: Any, make_world: Any
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    receipt, _ = guest(admin, venue, [known(admin, f"R{i}") for i in range(3)])
    world.qloo.down = True
    down = (await card(world, receipt, "/v1/public/card/extras")).json()
    assert down["status"] == "unavailable" and down["related"] == [] and down["near"] == []
    assert (await card(world, receipt)).status_code == 200  # the simple card is unaffected
    world.qloo.down = False
    world.qloo.delay = 0.6
    monkeypatch.setattr(card_service, "EXTRAS_TIMEOUT_S", 0.2)
    slow = (await card(world, receipt, "/v1/public/card/extras")).json()
    assert slow["status"] == "slow" and slow["related"] == []
    async with make_world(with_qloo=False) as bare:
        owner2 = await sign_up(bare)
        venue2 = await make_venue(owner2)
        receipt2, _ = guest(admin, venue2, [known(admin, f"S{i}") for i in range(3)])
        assert (
            await bare.client().post("/v1/public/card/extras", json={"receipt": receipt2})
        ).json()["status"] == "unavailable"


async def test_picks_qloo_never_confirmed_are_not_used_as_seeds(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    picks = [known(admin, f"U{i}") for i in range(3)]
    admin.execute(
        "UPDATE qloo_entity SET insights_eligible = NULL WHERE entity_id = ANY(%s)", (picks,)
    )
    receipt, _ = guest(admin, venue, picks)
    out = (await card(world, receipt, "/v1/public/card/extras")).json()
    assert out["status"] == "unavailable"
    assert world.qloo.calls == []


async def test_the_card_endpoints_are_rate_limited(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    codes = [(await card(world, "x" * 24)).status_code for _ in range(45)]
    assert codes[:40] == [404] * 40 and set(codes[40:]) == {429}


async def test_named_groups_show_their_names_on_the_card(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    flat = plant(admin, venue, 205, seed=21)
    await service.recompute(
        world.app.state.nigiwai.engine,
        None,
        uuid.UUID(owner.tenant_id),
        uuid.UUID(venue.business_id),
        force=True,
        cfg=TribesConfig(bootstrap=15, null_runs=19, lift_bootstrap=40),
    )
    receipt, _ = guest(admin, venue, flat[:5])
    group = (await card(world, receipt)).json()["group"]
    assert (
        group["status"] == "matched"
        and group["provisional"] is False
        and group["label"].endswith("crowd")
    )
    assert group["line"].startswith("Most picked: ")


async def test_the_share_image_is_a_png_with_names_only(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    import io

    from PIL import Image

    owner = await sign_up(world)
    venue = await make_venue(owner)
    picks = [
        known(admin, "Folk Act"),
        known(admin, "Quiet Film", MOVIE),
        known(admin, "渋谷系 Unicode Band"),
    ]
    receipt, _ = guest(admin, venue, picks)
    r = await world.client().post("/v1/public/card/share", json={"receipt": receipt})
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert "attachment" in r.headers["content-disposition"]
    img = Image.open(io.BytesIO(r.content))
    assert img.size == (1080, 1350)
    # The image holds text, not the guest: the file name and alt text carry no receipt.
    assert (
        receipt not in r.headers["content-disposition"] and receipt not in r.headers["x-alt-text"]
    )
    assert r.headers["x-alt-text"].startswith("Taste Card for The Lantern")
    assert (
        await world.client().post("/v1/public/card/share", json={"receipt": "x" * 24})
    ).status_code == 404


async def test_results_for_a_seed_qloo_dropped_are_not_shown_as_matched_to_the_guest(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    picks = [known(admin, f"Dropped {i}") for i in range(3)]
    world.qloo.drop_seeds = set(
        picks
    )  # Qloo knows none of them and would answer with popular items regardless
    receipt, _ = guest(admin, venue, picks)
    out = (await card(world, receipt, "/v1/public/card/extras")).json()
    assert out["status"] == "unavailable" and out["related"] == [] and out["near"] == []
