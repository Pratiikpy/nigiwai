"""The picker and eligibility probe against the real Qloo API, through the whole application. Spends a few dozen
calls of quota, so it only runs with NIGIWAI_RUN_LIVE=1 and a key (NIGIWAI_QLOO_KEY_FILE or QLOO_API_KEY)."""

from __future__ import annotations

import os
from typing import Any

import psycopg
import pytest
from harness import WorldFactory, make_venue, sign_up

pytestmark = pytest.mark.skipif(
    os.environ.get("NIGIWAI_RUN_LIVE") != "1", reason="set NIGIWAI_RUN_LIVE=1 to spend quota"
)

REALISTIC = [
    ("radiohead", "artist"),
    ("the office", "tv_show"),
    ("blue bottle", "brand"),
    ("normal people", "book"),
    ("zelda", "videogame"),
    ("serial", "podcast"),
    ("parasite", "movie"),
    ("mur", None),  # a short prefix, as typed mid-word
]


async def test_live_picker_search_and_probe(
    make_world: WorldFactory, admin: psycopg.Connection[Any]
) -> None:
    async with make_world(
        with_qloo=False,
        qloo_key_file=os.environ.get("NIGIWAI_QLOO_KEY_FILE"),
        min_completion_seconds=0.0,
    ) as world:
        assert world.app.state.nigiwai.guard is not None, "no Qloo key available"
        owner = await sign_up(world)
        venue = await make_venue(owner)
        guest = world.client()
        page = (await guest.get(f"/v1/public/survey/{venue.token}")).json()
        chosen: list[str] = []
        for query, kind in REALISTIC:
            body: dict[str, Any] = {"token": venue.token, "nonce": page["nonce"], "q": query}
            if kind:
                body["type"] = kind
            r = await guest.post("/v1/public/picker", json=body)
            assert r.status_code == 200, (query, r.text)
            out = r.json()
            print(f"{query!r:16} {out['source']:6} {[i['name'] for i in out['items'][:3]]}")
            assert out["items"], f"no results for {query!r}: {out}"
            if kind and len(chosen) < 5:
                top = out["items"][0]
                assert top["type"] == kind
                sel = await guest.post(
                    "/v1/public/select",
                    json={
                        "token": venue.token,
                        "nonce": page["nonce"],
                        "entity_id": top["entity_id"],
                    },
                )
                assert sel.status_code == 200, sel.text
                print(f"   probe {top['name']!r}: eligible={sel.json()['eligible']}")
                if sel.json()["eligible"] is not False:
                    chosen.append(top["entity_id"])
        assert len(chosen) >= 3
        r = await guest.post(
            "/v1/public/response",
            json={
                "token": venue.token,
                "nonce": page["nonce"],
                "picks": chosen[:5],
                "consent": True,
            },
        )
        assert r.status_code == 201, r.text
        assert admin.execute("SELECT count(*) FROM pick").fetchone() == (len(chosen[:5]),)
        calls = admin.execute(
            "SELECT purpose, endpoint, status, transport FROM qloo_call ORDER BY created_at"
        ).fetchall()
        print(
            f"{len(calls)} Qloo calls; statuses {sorted({c[2] for c in calls})}; transports {sorted({c[3] for c in calls})}"
        )
        assert all(c[2] in ("ok", "empty") for c in calls), calls


async def test_live_place_search_is_near_the_venue_and_never_offers_a_place_of_worship_or_care(
    make_world: WorldFactory, admin: psycopg.Connection[Any]
) -> None:
    """A guest names a favourite place in the real venue's city: the search is biased to the room's position (London), the results are
    places with addresses, only taste tags were stored for them, and a search aimed at places of worship or care offers none."""
    import re

    from nigiwai_tribes import sensitive_kind
    from nigiwai_tribes.places import PLACE_TASTE_NAMESPACES, namespace_of

    async with make_world(
        with_qloo=False,
        qloo_key_file=os.environ.get("NIGIWAI_QLOO_KEY_FILE"),
        min_completion_seconds=0.0,
    ) as world:
        assert world.app.state.nigiwai.guard is not None, "no Qloo key available"
        owner = await sign_up(world)
        venue = await make_venue(owner)  # the harness room is in London
        guest = world.client()
        page = (await guest.get(f"/v1/public/survey/{venue.token}")).json()
        asked = await guest.post(
            "/v1/public/picker",
            json={"token": venue.token, "nonce": page["nonce"], "q": "dishoom", "type": "place"},
        )
        assert asked.status_code == 200, asked.text
        items = asked.json()["items"]
        assert items and all(i["type"] == "place" for i in items)
        assert any(
            re.search(r"london|uk|united kingdom", i["description"] or "", re.I) for i in items
        ), items
        # only taste tags were kept for what came back, at most twenty
        for i in items:
            tags = admin.execute(
                "SELECT tags FROM qloo_entity WHERE entity_id = %s", (i["entity_id"],)
            ).fetchone()
            assert tags is not None and 0 < len(tags[0]) <= 20
            assert {namespace_of(t[0]) for t in tags[0]} <= PLACE_TASTE_NAMESPACES
            assert sensitive_kind([(t[0], t[1]) for t in tags[0]]) is None
        # a search aimed at places of worship and care offers none of them
        for q in ("mosque", "church", "synagogue", "clinic", "pharmacy"):
            found = await guest.post(
                "/v1/public/picker",
                json={"token": venue.token, "nonce": page["nonce"], "q": q, "type": "place"},
            )
            assert found.status_code == 200, found.text
            for i in found.json()["items"]:
                tags = admin.execute(
                    "SELECT tags FROM qloo_entity WHERE entity_id = %s", (i["entity_id"],)
                ).fetchone()
                assert (
                    tags is not None and sensitive_kind([(t[0], t[1]) for t in tags[0]]) is None
                ), i
