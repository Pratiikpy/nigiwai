"""The Taste Card's fill-in against the real Qloo API, end to end through the application. Spends about ten calls."""

from __future__ import annotations

import os
from typing import Any

import psycopg
import pytest
from harness import WorldFactory, make_venue, sign_up

pytestmark = pytest.mark.skipif(
    os.environ.get("NIGIWAI_RUN_LIVE") != "1", reason="set NIGIWAI_RUN_LIVE=1 to spend quota"
)


async def test_live_card_fill_in(make_world: WorldFactory, admin: psycopg.Connection[Any]) -> None:
    async with make_world(
        with_qloo=False, qloo_key_file=os.environ.get("NIGIWAI_QLOO_KEY_FILE")
    ) as world:
        assert world.app.state.nigiwai.guard is not None, "no Qloo key available"
        owner = await sign_up(world)
        venue = await make_venue(
            owner
        )  # the harness venue sits at 51.5, -0.12 (central London), radius 800 m
        guest = world.client()
        page = (await guest.get(f"/v1/public/survey/{venue.token}")).json()
        chosen: list[str] = []
        for query, kind in (
            ("radiohead", "artist"),
            ("normal people", "book"),
            ("blue bottle", "brand"),
        ):
            found = (
                await guest.post(
                    "/v1/public/picker",
                    json={"token": venue.token, "nonce": page["nonce"], "q": query, "type": kind},
                )
            ).json()
            top = found["items"][0]
            sel = await guest.post(
                "/v1/public/select",
                json={"token": venue.token, "nonce": page["nonce"], "entity_id": top["entity_id"]},
            )
            assert sel.json()["eligible"] is True
            chosen.append(top["entity_id"])
        sent = await guest.post(
            "/v1/public/response",
            json={"token": venue.token, "nonce": page["nonce"], "picks": chosen, "consent": True},
        )
        receipt = sent.json()["receipt"]
        simple = await guest.post("/v1/public/card", json={"receipt": receipt})
        assert simple.status_code == 200 and simple.json()["group"]["status"] == "forming"
        extras = (await guest.post("/v1/public/card/extras", json={"receipt": receipt})).json()
        print("status", extras["status"], "calls", extras.get("calls"))
        for rel in extras["related"]:
            print("because", rel["because"], "->", [i["name"] for i in rel["items"]])
        print("near", [(p["name"], p["distance_m"]) for p in extras["near"]])
        assert extras["status"] == "ok"
        assert extras["related"] and all(
            i["name"] for rel in extras["related"] for i in rel["items"]
        )
        # Places came back inside the venue's radius, which is the one thing Qloo is measurably good at.
        assert all(p["distance_m"] is None or p["distance_m"] <= 800 for p in extras["near"])
        assert extras["calls"] <= 3
