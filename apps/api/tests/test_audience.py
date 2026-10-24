"""The audience reading (PRD M7): a coarse age and gender lean per group from Qloo's audience data, shown as modelled.
All numbers here are invented; they are of the same size as ones seen when Qloo's demographics were tested."""

from __future__ import annotations

import uuid
from typing import Any

import psycopg
from harness import World, make_venue, sign_up
from nigiwai_api.services import audience
from nigiwai_api.services import tribes as service
from qloo_guard import DemographicsItem
from test_tribes import FAST, plant


def item(entity_id: str, female: float, contrast: float) -> DemographicsItem:
    q = contrast / 4
    return DemographicsItem(
        entity_id=entity_id,
        age={
            "24_and_younger": -q,
            "25_to_29": -q,
            "30_to_34": 0.0,
            "35_to_44": 0.0,
            "45_to_54": q,
            "55_and_older": q,
        },
        gender={"female": female, "male": -female},
    )


def reading(rows: list[tuple[float, float, float]], asked: int | None = None) -> dict[str, Any]:
    """rows: (female index, age contrast, pick weight) per item."""
    items = [item(f"e{i}", f, c) for i, (f, c, _) in enumerate(rows)]
    weights = {f"e{i}": w for i, (_, _, w) in enumerate(rows)}
    return audience.summarise(items, weights, asked or len(rows))


def test_contrast_is_older_bands_minus_younger_bands() -> None:
    assert audience.age_contrast(item("a", 0.0, 1.2)) == 1.2
    assert audience.female_index(item("a", 0.4, 0.0)) == 0.4


def test_a_young_female_crowd_a_crooner_crowd_and_a_male_rock_crowd_read_differently() -> None:
    young = reading([(0.5, -1.7, 3), (0.6, -1.5, 2), (0.4, -2.0, 1)])
    older = reading([(0.0, 1.2, 3), (0.1, 0.7, 2), (-0.1, 1.4, 1)])
    rock = reading([(-0.5, 0.6, 3), (-0.4, 1.3, 2), (-0.45, 0.7, 1)])
    assert (young["age"]["band"], young["gender"]["band"]) == ("younger", "women")
    assert (older["age"]["band"], older["gender"]["band"]) == ("older", "balanced")
    assert (rock["age"]["band"], rock["gender"]["band"]) == ("older", "men")
    assert young["age"]["label"].startswith("Younger-leaning")


def test_the_reading_is_weighted_by_how_strongly_the_group_picks_an_item() -> None:
    heavy_young = reading([(0.5, -1.8, 10), (0.5, 1.5, 1), (0.5, 1.5, 1)])
    heavy_old = reading([(0.5, -1.8, 1), (0.5, 1.5, 10), (0.5, 1.5, 10)])
    assert heavy_young["age"]["band"] == "younger" and heavy_old["age"]["band"] == "older"


def test_near_the_boundary_is_mixed_and_a_small_gender_lean_is_not_called_a_lean() -> None:
    mixed = reading([(0.05, -0.4, 1)] * 3)
    assert mixed["age"]["band"] == "mixed" and mixed["gender"]["band"] == "balanced"


def test_fewer_than_three_items_with_audience_data_is_said_so_not_averaged() -> None:
    thin = reading([(0.5, -1.0, 1), (0.5, -1.0, 1)], asked=8)
    assert thin["status"] == "thin" and thin["items_used"] == 2 and "age" not in thin
    assert "2 of this group's 8" in thin["reason"]


def test_an_item_with_a_missing_age_band_is_left_out_not_zeroed() -> None:
    broken = DemographicsItem(
        entity_id="e0", age={"45_to_54": 1.0}, gender={"female": 0.2, "male": -0.2}
    )
    out = audience.summarise(
        [broken, item("e1", 0.3, 1.0), item("e2", 0.3, 1.0), item("e3", 0.3, 1.0)],
        {"e0": 5, "e1": 1, "e2": 1, "e3": 1},
        4,
    )
    assert out["status"] == "ok" and out["items_used"] == 3 and out["age"]["index"] == 1.0


async def test_each_shown_group_gets_one_reading_stored_beside_the_groups(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    ids = plant(admin, venue, 70)
    expected = [(0.5, -1.9), (0.0, 0.95), (-0.45, 0.73)]  # planted group 0, 1, 2
    for g, (female, contrast) in enumerate(expected):
        for e in ids[g * 24 : (g + 1) * 24]:
            world.qloo.demographics[e] = (female, contrast)
    await service.recompute(
        world.app.state.nigiwai.engine,
        world.app.state.nigiwai.guard,
        uuid.UUID(owner.tenant_id),
        uuid.UUID(venue.business_id),
        force=True,
        cfg=FAST,
    )
    got = (
        await owner.client.get(
            f"/v1/tenants/{owner.tenant_id}/businesses/{venue.business_id}/tribes"
        )
    ).json()
    result = got["result"]
    assert result["state"] in ("provisional", "named")
    shown = [t for t in result["tribes"] if t["shown"]]
    assert len(shown) == 3
    labels = {0: ("younger", "women"), 1: ("older", "balanced"), 2: ("older", "men")}
    for t in shown:
        planted = ids.index(t["top_items"][0]["entity_id"]) // 24
        r = result["audience"][str(t["index"])]
        assert r["status"] == "ok" and r["items_used"] >= 3
        assert (r["age"]["band"], r["gender"]["band"]) == labels[planted]
    demographic_calls = [
        c for c in world.qloo.calls if dict(c[1]).get("filter.type") == "urn:demographics"
    ]
    assert len(demographic_calls) == 3  # one per shown group, never one per guest


async def test_a_qloo_outage_leaves_the_groups_in_place_and_says_the_reading_is_unavailable(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    plant(admin, venue, 70)
    world.qloo.down = True
    await service.recompute(
        world.app.state.nigiwai.engine,
        world.app.state.nigiwai.guard,
        uuid.UUID(owner.tenant_id),
        uuid.UUID(venue.business_id),
        force=True,
        cfg=FAST,
    )
    got = (
        await owner.client.get(
            f"/v1/tenants/{owner.tenant_id}/businesses/{venue.business_id}/tribes"
        )
    ).json()
    result = got["result"]
    assert result["state"] in ("provisional", "named") and any(t["shown"] for t in result["tribes"])
    assert result["audience"] and all(
        a["status"] == "unavailable" for a in result["audience"].values()
    )


async def test_a_crowd_too_small_for_groups_makes_no_audience_calls(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    plant(admin, venue, 20)
    await service.recompute(
        world.app.state.nigiwai.engine,
        world.app.state.nigiwai.guard,
        uuid.UUID(owner.tenant_id),
        uuid.UUID(venue.business_id),
        force=True,
        cfg=FAST,
    )
    assert not [c for c in world.qloo.calls if dict(c[1]).get("filter.type") == "urn:demographics"]
