"""Phase 2 exit check: the Taste Card makes at most 3 Qloo calls, measured as a mean over many synthetic scans.

Each scan is a different random combination of three real items out of a pool resolved once through the live picker,
sent through the real survey endpoints and then through the card fill-in. The mean is over scans, so the private cache
is allowed to help the way it would in use. Spends up to 3 live calls per scan. NIGIWAI_CARD_SCANS sets the count
(default 40; the architecture asks for 200)."""

from __future__ import annotations

import os
import random
import statistics
import time
from typing import Any

import psycopg
import pytest
from harness import WorldFactory, make_venue, sign_up

pytestmark = pytest.mark.skipif(
    os.environ.get("NIGIWAI_RUN_LIVE") != "1", reason="set NIGIWAI_RUN_LIVE=1 to spend quota"
)

POOL = [
    ("radiohead", "artist"),
    ("bjork", "artist"),
    ("khruangbin", "artist"),
    ("nina simone", "artist"),
    ("fleetwood mac", "artist"),
    ("tame impala", "artist"),
    ("miles davis", "artist"),
    ("beyonce", "artist"),
    ("parasite", "movie"),
    ("lost in translation", "movie"),
    ("amelie", "movie"),
    ("the godfather", "movie"),
    ("the office", "tv_show"),
    ("fleabag", "tv_show"),
    ("succession", "tv_show"),
    ("the bear", "tv_show"),
    ("blue bottle", "brand"),
    ("patagonia", "brand"),
    ("aesop", "brand"),
    ("levis", "brand"),
    ("normal people", "book"),
    ("the secret history", "book"),
    ("circe", "book"),
    ("dune", "book"),
    ("serial", "podcast"),
    ("radiolab", "podcast"),
    ("zelda", "videogame"),
    ("hades", "videogame"),
]


async def test_live_card_call_budget(
    make_world: WorldFactory, admin: psycopg.Connection[Any]
) -> None:
    scans = int(os.environ.get("NIGIWAI_CARD_SCANS", "40"))
    async with make_world(
        with_qloo=False,
        qloo_key_file=os.environ.get("NIGIWAI_QLOO_KEY_FILE"),
        min_completion_seconds=0.0,
        trust_proxy=True,  # each synthetic guest comes from its own address, as real guests do
    ) as world:
        assert world.app.state.nigiwai.guard is not None, "no Qloo key available"
        owner = await sign_up(world)
        venue = await make_venue(owner)
        guest = world.client()
        page = (await guest.get(f"/v1/public/survey/{venue.token}")).json()
        items: list[str] = []
        for query, kind in POOL:
            found = (
                await guest.post(
                    "/v1/public/picker",
                    json={"token": venue.token, "nonce": page["nonce"], "q": query, "type": kind},
                )
            ).json()
            if not found["items"]:
                continue
            top = found["items"][0]
            sel = (
                await guest.post(
                    "/v1/public/select",
                    json={
                        "token": venue.token,
                        "nonce": page["nonce"],
                        "entity_id": top["entity_id"],
                    },
                )
            ).json()
            if sel["eligible"]:
                items.append(top["entity_id"])
        print(f"pool resolved: {len(items)} eligible items of {len(POOL)}")
        assert len(items) >= 15

        rng = random.Random(20261024)
        calls: list[int] = []
        waits: list[float] = []
        statuses: dict[str, int] = {}
        for i in range(scans):
            g = world.client()
            g.headers["x-forwarded-for"] = f"10.{i // 60000}.{i // 250 % 240}.{i % 250 + 1}"
            p = (await g.get(f"/v1/public/survey/{venue.token}")).json()
            picks = rng.sample(items, 3)
            sent = await g.post(
                "/v1/public/response",
                json={"token": venue.token, "nonce": p["nonce"], "picks": picks, "consent": True},
            )
            assert sent.status_code == 201, sent.text
            receipt = sent.json()["receipt"]
            simple_started = time.monotonic()
            simple = await g.post("/v1/public/card", json={"receipt": receipt})
            simple_ms = (time.monotonic() - simple_started) * 1000
            assert simple.status_code == 200 and simple_ms < 1500, (
                simple_ms
            )  # the instant card is instant
            started = time.monotonic()
            extras_res = await g.post("/v1/public/card/extras", json={"receipt": receipt})
            assert extras_res.status_code == 200, (i, extras_res.status_code, extras_res.text)
            extras = extras_res.json()
            waits.append(time.monotonic() - started)
            calls.append(int(extras.get("calls") or 0))
            statuses[extras["status"]] = statuses.get(extras["status"], 0) + 1
            if i % 20 == 19:
                print(f"{i + 1} scans, mean calls so far {statistics.mean(calls):.2f}", flush=True)
        live_calls = admin.execute(
            "SELECT count(*) FROM qloo_call WHERE purpose = 'card' AND cache = 'miss'"
        ).fetchone()
        print("scans", scans, "statuses", statuses)
        print(
            "calls charged to the card budget: mean",
            round(statistics.mean(calls), 2),
            "max",
            max(calls),
        )
        print(
            "live calls actually made:", live_calls[0], "per scan", round(live_calls[0] / scans, 2)
        )  # type: ignore[index]
        print(
            "fill-in wait: median",
            round(statistics.median(waits), 2),
            "s, p95",
            round(sorted(waits)[int(0.95 * len(waits)) - 1], 2),
            "s",
        )
        assert max(calls) <= 3
        assert statistics.mean(calls) <= 3
