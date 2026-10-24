"""Grow against the real Qloo API, through the owner endpoints and the worker: three crowds of well-known artists (pop, crooners,
metal) at a London bar, then one run. The assertions are about what a run must never do, whatever Qloo answers: list an item Qloo did
not return, list a closed or out-of-area place, or claim a match its own checks do not support. What Qloo actually answered is
printed so it can be read. About 40 live calls."""

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


async def test_live_grow_never_lists_what_qloo_did_not_return_and_says_what_its_checks_allow(
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
        plant(admin, venue, ids)
        await service.recompute(
            state.engine,
            state.guard,
            uuid.UUID(owner.tenant_id),
            uuid.UUID(venue.business_id),
            force=True,
            cfg=TribesConfig(bootstrap=15, null_runs=19, lift_bootstrap=40),
        )
        root = f"/businesses/{venue.business_id}"
        assert (await owner.get(f"{root}/grow")).json()["state"] == "not_run"
        assert (await owner.post(f"{root}/grow")).status_code == 202
        admin.execute("UPDATE job SET run_after = now() WHERE state = 'pending'")
        while await worker.work_once(state.engine, state.guard):
            pass
        doc = (await owner.get(f"{root}/grow")).json()
        assert doc["state"] == "ready", doc
        run = doc["run"]
        ghosts, places = run["ghosts"], run["places"]
        print("groups", [(g["label"], g["share"]) for g in run["groups"]])
        print(
            "ghosts", ghosts["status"], "act similarity", ghosts["act_similarity"], ghosts["reason"]
        )
        for g in ghosts["items"]:
            print(
                "  ghost",
                g["group_index"],
                g["tag"],
                "via",
                g["bridges"],
                "carrying",
                g["carrying"],
                [a["name"] for a in g["acts"]],
            )
        assert ghosts["status"] in ("ok", "none", "not_group_specific")

        assert places["status"] == "ok", places
        for part in ("nearby", "elsewhere"):
            sec = places[part]
            print(
                part,
                sec["status"],
                sec["mode"],
                "seed effect",
                sec["seed_effect"],
                "similarity",
                sec["similarity"],
                "told apart",
                sec["told_apart"],
                [p["name"] for p in sec["items"]],
            )
            print("  ", sec["note"])
            assert sec["note"] and sec["status"] in ("ok", "empty")
            if sec["status"] == "ok":
                assert sec["mode"] in ("taste", "near")
                assert sec["seed_effect"] is not None
                if sec["mode"] == "near":
                    assert sec["by_group"] is None
        assert places["nearby"]["gaps"] == [] or places["nearby"]["told_apart"] is True
        print(
            "closed and dropped:",
            places["dropped_closed"],
            "closure unanswered:",
            places["closure_unanswered"],
        )

        # nothing is listed that Qloo did not return: every act and place is a stored Qloo entity of the right kind and name
        listed: list[tuple[str, str, str]] = [
            (a["entity_id"], a["name"], "urn:entity:artist")
            for g in ghosts["items"]
            for a in g["acts"]
        ]
        sections = [places["nearby"], places["elsewhere"]]
        for sec in sections:
            listed += [(p["entity_id"], p["name"], "urn:entity:place") for p in sec["items"]]
            for g in sec["by_group"] or []:
                listed += [(p["entity_id"], p["name"], "urn:entity:place") for p in g["items"]]
        for entity_id, name, kind in listed:
            row = admin.execute(
                "SELECT name_nfc, type, is_closed FROM qloo_entity WHERE entity_id = %s",
                (entity_id,),
            ).fetchone()
            assert row is not None, (name, "not a stored Qloo entity")
            assert row[0] == name and row[1] == kind, (name, row)
            assert row[2] is not True, (name, "Qloo marks it closed")
        wide = places["wide_radius_m"]
        for p in places["nearby"]["items"]:
            assert 0 < p["distance_m"] <= places["radius_m"] * 1.02, p
        for p in places["elsewhere"]["items"]:
            assert places["radius_m"] < p["distance_m"] <= wide * 1.02, p

        calls = (await owner.get(f"{root}/grow/calls")).json()
        print(
            "qloo calls",
            len(calls),
            sorted({(c["endpoint"], c["status"], c["cache"]) for c in calls}),
        )
        assert 5 <= len(calls) <= 40
        assert all(c["status"] in ("ok", "degraded", "empty") for c in calls)
