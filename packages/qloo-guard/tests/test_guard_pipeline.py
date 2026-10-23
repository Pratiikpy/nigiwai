"""The Guard pipeline against a scripted transport: cache, replay, budgets, retries, rules, fallback."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from qloo_guard import (
    AreaRef,
    ArtistInsights,
    CompareRequest,
    DemographicsRequest,
    EntitiesRequest,
    EntityType,
    GeoPoint,
    PlaceCategory,
    PlaceInsights,
    QlooAuthError,
    QlooConfig,
    ReplayMiss,
    SearchRequest,
    TagsRequest,
    TransportError,
)
from qloo_guard.transports.base import RawResponse

from .conftest import (
    FakeTransport,
    artist_raw,
    insights_artist_raw,
    insights_body,
    make_id,
    ok,
    place_raw,
    search_body,
)

AREA = AreaRef(center=GeoPoint(lat=40.72, lon=-73.99), radius_m=1500)


def search_req(q: str = "Lantern Hollow") -> SearchRequest:
    return SearchRequest(query=q, types=(EntityType.ARTIST,))


async def test_search_returns_trimmed_entities_and_registers_them(make_rig: Any) -> None:
    raw = artist_raw("Lantern Hollow")
    rig = make_rig(FakeTransport(respond=lambda p, q: ok(search_body(raw))))
    res = await rig.guard.search(search_req(), rig.guard.new_context("picker"))
    assert res.status == "ok" and res.cache == "miss"
    assert [e.name for e in res.items] == ["Lantern Hollow"]
    assert res.items[0].musicbrainz_id == "mb-1"
    assert (await rig.registry.get(raw["entity_id"])) is not None
    assert res.result_entity_ids == [raw["entity_id"]]


async def test_second_identical_call_is_a_cache_hit_and_refunds_the_budget(make_rig: Any) -> None:
    rig = make_rig(FakeTransport(respond=lambda p, q: ok(search_body(artist_raw()))))
    ctx = rig.guard.new_context("picker")
    first = await rig.guard.search(search_req(), ctx)
    used_after_first = ctx.budget.used
    second = await rig.guard.search(search_req(), ctx)
    assert first.cache == "miss" and second.cache == "hit"
    assert len(rig.transport.calls) == 1
    assert ctx.budget.used == used_after_first  # a cache hit costs nothing


async def test_single_flight_coalesces_identical_concurrent_requests(make_rig: Any) -> None:
    gate = asyncio.Event()

    class Slow(FakeTransport):
        async def get(self, path: str, params: Any) -> RawResponse:
            self.calls.append((path, list(params)))
            await gate.wait()
            return ok(search_body(artist_raw()))

    rig = make_rig(Slow())
    tasks = [
        asyncio.create_task(rig.guard.search(search_req(), rig.guard.new_context("picker")))
        for _ in range(5)
    ]
    await asyncio.sleep(0.05)
    gate.set()
    results = await asyncio.gather(*tasks)
    assert len(rig.transport.calls) == 1
    assert all(r.status == "ok" for r in results)


async def test_empty_search_is_empty_not_an_error(make_rig: Any) -> None:
    """Trap 14: a miss returns 200 with no results, or 404 on some endpoints."""
    rig = make_rig(FakeTransport(respond=lambda p, q: ok(search_body())))
    res = await rig.guard.search(search_req("Radiohed"), rig.guard.new_context("picker"))
    assert res.status == "empty" and res.items == []
    rig2 = make_rig(
        FakeTransport(respond=lambda p, q: RawResponse(status=404, body=None, transport="rest"))
    )
    res2 = await rig2.guard.search(search_req("zzz"), rig2.guard.new_context("picker"))
    assert res2.status == "empty"


async def test_search_drops_wrong_types_and_duplicates(make_rig: Any) -> None:
    keep = artist_raw("Lantern Hollow")
    dup = artist_raw("lantern hollow")  # same name, different id
    wrong = {**artist_raw("Some Film"), "types": ["urn:entity:movie"]}
    person = {**artist_raw("A Director"), "types": ["urn:entity:person"]}
    rig = make_rig(FakeTransport(respond=lambda p, q: ok(search_body(keep, dup, wrong, person))))
    res = await rig.guard.search(search_req(), rig.guard.new_context("picker"))
    assert [e.name for e in res.items] == ["Lantern Hollow"]
    rules = {e.rule for e in res.rule_events}
    assert {"T18-type", "T18-name"} <= rules
    assert (await rig.registry.get(person["entity_id"])) is None  # persons never enter the registry


async def test_replay_serves_recorded_responses_and_fails_closed(make_rig: Any) -> None:
    rig = make_rig(FakeTransport(respond=lambda p, q: ok(search_body(artist_raw()))))
    await rig.guard.search(search_req(), rig.guard.new_context("picker"))
    calls_before = len(rig.transport.calls)
    replayed = await rig.guard.search(search_req(), rig.guard.new_context("picker", mode="replay"))
    assert replayed.cache == "replay" and replayed.status == "ok"
    with pytest.raises(ReplayMiss):
        await rig.guard.search(
            search_req("never recorded"), rig.guard.new_context("picker", mode="replay")
        )
    assert len(rig.transport.calls) == calls_before  # replay never falls through to live


async def test_trace_budget_blocks_the_call_after_the_cap(make_rig: Any) -> None:
    rig = make_rig(FakeTransport(respond=lambda p, q: ok(search_body(artist_raw()))))
    ctx = rig.guard.new_context("card")  # cap 3
    for i in range(3):
        assert (await rig.guard.search(search_req(f"q{i}"), ctx)).status == "ok"
    blocked = await rig.guard.search(search_req("q4"), ctx)
    assert blocked.status == "budget_exhausted"
    assert len(rig.transport.calls) == 3


async def test_month_floor_stops_non_system_classes(make_rig: Any) -> None:
    body = search_body(artist_raw())
    rig = make_rig(
        FakeTransport(
            respond=lambda p, q: ok(body, headers={"x-month-ratelimit-remaining": "1500"})
        )
    )
    first = await rig.guard.search(search_req("a"), rig.guard.new_context("ask"))
    assert first.status == "ok"
    second = await rig.guard.search(search_req("b"), rig.guard.new_context("ask"))
    assert second.status == "budget_exhausted"
    system = await rig.guard.search(search_req("c"), rig.guard.new_context("system"))
    assert system.status == "ok"  # the incident class may still call


async def test_class_share_runs_out(make_rig: Any) -> None:
    cfg = QlooConfig(
        rate_per_second=1000.0, burst=1000, month_limit=100, class_shares={"board": 0.02}
    )
    rig = make_rig(FakeTransport(respond=lambda p, q: ok(search_body(artist_raw()))), cfg=cfg)
    assert (await rig.guard.search(search_req("a"), rig.guard.new_context("board"))).status == "ok"
    assert (await rig.guard.search(search_req("b"), rig.guard.new_context("board"))).status == "ok"
    assert (
        await rig.guard.search(search_req("c"), rig.guard.new_context("board"))
    ).status == "budget_exhausted"


async def test_400_is_rejected_and_not_retried(make_rig: Any) -> None:
    rig = make_rig(
        FakeTransport(respond=lambda p, q: RawResponse(status=400, body=None, transport="rest"))
    )
    res = await rig.guard.search(search_req(), rig.guard.new_context("picker"))
    assert res.status == "rejected"
    assert len(rig.transport.calls) == 1


async def test_429_waits_and_retries_at_most_twice(make_rig: Any) -> None:
    t = FakeTransport(respond=lambda p, q: ok(search_body(artist_raw())))
    limited = RawResponse(
        status=429, body=None, headers={"x-second-ratelimit-reset": "1"}, transport="rest"
    )
    t.queue = [limited, limited, ok(search_body(artist_raw()))]
    rig = make_rig(t)
    res = await rig.guard.search(search_req(), rig.guard.new_context("picker"))
    assert res.status == "ok" and len(t.calls) == 3
    t2 = FakeTransport(respond=lambda p, q: limited)
    rig2 = make_rig(t2)
    res2 = await rig2.guard.search(search_req(), rig2.guard.new_context("picker"))
    assert res2.status == "unavailable" and len(t2.calls) == 3  # 1 try + 2 retries


async def test_5xx_retries_once_then_gives_up(make_rig: Any) -> None:
    t = FakeTransport(respond=lambda p, q: RawResponse(status=503, body=None, transport="rest"))
    rig = make_rig(t)
    res = await rig.guard.search(search_req(), rig.guard.new_context("picker"))
    assert res.status == "unavailable" and len(t.calls) == 2


async def test_timeout_retries_once(make_rig: Any) -> None:
    t = FakeTransport(respond=lambda p, q: ok(search_body(artist_raw())))
    t.queue = [TransportError("timed out", retryable=True)]
    rig = make_rig(t)
    res = await rig.guard.search(search_req(), rig.guard.new_context("picker"))
    assert res.status == "ok" and len(t.calls) == 2


async def test_auth_errors_are_never_retried_and_propagate(make_rig: Any) -> None:
    t = FakeTransport()
    t.queue = [QlooAuthError("rejected", 401)]
    rig = make_rig(t)
    with pytest.raises(QlooAuthError):
        await rig.guard.search(search_req(), rig.guard.new_context("picker"))
    assert len(t.calls) == 1


async def test_circuit_opens_after_repeated_failures(make_rig: Any) -> None:
    t = FakeTransport(respond=lambda p, q: RawResponse(status=500, body=None, transport="rest"))
    rig = make_rig(t)
    for i in range(6):
        await rig.guard.search(search_req(f"q{i}"), rig.guard.new_context("picker"))
    calls_when_open = len(t.calls)
    res = await rig.guard.search(search_req("after"), rig.guard.new_context("picker"))
    assert res.status == "unavailable"
    assert len(t.calls) == calls_when_open  # circuit open: no call was made


async def test_latency_critical_purposes_go_to_rest_first(make_rig: Any) -> None:
    harness = FakeTransport(
        name="harness", respond=lambda p, q: ok(search_body(artist_raw()), transport="harness")
    )
    rest = FakeTransport(name="rest", respond=lambda p, q: ok(search_body(artist_raw())))
    rig = make_rig(transports=[harness, rest])
    typed = await rig.guard.search(search_req("typed"), rig.guard.new_context("picker"))
    assert typed.transport == "rest" and len(harness.calls) == 0
    asked = await rig.guard.search(search_req("asked"), rig.guard.new_context("ask"))
    assert (
        asked.transport == "harness" and len(rest.calls) == 1
    )  # other purposes keep the harness first


async def test_picker_falls_back_to_the_harness_when_rest_fails(make_rig: Any) -> None:
    rest = FakeTransport(name="rest")
    rest.queue = [TransportError("rest down", retryable=False)]
    harness = FakeTransport(
        name="harness", respond=lambda p, q: ok(search_body(artist_raw()), transport="harness")
    )
    rig = make_rig(transports=[harness, rest])
    res = await rig.guard.search(search_req(), rig.guard.new_context("picker"))
    assert res.status == "ok" and res.transport == "harness"


async def test_harness_failure_falls_back_to_rest(make_rig: Any) -> None:
    harness = FakeTransport(name="harness")
    harness.queue = [TransportError("harness exited 1", retryable=False)]
    rest = FakeTransport(name="rest", respond=lambda p, q: ok(search_body(artist_raw())))
    rig = make_rig(transports=[harness, rest])
    res = await rig.guard.search(search_req(), rig.guard.new_context("ask"))
    assert res.status == "ok" and res.transport == "rest"
    assert any(e.rule == "transport" and "rest" in e.detail for e in res.rule_events)


async def test_transport_selection_respects_capability(make_rig: Any) -> None:
    harness = FakeTransport(
        name="harness",
        respond=lambda p, q: ok(insights_body()),
        supports=lambda p, q: "signal.interests.entities" not in dict(q),
    )
    rest = FakeTransport(
        name="rest", respond=lambda p, q: ok(insights_body(insights_artist_raw("Other", 0.8)))
    )
    rig = make_rig(transports=[harness, rest])
    seed = await rig.known(make_id())
    seeded = await rig.guard.insights(
        ArtistInsights(signal_entities=(seed,), take=5), rig.guard.new_context("ask")
    )
    assert (
        seeded.transport == "rest" and len(harness.calls) == 0
    )  # seeded insights need REST (warnings, headers)


# ---- pre-rules against the registry -------------------------------------------------------------------------
async def test_unregistered_seed_is_rejected_before_any_call(make_rig: Any) -> None:
    rig = make_rig(FakeTransport(respond=lambda p, q: ok(insights_body())))
    res = await rig.guard.insights(
        ArtistInsights(signal_entities=(make_id(),), take=5), rig.guard.new_context("ask")
    )
    assert res.status == "rejected" and any(e.rule == "T13-unregistered" for e in res.rule_events)
    assert rig.transport.calls == []


async def test_person_seed_is_rejected(make_rig: Any) -> None:
    """Trap 12: person seeds fail alone and are silently dropped in combinations."""
    rig = make_rig(FakeTransport(respond=lambda p, q: ok(insights_body())))
    person = await rig.known(make_id(), types=("urn:entity:person",), name="A Director")
    res = await rig.guard.insights(
        ArtistInsights(signal_entities=(person,), take=5), rig.guard.new_context("ask")
    )
    assert res.status == "rejected" and any(e.rule == "T12-person" for e in res.rule_events)
    assert rig.transport.calls == []


async def test_ineligible_and_unprobed_seeds_are_rejected(make_rig: Any) -> None:
    """Trap 13: a search hit that insights rejects must never become a signal."""
    rig = make_rig(FakeTransport(respond=lambda p, q: ok(insights_body())))
    bad = await rig.known(make_id(), name="Normal People", eligible=False)
    unprobed = await rig.known(make_id(), name="Unprobed", eligible=None)
    r1 = await rig.guard.insights(
        ArtistInsights(signal_entities=(bad,), take=5), rig.guard.new_context("ask")
    )
    r2 = await rig.guard.insights(
        ArtistInsights(signal_entities=(unprobed,), take=5), rig.guard.new_context("ask")
    )
    assert r1.status == r2.status == "rejected"
    assert {e.rule for e in r1.rule_events + r2.rule_events} == {"T13-ineligible"}


async def test_probe_marks_eligibility_from_the_insights_answer(make_rig: Any) -> None:
    def respond(path: str, params: Any) -> RawResponse:
        return ok(insights_body(insights_artist_raw("Neighbour", 0.9)))

    rig = make_rig(FakeTransport(respond=respond))
    raw = artist_raw("Lantern Hollow")
    res = await rig.guard.search(search_req(), rig.guard.new_context("picker"))
    e = res.items[0]
    assert (await rig.registry.get(e.entity_id)).eligible is None
    assert await rig.guard.probe_eligibility(e, rig.guard.new_context("picker")) is True
    assert (await rig.registry.get(e.entity_id)).eligible is True
    # a 400 from insights means ineligible
    rig2 = make_rig(
        FakeTransport(respond=lambda p, q: RawResponse(status=400, body=None, transport="rest"))
    )
    rig2.transport._respond = lambda p, q: (
        ok(search_body(raw))
        if p == "/search"
        else RawResponse(status=400, body=None, transport="rest")
    )
    res2 = await rig2.guard.search(search_req("x"), rig2.guard.new_context("picker"))
    assert (
        await rig2.guard.probe_eligibility(res2.items[0], rig2.guard.new_context("picker")) is False
    )
    assert (await rig2.registry.get(res2.items[0].entity_id)).eligible is False


async def test_probe_result_is_cached_for_ninety_days(make_rig: Any) -> None:
    rig = make_rig(
        FakeTransport(
            respond=lambda p, q: (
                ok(search_body(artist_raw()))
                if p == "/search"
                else ok(insights_body(insights_artist_raw("N", 0.5)))
            )
        )
    )
    res = await rig.guard.search(search_req(), rig.guard.new_context("picker"))
    await rig.guard.probe_eligibility(res.items[0], rig.guard.new_context("picker"))
    probes = [s for s in rig.store._items.values() if s.endpoint == "/v2/insights"]
    assert probes and (probes[0].expires_at - probes[0].fetched_at) == 90 * 86_400


# ---- post-rules ---------------------------------------------------------------------------------------------
async def test_seed_is_removed_from_its_own_results(make_rig: Any) -> None:
    seed_raw = insights_artist_raw("Seed", 0.99)
    other = insights_artist_raw("Neighbour", 0.8)
    rig = make_rig(FakeTransport(respond=lambda p, q: ok(insights_body(seed_raw, other))))
    seed = await rig.known(seed_raw["entity_id"])
    res = await rig.guard.insights(
        ArtistInsights(signal_entities=(seed,), take=5), rig.guard.new_context("ask")
    )
    assert [e.name for e in res.items] == ["Neighbour"]
    assert any(e.rule == "T18-seed" for e in res.rule_events)


async def test_dropped_seed_warning_marks_the_result_degraded(make_rig: Any) -> None:
    """Trap 12: Qloo drops a seed it cannot use and only says so in `warnings`."""
    seed = make_id()
    body = insights_body(
        insights_artist_raw("Neighbour", 0.8),
        warnings=[{"type": "not_found", "signal.interests.entities": [seed]}],
    )
    rig = make_rig(FakeTransport(respond=lambda p, q: ok(body)))
    await rig.known(seed)
    res = await rig.guard.insights(
        ArtistInsights(signal_entities=(seed,), take=5), rig.guard.new_context("ask")
    )
    assert res.status == "degraded"
    assert res.warnings[0].type == "not_found" and res.warnings[0].entity_ids() == (seed,)
    assert any(e.rule == "T12-dropped-seed" for e in res.rule_events)


async def test_flat_affinity_is_flagged(make_rig: Any) -> None:
    """Trap 7: a wrong-namespace tag gives the same affinity to everything."""
    items = [insights_artist_raw(f"A{i}", 0.765) for i in range(4)]
    rig = make_rig(FakeTransport(respond=lambda p, q: ok(insights_body(*items))))
    seed = await rig.known(make_id())
    res = await rig.guard.insights(
        ArtistInsights(signal_entities=(seed,), take=5), rig.guard.new_context("ask")
    )
    assert res.status == "degraded" and any(e.rule == "T7-flat-affinity" for e in res.rule_events)


async def test_zero_results_with_a_tag_filter_is_flagged(make_rig: Any) -> None:
    from qloo_guard import TagRef

    rig = make_rig(FakeTransport(respond=lambda p, q: ok(insights_body())))
    seed = await rig.known(make_id())
    req = ArtistInsights(
        signal_entities=(seed,), filter_tags=(TagRef(tag_id="urn:tag:genre:media:comedy"),), take=5
    )
    res = await rig.guard.insights(req, rig.guard.new_context("ask"))
    assert res.status == "empty" and any(e.rule == "T7-zero-with-tags" for e in res.rule_events)


async def test_places_outside_the_area_are_dropped(make_rig: Any) -> None:
    near = place_raw("Near Bar", 400)
    far = place_raw("Far Bar", 9000)
    rig = make_rig(FakeTransport(respond=lambda p, q: ok(insights_body(near, far))))
    res = await rig.guard.insights(
        PlaceInsights(area=AREA, category=PlaceCategory.BAR, take=10), rig.guard.new_context("ask")
    )
    assert [e.name for e in res.items] == ["Near Bar"]
    assert any(e.rule == "T17-area" for e in res.rule_events)


async def test_place_containment_falls_back_to_coordinates_and_drops_unverifiable(
    make_rig: Any,
) -> None:
    no_distance = {**place_raw("Coords Only", 0), "query": {}}
    nothing = {**place_raw("Nothing", 0), "query": {}, "location": None}
    rig = make_rig(FakeTransport(respond=lambda p, q: ok(insights_body(no_distance, nothing))))
    res = await rig.guard.insights(PlaceInsights(area=AREA, take=10), rig.guard.new_context("ask"))
    assert [e.name for e in res.items] == ["Coords Only"]
    assert any(e.rule == "T17-unverifiable" for e in res.rule_events)


async def test_category_leakage_is_removed(make_rig: Any) -> None:
    """Rule G26: hotels and arenas leak into bar lists."""
    bar = place_raw("Real Bar", 100)
    hotel = place_raw(
        "Grand Hotel", 100, tags=["urn:tag:category:place:bar", "urn:tag:category:place:hotel"]
    )
    rig = make_rig(FakeTransport(respond=lambda p, q: ok(insights_body(bar, hotel))))
    res = await rig.guard.insights(
        PlaceInsights(area=AREA, category=PlaceCategory.BAR, take=10), rig.guard.new_context("ask")
    )
    assert [e.name for e in res.items] == ["Real Bar"]
    assert any(e.rule == "G26" for e in res.rule_events)


async def test_results_are_cut_to_take(make_rig: Any) -> None:
    items = [insights_artist_raw(f"A{i}", 0.9 - i / 100) for i in range(10)]
    rig = make_rig(FakeTransport(respond=lambda p, q: ok(insights_body(*items))))
    seed = await rig.known(make_id())
    res = await rig.guard.insights(
        ArtistInsights(signal_entities=(seed,), take=3), rig.guard.new_context("ask")
    )
    assert len(res.items) == 3


# ---- other endpoints ----------------------------------------------------------------------------------------
async def test_entities_batch_registers_and_reads_is_closed(make_rig: Any) -> None:
    p = place_raw("Venue", 0)
    p["properties"]["is_closed"] = True
    p["types"] = ["urn:entity:place"]
    rig = make_rig(FakeTransport(respond=lambda path, q: ok({"results": [p]})))
    res = await rig.guard.entities(
        EntitiesRequest(entity_ids=(p["entity_id"],)), rig.guard.new_context("ask")
    )
    assert res.items[0].is_closed is True


async def test_compare_drops_country_tags_and_cuts_to_twenty(make_rig: Any) -> None:
    tags = [
        {
            "tag_id": f"urn:tag:genre:qloo:g{i}",
            "name": f"G{i}",
            "subtype": "urn:tag:genre:qloo",
            "popularity": 0.1,
        }
        for i in range(30)
    ]
    tags.append(
        {
            "tag_id": "urn:tag:country:qloo:ie",
            "name": "Ireland",
            "subtype": "urn:tag:country:qloo",
            "popularity": 0.9,
        }
    )
    rig = make_rig(
        FakeTransport(respond=lambda p, q: ok({"results": {"tags": tags, "a": [], "b": []}}))
    )
    a, b = await rig.known(make_id()), await rig.known(make_id())
    res = await rig.guard.compare(CompareRequest(a=(a,), b=(b,)), rig.guard.new_context("ask"))
    assert len(res.items.shared_tags) == 20
    assert all("country" not in t.tag_id for t in res.items.shared_tags)


async def test_demographics_parse(make_rig: Any) -> None:
    seed = make_id()
    body = {
        "success": True,
        "results": {
            "demographics": [
                {
                    "entity_id": seed,
                    "query": {
                        "age": {"24_and_younger": 0.5, "55_and_older": -0.5},
                        "gender": {"male": -0.2, "female": 0.2},
                    },
                }
            ]
        },
    }
    rig = make_rig(FakeTransport(respond=lambda p, q: ok(body)))
    await rig.known(seed)
    res = await rig.guard.demographics(
        DemographicsRequest(signal_entities=(seed,)), rig.guard.new_context("board")
    )
    assert res.items[0].gender["female"] == 0.2


async def test_tags_parse(make_rig: Any) -> None:
    body = {
        "success": True,
        "results": {
            "tags": [
                {
                    "id": "urn:tag:genre:music:jazz",
                    "name": "Jazz",
                    "type": "urn:tag:genre:music",
                    "popularity": 0.99,
                }
            ]
        },
    }
    rig = make_rig(FakeTransport(respond=lambda p, q: ok(body)))
    res = await rig.guard.tags(TagsRequest(query="jazz"), rig.guard.new_context("ask"))
    assert res.items[0].tag_id == "urn:tag:genre:music:jazz"


# ---- trace --------------------------------------------------------------------------------------------------
async def test_every_call_is_recorded_with_ordered_result_ids_and_only_a_fingerprint(
    make_rig: Any,
) -> None:
    a, b = artist_raw("A"), artist_raw("B")
    rig = make_rig(FakeTransport(respond=lambda p, q: ok(search_body(a, b))))
    ctx = rig.guard.new_context("picker")
    await rig.guard.search(search_req(), ctx)
    await rig.guard.search(search_req(), ctx)  # cache hit is recorded too
    calls = rig.recorder.for_trace(ctx.trace_id)
    assert len(calls) == 2
    assert calls[0].result_entity_ids == [a["entity_id"], b["entity_id"]]
    assert calls[0].cache == "miss" and calls[1].cache == "hit"
    assert calls[0].key_fingerprint == "abcd1234"


async def test_budget_exhaustion_is_recorded_not_raised(make_rig: Any) -> None:
    rig = make_rig(FakeTransport(respond=lambda p, q: ok(search_body(artist_raw()))))
    ctx = rig.guard.new_context("card")
    for i in range(4):
        await rig.guard.search(search_req(f"q{i}"), ctx)
    assert [c.status for c in rig.recorder.for_trace(ctx.trace_id)][-1] == "budget_exhausted"
