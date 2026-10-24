"""Soundcheck against the real Qloo API, through the owner endpoints: three crowds of well-known artists, then acts whose
audiences are common knowledge. Each act should fit its own crowd's group best. The ground truth is common knowledge, not
a survey, so a pass shows the direction is right, not that the scores are calibrated. About 90 live calls."""

from __future__ import annotations

import os
import uuid
from typing import Any

import psycopg
import pytest
from harness import WorldFactory, make_venue, sign_up
from live.real_crowd import CROWDS, plant, resolve
from nigiwai_api import worker
from nigiwai_api.services import tribes as service
from nigiwai_tribes import TribesConfig

pytestmark = pytest.mark.skipif(
    os.environ.get("NIGIWAI_RUN_LIVE") != "1", reason="set NIGIWAI_RUN_LIVE=1 to spend quota"
)

ACTS = [
    ("Ariana Grande", "pop"),
    ("Pale Waves", "pop"),
    ("Peggy Lee", "crooners"),
    ("Rosemary Clooney", "crooners"),
    ("Rammstein", "metal"),
    ("Megadeth", "metal"),
]


async def test_live_soundcheck_fits_each_act_to_its_own_crowd(
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
        ids = await resolve(world, venue, CROWDS)
        assert all(len(v) >= 6 for v in ids.values()), {k: len(v) for k, v in ids.items()}
        crowd_of = plant(admin, venue, ids)
        await service.recompute(
            state.engine,
            state.guard,
            uuid.UUID(owner.tenant_id),
            uuid.UUID(venue.business_id),
            force=True,
            cfg=TribesConfig(bootstrap=15, null_runs=19, lift_bootstrap=40),
        )
        groups = (await owner.get(f"/businesses/{venue.business_id}/tribes")).json()["result"][
            "tribes"
        ]
        tribe_crowd: dict[int, str] = {}
        for t in groups:
            votes: dict[str, float] = {}
            for it in t["top_items"]:
                c = crowd_of.get(it["entity_id"], "?")
                votes[c] = votes.get(c, 0.0) + it["weight"]
            tribe_crowd[t["index"]] = max(votes, key=lambda k: votes[k])
        print("groups ->", tribe_crowd)
        assert sorted(tribe_crowd.values()) == sorted(CROWDS)

        wrong: list[str] = []
        for name, expected in ACTS:
            found = (
                await owner.get(
                    f"/businesses/{venue.business_id}/soundcheck/search", params={"q": name}
                )
            ).json()
            hit = next((i for i in found["items"] if i["name"].lower() == name.lower()), None)
            assert hit is not None, (name, [i["name"] for i in found["items"]])
            res = await owner.post(
                f"/businesses/{venue.business_id}/soundcheck", json={"entity_id": hit["entity_id"]}
            )
            assert res.status_code == 200, res.text
            doc = res.json()
            fits = {
                tribe_crowd[g["index"]]: g["fit"] for g in doc["groups"] if g["fit"] is not None
            }
            print(
                f"{name:18} status={doc['status']} score={doc['score']} band={doc['band']}",
                {k: round(v, 2) for k, v in fits.items()},
                "suits",
                doc["suits"],
            )
            assert doc["status"] == "ok", doc["reason"]
            best = max(fits, key=lambda k: fits[k])
            if best != expected or fits[expected] <= sorted(fits.values())[-2] - 1e-9:
                wrong.append(f"{name}: expected {expected}, got {fits}")
            calls = (
                await owner.get(f"/businesses/{venue.business_id}/soundchecks/{doc['id']}/calls")
            ).json()
            assert 1 <= len(calls) <= 4 and all(c["status"] in ("ok", "empty") for c in calls)
        assert not wrong, wrong

        # Suggestions, built by the worker against the same crowd.
        assert (await owner.post(f"/businesses/{venue.business_id}/suggestions")).status_code == 202
        admin.execute("UPDATE job SET run_after = now() WHERE state = 'pending'")
        while await worker.work_once(state.engine, state.guard):
            pass
        got = (await owner.get(f"/businesses/{venue.business_id}/suggestions")).json()
        print("suggestions status", got["status"], got.get("error"))
        assert got["status"] == "ready", got
        for t in got["result"]["top"]:
            print(
                "top", t["name"], t["score"], t["band"], "best for", t["best_for"], t["genres"][:3]
            )
        w = got["result"]["wildcard"]
        print("wildcard", w and (w["name"], w["score"], w["popularity"], w["best_for"]))
        assert got["result"]["top"], "no acts were suggested"
