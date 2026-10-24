"""The public-lineup start against the real MusicBrainz and Qloo, for a real venue. Spends up to 60 Qloo calls and
about ten MusicBrainz requests (one per second), so it only runs on request."""

from __future__ import annotations

import os
from typing import Any

import psycopg
import pytest
from harness import WorldFactory, make_venue, sign_up
from nigiwai_api import worker

pytestmark = pytest.mark.skipif(
    os.environ.get("NIGIWAI_RUN_LIVE") != "1", reason="set NIGIWAI_RUN_LIVE=1 to spend quota"
)


async def test_live_lineup_for_a_real_venue(
    make_world: WorldFactory, admin: psycopg.Connection[Any]
) -> None:
    async with make_world(
        with_qloo=False, qloo_key_file=os.environ.get("NIGIWAI_QLOO_KEY_FILE")
    ) as world:
        assert world.app.state.nigiwai.guard is not None, "no Qloo key available"
        owner = await sign_up(world)
        venue = await make_venue(owner)
        found = (
            await owner.get(
                f"/businesses/{venue.business_id}/lineup/search", params={"q": "Mercury Lounge"}
            )
        ).json()
        print("candidates", [(c["name"], c["area"]) for c in found])
        assert found, "MusicBrainz returned no venue"
        pick = next(c for c in found if c["area"] and "Lower East Side" in c["area"])
        queued = await owner.post(
            f"/businesses/{venue.business_id}/lineup",
            json={"mbid": pick["mbid"], "name": pick["name"], "area": pick["area"]},
        )
        assert queued.status_code == 202
        admin.execute("UPDATE job SET run_after = now() WHERE state = 'pending'")
        state = world.app.state.nigiwai
        while await worker.work_once(state.engine, state.guard, state.musicbrainz):
            pass
        got = (await owner.get(f"/businesses/{venue.business_id}/lineup")).json()
        assert got["status"] == "ready", got
        res = got["result"]
        print("events", res["events"])
        print("performers", res["performers"], "qloo calls", res["qloo_calls"])
        print("top acts", [(a["name"], a["events"], bool(a["entity_id"])) for a in res["top_acts"]])
        print("top tags", [(t["name"], t["acts"]) for t in res["top_tags"]])
        print("state", res["state"], res["reason"])
        assert res["events"]["used"] >= 10
        assert res["performers"]["resolved"] >= 1
        assert res["qloo_calls"] <= 60
