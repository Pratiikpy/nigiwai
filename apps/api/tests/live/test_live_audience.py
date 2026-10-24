"""The audience reading against the real Qloo API: three crowds with well-known, very different audiences go through the
survey, the tribes job and the audience step, and each group's reading is compared with common knowledge about who
listens to those acts. About 55 live calls. Common knowledge is the same weak ground truth the research folder's proofs K
and L used, so a pass shows the direction is right, not that the numbers are accurate."""

from __future__ import annotations

import os
import random
import uuid
from typing import Any

import psycopg
import pytest
from harness import WorldFactory, make_venue, sign_up
from nigiwai_api.services import tribes as service
from nigiwai_tribes import TribesConfig

pytestmark = pytest.mark.skipif(
    os.environ.get("NIGIWAI_RUN_LIVE") != "1", reason="set NIGIWAI_RUN_LIVE=1 to spend quota"
)

CROWDS = {
    "pop": [
        "Dua Lipa",
        "Olivia Rodrigo",
        "Billie Eilish",
        "Sabrina Carpenter",
        "Charli XCX",
        "Gracie Abrams",
        "Doja Cat",
        "Taylor Swift",
    ],
    "crooners": [
        "Frank Sinatra",
        "Bing Crosby",
        "Dean Martin",
        "Tony Bennett",
        "Nat King Cole",
        "Perry Como",
        "Ella Fitzgerald",
        "Louis Armstrong",
    ],
    "metal": [
        "Metallica",
        "Iron Maiden",
        "Slayer",
        "Pantera",
        "Black Sabbath",
        "Judas Priest",
        "Motorhead",
        "Megadeth",
    ],
}
EXPECTED = {"pop": ("younger", "women"), "crooners": ("older", None), "metal": ("older", "men")}


async def test_live_audience_reading_follows_the_crowd(
    make_world: WorldFactory, admin: psycopg.Connection[Any]
) -> None:
    async with make_world(
        with_qloo=False,
        qloo_key_file=os.environ.get("NIGIWAI_QLOO_KEY_FILE"),
        min_completion_seconds=0.0,
        trust_proxy=True,
    ) as world:
        state = world.app.state.nigiwai
        assert state.guard is not None, "no Qloo key available"
        owner = await sign_up(world)
        venue = await make_venue(owner)
        ids: dict[str, list[str]] = {name: [] for name in CROWDS}
        for crowd, acts in CROWDS.items():
            guest = (
                world.client()
            )  # a sitting may make 20 live searches, so each crowd gets its own
            guest.headers["x-forwarded-for"] = (
                f"10.8.0.{len(ids[crowd]) + list(CROWDS).index(crowd) + 1}"
            )
            page = (await guest.get(f"/v1/public/survey/{venue.token}")).json()
            for act in acts:
                found = (
                    await guest.post(
                        "/v1/public/picker",
                        json={
                            "token": venue.token,
                            "nonce": page["nonce"],
                            "q": act,
                            "type": "artist",
                        },
                    )
                ).json()
                if not found["items"] or found["items"][0]["name"].lower() != act.lower():
                    print("not matched exactly:", act, [i["name"] for i in found["items"][:2]])
                    continue
                top = found["items"][0]
                sel = await guest.post(
                    "/v1/public/select",
                    json={
                        "token": venue.token,
                        "nonce": page["nonce"],
                        "entity_id": top["entity_id"],
                    },
                )
                if sel.json()["eligible"]:
                    ids[crowd].append(top["entity_id"])
        print({k: len(v) for k, v in ids.items()})
        assert all(len(v) >= 6 for v in ids.values())

        # The survey endpoints are exercised by the other live tests; here the responses go in through the same database
        # function, because one QR point holds back responses beyond 40 in ten minutes (a rule the survey rightly has).
        rng = random.Random(7)
        names: dict[str, str] = {}
        survey = admin.execute(
            "SELECT id, version FROM survey WHERE business_id = %s AND status = 'published'",
            (venue.business_id,),
        ).fetchone()
        assert survey is not None
        for n in range(75):
            crowd = list(CROWDS)[n % 3]
            picks = rng.sample(ids[crowd], 4)
            admin.execute(
                "SELECT public_insert_response(%s, %s, %s, 'v1', NULL, NULL, NULL, 'ok', %s, %s, %s)",
                (
                    venue.qr["id"],
                    survey[0],
                    survey[1],
                    picks,
                    ["urn:entity:artist"] * len(picks),
                    uuid.uuid4().bytes,
                ),
            )
            names.update({e: crowd for e in picks})
        admin.execute(
            "UPDATE response SET local_weekday = (random() * 6)::int, local_hour = (random() * 23)::int"
        )

        await service.recompute(
            state.engine,
            state.guard,
            uuid.UUID(owner.tenant_id),
            uuid.UUID(venue.business_id),
            force=True,
            cfg=TribesConfig(bootstrap=15, null_runs=19, lift_bootstrap=40),
        )
        got = (await owner.get(f"/businesses/{venue.business_id}/tribes")).json()["result"]
        print("state", got["state"], "n", got["n"])
        shown = [t for t in got["tribes"] if t["shown"]]
        found_crowds: dict[str, dict[str, Any]] = {}
        for t in shown:
            votes: dict[str, float] = {}
            for it in t["top_items"]:
                votes[names.get(it["entity_id"], "?")] = (
                    votes.get(names.get(it["entity_id"], "?"), 0) + it["weight"]
                )
            crowd = max(votes, key=lambda k: votes[k])
            r = got["audience"][str(t["index"])]
            print(t["label"], "->", crowd, [i["name"] for i in t["top_items"][:4]], r)
            found_crowds[crowd] = r
        assert set(found_crowds) == set(CROWDS), (
            f"groups did not separate the crowds: {sorted(found_crowds)}"
        )
        for crowd, (age, gender) in EXPECTED.items():
            r = found_crowds[crowd]
            assert r["status"] == "ok", (crowd, r)
            assert r["age"]["band"] == age, (crowd, r)
            if gender:
                assert r["gender"]["band"] == gender, (crowd, r)
        demographic_calls = admin.execute(
            "SELECT count(*) FROM qloo_call WHERE endpoint = '/v2/insights' AND cache = 'miss'"
            " AND purpose = 'tribes'"
        ).fetchone()
        print("live audience calls", demographic_calls[0] if demographic_calls else None)
