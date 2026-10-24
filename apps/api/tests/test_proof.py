"""The proof panel: what Qloo was asked, how it answered, and whether anything shown traces back to it."""

from __future__ import annotations

import json
import uuid
from typing import Any

import psycopg
from fakeqloo import artist
from harness import World, make_venue, sign_up
from nigiwai_api.services import tribes as service
from test_tribes import FAST, plant


async def test_guest_calls_are_counted_but_never_listed(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    world.qloo.catalogue = [artist("Secret Search Term Band")]
    guest = world.client()
    page = (await guest.get(f"/v1/public/survey/{venue.token}")).json()
    await guest.post(
        "/v1/public/picker",
        json={"token": venue.token, "nonce": page["nonce"], "q": "secret search term"},
    )
    body = (await owner.client.get(f"/v1/tenants/{owner.tenant_id}/proof")).json()
    purposes = {p["purpose"]: p for p in body["usage_30_days"]["by_purpose"]}
    assert purposes["picker"]["calls"] == 1 and purposes["picker"]["live"] == 1
    assert body["recent_calls"] == []  # what a guest typed is not shown to the owner
    assert "secret search term" not in json.dumps(body).lower()
    assert body["usage_30_days"]["calls"] == 1 and body["usage_30_days"]["cache_share"] == 0.0


async def test_traced_items_count_and_an_untraceable_one_is_called_invented(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    plant(admin, venue, 70)
    await service.recompute(
        world.app.state.nigiwai.engine,
        None,
        uuid.UUID(owner.tenant_id),
        uuid.UUID(venue.business_id),
        force=True,
        cfg=FAST,
    )
    url = f"/v1/tenants/{owner.tenant_id}/proof"
    ok = (await owner.client.get(url)).json()["integrity"]
    assert ok["items_shown"] > 0 and ok["invented"] == 0 and ok["items_traced"] == ok["items_shown"]
    # Corrupt the stored result so it names an entity the index never held: the panel must say so.
    admin.execute(
        "UPDATE tribe_version SET result = jsonb_set(result, '{tribes,0,top_items,0,entity_id}', to_jsonb(%s::text))",
        (str(uuid.uuid4()),),
    )
    bad = (await owner.client.get(url)).json()["integrity"]
    assert bad["invented"] == 1


async def test_tribe_calls_are_listed_with_their_rules_and_the_account_is_private(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    other = await sign_up(world)
    venue = await make_venue(owner)
    ids = plant(admin, venue, 70, tags=False)
    world.qloo.catalogue = [
        artist(
            f"Item {i}",
            entity_id=e,
            # four of the group's fourteen tags, a different four for each item, so the groups are real structure
            # and not forty identical rows (which the stability test rightly refuses to call groups)
            tags=[
                (f"urn:tag:genre:qloo:t{i // 24}_{(i * 5 + k * 3) % 14}", f"F{k}") for k in range(4)
            ],
        )
        for i, e in enumerate(ids)
    ]
    await service.recompute(
        world.app.state.nigiwai.engine,
        world.app.state.nigiwai.guard,
        uuid.UUID(owner.tenant_id),
        uuid.UUID(venue.business_id),
        force=True,
        cfg=FAST,
    )
    mine = (await owner.client.get(f"/v1/tenants/{owner.tenant_id}/proof")).json()
    calls = mine["recent_calls"]
    assert [c["purpose"] for c in calls] == ["tribes"] * 5
    entity_calls = [c for c in calls if c["endpoint"] == "/entities"]
    audience_calls = [
        c for c in calls if ("filter.type", "urn:demographics") in [tuple(p) for p in c["params"]]
    ]
    assert (
        len(entity_calls) == 2 and len(audience_calls) == 3
    )  # tags for 72 items; one reading per group
    first = entity_calls[0]
    assert first["status"] == "ok" and first["results"] > 0
    assert any(k == "entity_ids" for k, _ in first["params"])
    theirs = (await other.client.get(f"/v1/tenants/{other.tenant_id}/proof")).json()
    assert theirs["recent_calls"] == [] and theirs["usage_30_days"]["calls"] == 0
    assert (await other.client.get(f"/v1/tenants/{owner.tenant_id}/proof")).status_code == 404
    assert (await world.client().get(f"/v1/tenants/{owner.tenant_id}/proof")).status_code == 401
