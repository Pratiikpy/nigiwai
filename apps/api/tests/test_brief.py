"""The Booking Brief: the document, its PDF and its share links. Qloo is scripted and every name is invented."""

from __future__ import annotations

import json
import uuid
from typing import Any

import psycopg
import pypdfium2 as pdfium
from harness import World, make_venue, sign_up
from nigiwai_api import worker
from nigiwai_api.services.brief import describe_when
from test_soundcheck import add_artist, base, crowd


def pdf_text(data: bytes) -> tuple[int, str]:
    doc = pdfium.PdfDocument(data)
    pages = len(doc)
    text = "".join(doc[i].get_textpage().get_text_range() for i in range(pages))
    return pages, " ".join(text.split())


async def ready_brief(
    world: World,
    admin: psycopg.Connection[Any],
    owner: Any,
    venue: Any,
    *,
    names: list[str] | None = None,
) -> list[str]:
    """A crowd with suggested acts built by the worker. Returns the planted ids."""
    ids = await crowd(world, admin, owner, venue)
    for g in range(3):
        for i in range(9):
            label = (
                (names or [])[g * 9 + i]
                if names and g * 9 + i < len(names)
                else f"Neighbour {g}-{i}"
            )
            add_artist(admin, world, label, g, popularity=0.05 + 0.1 * i)
    await owner.post(f"{base(owner, venue)}/suggestions")
    admin.execute("UPDATE job SET run_after = now() WHERE state = 'pending'")
    state = world.app.state.nigiwai
    while await worker.work_once(state.engine, state.guard):
        pass
    got = (await owner.get(f"{base(owner, venue)}/suggestions")).json()
    assert got["status"] == "ready", got
    return ids


async def test_a_venue_with_no_crowd_gets_a_brief_that_says_so_and_cannot_be_shared(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    doc = (await owner.get(f"{base(owner, venue)}/brief")).json()
    assert doc["status"] == "thin" and "no crowd yet" in doc["reason"] and doc["acts"] == []
    pdf = await owner.get(f"{base(owner, venue)}/brief.pdf")
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
    pages, text = pdf_text(pdf.content)
    assert pages == 1 and "Not enough data yet" in text and "no crowd yet" in text
    share = await owner.post(f"{base(owner, venue)}/brief/shares")
    assert share.status_code == 422 and "nothing to share yet" in share.json()["detail"]


async def test_the_brief_matches_the_suggestions_and_the_pdf_says_the_same_thing(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    await ready_brief(world, admin, owner, venue)
    suggestions = (await owner.get(f"{base(owner, venue)}/suggestions")).json()["result"]
    doc = (await owner.get(f"{base(owner, venue)}/brief")).json()
    assert doc["status"] == "ok" and doc["venue"]["business"] == "The Lantern"
    assert [a["name"] for a in doc["acts"]] == [t["name"] for t in suggestions["top"]]
    assert [a["score"] for a in doc["acts"]] == [t["score"] for t in suggestions["top"]]
    assert all(
        a["groups"] and a["best_for"] for a in doc["acts"]
    )  # a per-group breakdown on every act
    assert len(doc["groups"]) == 3 and sum(g["share"] for g in doc["groups"]) in range(98, 103)
    assert doc["basis"]["kind"] == "guests" and doc["basis"]["unit"] == "guests"
    assert doc["labels"]["crowd"] == ["measured", "modelled"]

    pdf = await owner.get(f"{base(owner, venue)}/brief.pdf")
    assert pdf.headers["content-disposition"].startswith(
        'attachment; filename="booking-brief-the-lantern-'
    )
    pages, text = pdf_text(pdf.content)
    assert pages == 1
    assert doc["title"] in text and "The Lantern".upper() in text.upper()
    for a in doc["acts"]:
        assert a["name"] in text
        assert f"range {a['band'][0]} to {a['band'][1]}" in text
        assert str(a["score"]) in text
    for g in doc["groups"]:
        assert g["label"] in text
    assert "How this was computed" in text and "Taste data from Qloo" in text
    assert "Three acts to consider" in text


async def test_a_name_the_fonts_cannot_draw_is_replaced_and_the_pdf_says_so(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    await ready_brief(world, admin, owner, venue, names=[f"東京事変 Band {i}" for i in range(27)])
    doc = (await owner.get(f"{base(owner, venue)}/brief")).json()
    assert any("東京事変" in a["name"] for a in doc["acts"])  # the document keeps the real name
    _, text = pdf_text((await owner.get(f"{base(owner, venue)}/brief.pdf")).content)
    assert "東京事変" not in text and "?" in text
    assert "could not be printed here" in text


async def test_a_share_link_is_a_frozen_names_and_scores_only_copy_that_can_be_revoked(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    other = await sign_up(world)
    venue = await make_venue(owner)
    await ready_brief(world, admin, owner, venue)
    made = await owner.post(f"{base(owner, venue)}/brief/shares")
    assert made.status_code == 201, made.text
    link = made.json()
    token = link["url"].rsplit("/", 1)[1]
    assert link["url"].startswith("https://nigiwai.test/b/") and len(token) >= 30

    anon = world.client()
    seen = await anon.get(f"/v1/public/brief/{token}")
    assert seen.status_code == 200
    shared = seen.json()
    own = (await owner.get(f"{base(owner, venue)}/brief")).json()
    assert [a["name"] for a in shared["acts"]] == [a["name"] for a in own["acts"]]
    blob = json.dumps(shared)
    # item names and our own scores only: no entity ids, no popularity, no raw Qloo fields
    for forbidden in (
        "entity_id",
        "popularity",
        "affinity",
        "soundcheck_id",
        venue.business_id,
        owner.tenant_id,
    ):
        assert forbidden not in blob
    pdf = await anon.get(f"/v1/public/brief/{token}/pdf")
    assert pdf.status_code == 200 and pdf_text(pdf.content)[0] == 1

    # frozen: the owner's brief can change, the link does not
    admin.execute("UPDATE act_suggestion SET result = jsonb_set(result, '{top,0,score}', '1')")
    assert (await anon.get(f"/v1/public/brief/{token}")).json()["acts"][0]["score"] == shared[
        "acts"
    ][0]["score"]

    listed = (await owner.get(f"{base(owner, venue)}/brief/shares")).json()
    assert len(listed) == 1 and listed[0]["live"] is True
    # other accounts cannot list, create or revoke
    theirs = f"/v1/tenants/{owner.tenant_id}/businesses/{venue.business_id}/brief/shares"
    assert (await other.client.get(theirs)).status_code == 404
    assert (await other.client.post(theirs, headers=other.headers)).status_code == 404
    assert (
        await other.client.delete(f"{theirs}/{link['id']}", headers=other.headers)
    ).status_code == 404

    assert (
        await owner.client.delete(
            f"/v1/tenants/{owner.tenant_id}/businesses/{venue.business_id}/brief/shares/{link['id']}",
            headers=owner.headers,
        )
    ).status_code == 204
    gone = await anon.get(f"/v1/public/brief/{token}")
    assert gone.status_code == 404 and gone.json()["detail"] == "This brief is no longer available."
    assert (await anon.get(f"/v1/public/brief/{token}/pdf")).status_code == 404


async def test_unknown_expired_and_junk_links_all_say_the_same_thing(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    await ready_brief(world, admin, owner, venue)
    token = (await owner.post(f"{base(owner, venue)}/brief/shares")).json()["url"].rsplit("/", 1)[1]
    admin.execute("UPDATE brief_share SET expires_at = now() - interval '1 minute'")
    anon = world.client()
    bodies = set()
    for t in (token, "x" * 32, "a" * 500):
        res = await anon.get(f"/v1/public/brief/{t}")
        assert res.status_code == 404, t
        bodies.add(res.text)
    assert len(bodies) == 1  # nothing tells an expired link from one that never existed
    for junk in ("../../etc/passwd", "%00", "%2e%2e%2f", " "):
        assert (await anon.get(f"/v1/public/brief/{junk}")).status_code in (307, 404, 422), junk
    assert (await anon.get("/v1/public/brief")).status_code in (404, 405)


async def test_the_brief_is_private_to_its_account(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    other = await sign_up(world)
    venue = await make_venue(owner)
    theirs = f"/v1/tenants/{owner.tenant_id}/businesses/{venue.business_id}"
    assert (await other.client.get(f"{theirs}/brief")).status_code == 404
    assert (await other.client.get(f"{theirs}/brief.pdf")).status_code == 404
    assert (await world.client().get(f"{theirs}/brief")).status_code == 401
    assert (await owner.get(f"/businesses/{uuid.uuid4()}/brief")).status_code == 404


def test_where_a_group_scans_is_put_in_words() -> None:
    grid = [[0.0] * 24 for _ in range(7)]
    for d in (3, 4, 5):  # Thursday to Saturday, evenings
        for h in (18, 19, 20):
            grid[d][h] = 10.0
    assert describe_when(grid) == "Skews to Thursday to Saturday, mostly evenings"
    even = [[1.0] * 24 for _ in range(7)]
    assert describe_when(even) == "Spread across the week"
    weekend = [[0.0] * 24 for _ in range(7)]
    for d in (0, 6):
        for h in (7, 8, 9):
            weekend[d][h] = 8.0
    assert describe_when(weekend) == "Skews to Monday and Sunday, mostly mornings"
    assert describe_when([[0.0] * 24 for _ in range(7)]) is None  # no scans: nothing is said
    tiny = [[0.0] * 24 for _ in range(7)]
    tiny[2][12] = 3.0
    assert describe_when(tiny) is None  # under 10 scans is too few to describe
    assert describe_when([[1.0] * 3]) is None  # a malformed grid is ignored, not guessed at
