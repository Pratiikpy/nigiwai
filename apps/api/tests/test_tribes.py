"""Tribes through the whole backend: responses queue a refit, the worker computes it under the tenant's scope, owners
read it, and a wrong or missing piece fails in a way a person can understand."""

from __future__ import annotations

import json
import uuid
from typing import Any

import numpy as np
import psycopg
from fakeqloo import artist
from harness import World, make_venue, sign_up
from nigiwai_api import worker
from nigiwai_api.services import tribes as service
from nigiwai_tribes import TribesConfig

FAST = TribesConfig(bootstrap=15, null_runs=19, lift_bootstrap=40)
TYPES = ("urn:entity:artist", "urn:entity:movie", "urn:entity:brand")


def plant(
    admin: psycopg.Connection[Any], venue: Any, n: int, *, seed: int = 1, tags: bool = True
) -> list[str]:
    """Insert n real responses (through the same database function the survey uses) from three planted tribes.
    Returns the entity ids. The three tribes' items carry mostly their own tags, so groups exist to be found."""
    rng = np.random.default_rng(seed)
    survey = admin.execute(
        "SELECT id, version FROM survey WHERE business_id = %s AND status = 'published'",
        (venue.business_id,),
    ).fetchone()
    assert survey is not None
    items: list[list[str]] = []
    for t in range(3):
        group = []
        pool = [f"urn:tag:genre:qloo:t{t}_{j}" for j in range(14)]
        for e in range(24):
            own = [pool[int(i)] for i in rng.choice(14, size=4, replace=False)]
            own += [
                f"urn:tag:genre:qloo:generic{int(rng.integers(3))}",
                f"urn:tag:style:qloo:noise{int(rng.integers(30))}",
            ]
            entity_id = str(uuid.UUID(int=(seed * 1000 + t * 100 + e + 1) + (0x7 << 100)))
            tag_json = (
                json.dumps([[tg, tg.rsplit(":", 1)[1], "urn:tag:genre:qloo"] for tg in own])
                if tags
                else "[]"
            )
            admin.execute(
                "INSERT INTO qloo_entity (entity_id, type, types, name_nfc, tags, insights_eligible)"
                " VALUES (%s, %s, %s, %s, %s::jsonb, true) ON CONFLICT (entity_id) DO NOTHING",
                (entity_id, TYPES[e % 3], [TYPES[e % 3]], f"Item {t}-{e}", tag_json),
            )
            group.append(entity_id)
        items.append(group)
    flat = [i for g in items for i in g]
    for _ in range(n):
        t = int(rng.integers(3))
        chosen: list[str] = []
        while len(chosen) < 5:
            pick = (
                items[t][int(rng.integers(24))]
                if rng.random() < 0.85
                else flat[int(rng.integers(len(flat)))]
            )
            if pick not in chosen:
                chosen.append(pick)
        types = [
            admin.execute("SELECT type FROM qloo_entity WHERE entity_id = %s", (i,)).fetchone()[0]
            for i in chosen
        ]  # type: ignore[index]
        admin.execute(
            "SELECT public_insert_response(%s, %s, %s, 'v1', NULL, NULL, NULL, 'ok', %s, %s, %s)",
            (venue.qr["id"], survey[0], survey[1], chosen, types, uuid.uuid4().bytes),
        )
    admin.execute(
        "UPDATE response SET local_weekday = (random() * 6)::int, local_hour = (random() * 23)::int"
    )
    return flat


async def drain(world: World, admin: psycopg.Connection[Any]) -> int:
    """Make every queued job due (the real delay is 20 s) and run them all."""
    admin.execute("UPDATE job SET run_after = now() WHERE state = 'pending'")
    ran = 0
    state = world.app.state.nigiwai
    while await worker.work_once(state.engine, state.guard):
        ran += 1
    return ran


async def test_responses_queue_one_refit_and_removals_queue_another(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    plant(admin, venue, 3)
    assert admin.execute(
        "SELECT count(*), min(kind) FROM job WHERE state = 'pending'"
    ).fetchone() == (1, "recompute_tribes")
    plant(admin, venue, 2, seed=2)
    assert admin.execute("SELECT count(*) FROM job WHERE state = 'pending'").fetchone() == (
        1,
    )  # a burst is one job


async def test_a_held_response_does_not_queue_a_refit(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    survey = admin.execute("SELECT id, version FROM survey").fetchone()
    pick = str(uuid.uuid4())
    admin.execute(
        "INSERT INTO qloo_entity (entity_id, type, types, name_nfc) VALUES (%s, %s, %s, %s)",
        (pick, TYPES[0], [TYPES[0]], "X"),
    )
    admin.execute(
        "SELECT public_insert_response(%s, %s, %s, 'v1', NULL, NULL, NULL, 'quarantined', %s, %s, %s)",
        (venue.qr["id"], survey[0], survey[1], [pick], [TYPES[0]], uuid.uuid4().bytes),  # type: ignore[index]
    )
    assert admin.execute("SELECT count(*) FROM job").fetchone() == (0,)


async def test_too_few_guests_stores_an_honest_none_with_the_distance_to_go(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    plant(admin, venue, 25)
    assert await drain(world, admin) == 1
    r = (await owner.get(f"/businesses/{venue.business_id}/tribes")).json()
    assert r["responses"] == 25 and r["unlock"] == {
        "provisional": 60,
        "named": 200,
        "min_group": 10,
    }
    assert (
        r["result"]["state"] == "none"
        and r["result"]["tribes"] == []
        and "60" in r["result"]["reason"]
    )
    assert r["refit_queued"] is False


async def test_a_planted_crowd_becomes_provisional_groups_without_names(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    plant(admin, venue, 90)
    out = await service.recompute(
        world.app.state.nigiwai.engine,
        None,
        uuid.UUID(owner.tenant_id),
        uuid.UUID(venue.business_id),
        force=True,
        cfg=FAST,
    )
    assert out.stored and out.state == "provisional" and out.version == 1
    r = (await owner.get(f"/businesses/{venue.business_id}/tribes")).json()
    res = r["result"]
    assert res["state"] == "provisional" and res["n"] == 90 and len(res["tribes"]) == 3
    assert all(t["name"] is None and t["label"].startswith("Group ") for t in res["tribes"])
    assert all(t["shown"] and t["top_tags"] and t["top_items"] for t in res["tribes"])
    assert res["stability"]["beats_both_nulls"] is True
    # The fitted profiles stay on the server: the browser needs the cards, not the model.
    assert "h" not in res and "vocab" not in res and res["vocab_size"] > 0


async def test_unchanged_crowd_is_not_refitted_and_new_responses_make_a_new_version(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    plant(admin, venue, 70)
    engine = world.app.state.nigiwai.engine
    t, b = uuid.UUID(owner.tenant_id), uuid.UUID(venue.business_id)
    assert (await service.recompute(engine, None, t, b, cfg=FAST)).stored
    again = await service.recompute(engine, None, t, b, cfg=FAST)
    assert not again.stored and again.reason == "not due"
    forced = await service.recompute(engine, None, t, b, force=True, cfg=FAST)
    assert (
        not forced.stored and forced.reason == "unchanged"
    )  # same picks, same hash: no duplicate version
    plant(admin, venue, 12, seed=5)
    nxt = await service.recompute(engine, None, t, b, cfg=FAST)
    assert nxt.stored and nxt.version == 2 and nxt.n == 82
    assert admin.execute("SELECT count(*) FROM tribe_version").fetchone() == (2,)


async def test_names_appear_from_two_hundred(world: World, admin: psycopg.Connection[Any]) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    plant(admin, venue, 205)
    out = await service.recompute(
        world.app.state.nigiwai.engine,
        None,
        uuid.UUID(owner.tenant_id),
        uuid.UUID(venue.business_id),
        force=True,
        cfg=FAST,
    )
    assert out.state == "named"
    res = (await owner.get(f"/businesses/{venue.business_id}/tribes")).json()["result"]
    assert all(t["name"] and t["name"].endswith("crowd") and t["used_tags"] for t in res["tribes"])


async def test_the_worker_runs_the_queued_job_and_removes_it(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    plant(admin, venue, 70)
    admin.execute("UPDATE job SET run_after = now()")
    assert await drain(world, admin) == 1
    assert admin.execute("SELECT state, attempts FROM job").fetchone() == ("done", 1)
    assert admin.execute("SELECT state, n FROM tribe_version").fetchone() == ("provisional", 70)
    assert await drain(world, admin) == 0


async def test_a_job_that_fails_is_retried_later_then_given_up_on(
    world: World, admin: psycopg.Connection[Any], monkeypatch: Any
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    plant(admin, venue, 3)
    admin.execute("UPDATE job SET run_after = now()")

    async def boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("database hiccup")

    monkeypatch.setattr(service, "recompute", boom)
    engine = world.app.state.nigiwai.engine
    assert await worker.work_once(engine, None)
    state, attempts, error, wait = admin.execute(
        "SELECT state, attempts, last_error, extract(epoch FROM run_after - now()) FROM job"
    ).fetchone()  # type: ignore[misc]
    assert (state, attempts) == ("pending", 1) and "database hiccup" in error and 20 < wait <= 31
    for _ in range(3):
        admin.execute("UPDATE job SET run_after = now()")
        assert await worker.work_once(engine, None)
    assert admin.execute("SELECT state, attempts FROM job").fetchone() == ("failed", 4)


async def test_a_job_a_crashed_worker_left_running_is_picked_up_again(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    plant(admin, venue, 3)
    admin.execute(
        "UPDATE job SET state = 'running', locked_at = now() - interval '11 minutes', run_after = now()"
    )
    assert await drain(world, admin) == 1
    assert admin.execute("SELECT state FROM job").fetchone() == ("done",)


async def test_two_workers_never_take_the_same_job(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    import asyncio

    owner = await sign_up(world)
    venue = await make_venue(owner)
    plant(admin, venue, 3)
    admin.execute("UPDATE job SET run_after = now()")
    engine = world.app.state.nigiwai.engine
    claimed = await asyncio.gather(*[worker.claim(engine) for _ in range(6)])
    assert sum(1 for c in claimed if c is not None) == 1


async def test_picks_without_stored_tags_are_filled_in_with_one_batched_call(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    ids = plant(admin, venue, 70, tags=False)
    # Qloo knows these items and their tags; the local index does not yet.
    world.qloo.catalogue = [
        artist(
            f"Item {i}",
            entity_id=entity_id,
            tags=[
                (
                    f"urn:tag:genre:qloo:t{i // 24}_{(i * 5 + k) % 14}",
                    f"Flavour {i // 24}-{(i * 5 + k) % 14}",
                )
                for k in range(4)
            ],
        )
        for i, entity_id in enumerate(ids)
    ]
    out = await service.recompute(
        world.app.state.nigiwai.engine,
        world.app.state.nigiwai.guard,
        uuid.UUID(owner.tenant_id),
        uuid.UUID(venue.business_id),
        force=True,
        cfg=FAST,
    )
    assert out.stored and out.n == 70
    calls = [c for c in world.qloo.calls if c[0] == "/entities"]
    assert len(calls) == 2  # 72 distinct items, 50 per call
    assert admin.execute(
        "SELECT count(*) FROM qloo_call WHERE purpose = 'tribes' AND endpoint = '/entities'"
    ).fetchone() == (2,)


async def test_without_tags_and_without_qloo_the_crowd_is_left_out_and_counted(
    make_world: Any, admin: psycopg.Connection[Any]
) -> None:
    async with make_world(with_qloo=False) as world:
        owner = await sign_up(world)
        venue = await make_venue(owner)
        plant(admin, venue, 70, tags=False)
        out = await service.recompute(
            world.app.state.nigiwai.engine,
            None,
            uuid.UUID(owner.tenant_id),
            uuid.UUID(venue.business_id),
            force=True,
            cfg=FAST,
        )
        assert out.state == "none" and out.n == 0
        res = (await owner.get(f"/businesses/{venue.business_id}/tribes")).json()["result"]
        assert res["dropped"]["respondents_too_few_picks"] == 70


async def test_only_members_read_tribes_and_only_writers_can_force_a_refit(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    other = await sign_up(world)
    viewer = await sign_up(world)
    venue = await make_venue(owner)
    admin.execute(
        "INSERT INTO membership (tenant_id, user_id, role) VALUES (%s, %s, 'viewer')",
        (owner.tenant_id, viewer.me["user_id"]),
    )
    base = f"/v1/tenants/{owner.tenant_id}/businesses/{venue.business_id}/tribes"
    assert (await viewer.client.get(base)).status_code == 200
    assert (
        await viewer.client.post(f"{base}/recompute", headers=viewer.headers)
    ).status_code == 403
    assert (await other.client.get(base)).status_code == 404
    assert (await other.client.post(f"{base}/recompute", headers=other.headers)).status_code == 404
    assert (
        await owner.client.get(base.replace(venue.business_id, str(uuid.uuid4())))
    ).status_code == 404
    queued = await owner.client.post(f"{base}/recompute", headers=owner.headers)
    assert queued.status_code == 202
    assert admin.execute("SELECT payload FROM job WHERE state = 'pending'").fetchone() == (
        {"force": True},
    )
    # Asking twice is still one job.
    await owner.client.post(f"{base}/recompute", headers=owner.headers)
    assert admin.execute("SELECT count(*) FROM job WHERE state = 'pending'").fetchone() == (1,)


async def test_a_removed_guest_leaves_the_groups_at_the_next_refit(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    plant(admin, venue, 70)
    engine = world.app.state.nigiwai.engine
    t, b = uuid.UUID(owner.tenant_id), uuid.UUID(venue.business_id)
    await service.recompute(engine, None, t, b, cfg=FAST)
    admin.execute("UPDATE job SET state = 'done'")
    first_hash = admin.execute("SELECT delete_token_hash FROM response LIMIT 1").fetchone()[0]  # type: ignore[index]
    assert admin.execute("SELECT public_delete_response(%s)", (first_hash,)).fetchone() == (True,)
    assert admin.execute("SELECT count(*) FROM job WHERE state = 'pending'").fetchone() == (1,)
    out = await service.recompute(engine, None, t, b, force=True, cfg=FAST)
    assert out.stored and out.n == 69


async def test_tribe_versions_are_invisible_across_tenants(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    from harness import APP_URL
    from nigiwai_api.db import transaction
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    a = await sign_up(world)
    b = await sign_up(world)
    venue = await make_venue(a)
    plant(admin, venue, 25)
    await service.recompute(
        world.app.state.nigiwai.engine,
        None,
        uuid.UUID(a.tenant_id),
        uuid.UUID(venue.business_id),
        force=True,
        cfg=FAST,
    )
    engine = create_async_engine(APP_URL)
    try:
        async with transaction(
            engine, tenant_id=uuid.UUID(b.tenant_id), user_id=uuid.UUID(b.me["user_id"])
        ) as conn:
            assert (
                await conn.execute(text("SELECT count(*) FROM tribe_version"))
            ).scalar_one() == 0
        async with transaction(
            engine, tenant_id=uuid.UUID(a.tenant_id), user_id=uuid.UUID(a.me["user_id"])
        ) as conn:
            assert (
                await conn.execute(text("SELECT count(*) FROM tribe_version"))
            ).scalar_one() == 1
    finally:
        await engine.dispose()
