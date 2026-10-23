"""Live checks against the real Qloo API. They spend quota, so they run only when asked:

    NIGIWAI_RUN_LIVE=1 uv run pytest packages/qloo-guard/tests/live -m live -v

Every assertion states a behaviour the Guard's rules depend on. Nothing recorded here is committed: results are
asserted in memory only, never written to disk.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from qloo_guard import (
    AreaRef,
    ArtistInsights,
    EntitiesRequest,
    EntityType,
    GeoPoint,
    PlaceCategory,
    PlaceInsights,
    QlooConfig,
    SearchRequest,
    build_guard,
    read_key,
)
from qloo_guard.errors import RuleRejected  # noqa: F401  (documents the rejection path)

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("NIGIWAI_RUN_LIVE") != "1", reason="set NIGIWAI_RUN_LIVE=1 to spend quota"
    ),
]

ROOT = Path(__file__).resolve().parents[4]
KEY_FILE = os.environ.get("NIGIWAI_QLOO_KEY_FILE", str(Path.home() / ".secrets" / "qloo.env"))
NYC = AreaRef(center=GeoPoint(lat=40.7203, lon=-73.9985), radius_m=1500)


def make(transport: str):
    cfg = QlooConfig(
        key_file=KEY_FILE,
        transport=transport,
        harness_home=str(ROOT / ".qloo-home"),
        rate_per_second=4.0,
        burst=4,
    )
    assert read_key(cfg), "no Qloo key found"
    return build_guard(cfg)


@pytest.fixture
def rest():
    return make("rest")


@pytest.fixture
def harness():
    return make("harness")


async def test_rest_search_returns_musicbrainz_id(rest) -> None:
    res = await rest.search(
        SearchRequest(query="Radiohead", types=(EntityType.ARTIST,), take=3),
        rest.new_context("system"),
    )
    assert res.status == "ok" and res.transport == "rest"
    top = res.items[0]
    assert top.name == "Radiohead" and top.musicbrainz_id, "Qloo artists carry a MusicBrainz id"


async def test_harness_and_rest_agree_on_search(rest, harness) -> None:
    req = SearchRequest(query="Fleetwood Mac", types=(EntityType.ARTIST,), take=3)
    a = await rest.search(req, rest.new_context("system"))
    b = await harness.search(req, harness.new_context("system"))
    assert b.transport == "harness"
    assert [e.entity_id for e in a.items] == [e.entity_id for e in b.items]


async def test_empty_search_is_empty(rest) -> None:
    res = await rest.search(
        SearchRequest(query="zzqxqxqzzq", types=(EntityType.ARTIST,)), rest.new_context("system")
    )
    assert res.status == "empty"


@pytest.mark.parametrize("category", list(PlaceCategory))
async def test_each_place_category_tag_returns_places(rest, category: PlaceCategory) -> None:
    """The category tag urns in PlaceCategory must select real places (a wrong namespace returns nothing)."""
    res = await rest.insights(
        PlaceInsights(area=NYC, category=category, take=10), rest.new_context("system")
    )
    assert res.status in ("ok", "degraded"), f"{category.name}: {res.status} {res.rule_events}"
    assert res.items, f"{category.name} returned no places"
    assert all((e.distance_m or 0) <= NYC.radius_m * 1.02 for e in res.items)


async def test_harness_places_match_rest_ids(rest, harness) -> None:
    req = PlaceInsights(area=NYC, category=PlaceCategory.BAR, take=8)
    a = await rest.insights(req, rest.new_context("system"))
    b = await harness.insights(req, harness.new_context("system"))
    assert b.transport == "harness"
    assert {e.entity_id for e in a.items} == {e.entity_id for e in b.items}


async def test_take_above_fifty_is_refused_before_the_call(rest) -> None:
    with pytest.raises(ValueError, match="less than or equal to 50"):
        ArtistInsights(take=51)


async def test_probe_accepts_an_artist_and_registry_allows_it_as_a_seed(rest) -> None:
    ctx = rest.new_context("system")
    found = await rest.search(
        SearchRequest(query="Radiohead", types=(EntityType.ARTIST,), take=1), ctx
    )
    assert await rest.probe_eligibility(found.items[0], ctx) is True
    res = await rest.insights(
        ArtistInsights(signal_entities=(found.items[0].entity_id,), take=5), ctx
    )
    assert res.status in ("ok", "degraded") and res.items
    assert all(e.entity_id != found.items[0].entity_id for e in res.items)
    assert all(e.affinity is not None for e in res.items)


async def test_entities_batch_returns_closure_flag(rest) -> None:
    ctx = rest.new_context("system")
    places = await rest.insights(PlaceInsights(area=NYC, category=PlaceCategory.BAR, take=3), ctx)
    ids = tuple(e.entity_id for e in places.items)
    res = await rest.entities(EntitiesRequest(entity_ids=ids), ctx)
    assert res.status == "ok" and len(res.items) >= 1
    assert all(e.is_closed is not None for e in res.items)


async def test_rest_reports_rate_limit_headers_to_the_ledger(rest) -> None:
    await rest.search(
        SearchRequest(query="Radiohead", types=(EntityType.ARTIST,), take=1),
        rest.new_context("system"),
    )
    remaining = rest._ledger.month_remaining_last  # recorded from X-Month-RateLimit-Remaining
    assert remaining is not None and remaining > 0
