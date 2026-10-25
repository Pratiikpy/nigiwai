"""Request models: the serialiser owns parameter names, coordinate order and limits (traps 1 to 11, 17)."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError
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
    SearchRequest,
    TagRef,
    TagsRequest,
    Weekday,
)
from qloo_guard.requests import NEVER_EXPOSED, allowed_params

ID_A = "11111111-1111-4111-8111-111111111111"
ID_B = "22222222-2222-4222-8222-222222222222"
AREA = AreaRef(center=GeoPoint(lat=40.72, lon=-73.99), radius_m=1500)


def test_search_trims_query_and_requires_types() -> None:
    r = SearchRequest(query="  radio   head ", types=(EntityType.ARTIST, EntityType.BRAND))
    assert r.endpoint() == (
        "/search",
        [("query", "radio head"), ("types", "urn:entity:artist,urn:entity:brand"), ("take", "5")],
    )
    with pytest.raises(ValidationError):
        SearchRequest(query="x", types=())  # rule G20: types are required


@pytest.mark.parametrize(
    "urn", ["urn:entity:person", "urn:entity:actor", "urn:entity:director", "urn:entity:author"]
)
def test_person_like_types_are_never_searchable(urn: str) -> None:
    with pytest.raises(ValidationError):
        SearchRequest(query="x", types=(urn,))  # type: ignore[arg-type]


def test_search_page_is_only_sent_after_page_one() -> None:
    assert ("page", "2") in SearchRequest(query="x", types=(EntityType.ARTIST,), page=2).endpoint()[
        1
    ]
    assert all(
        k != "page" for k, _ in SearchRequest(query="x", types=(EntityType.ARTIST,)).endpoint()[1]
    )


def test_wkt_is_longitude_first() -> None:
    """Trap 9: a swapped POINT returns zero results. The serialiser owns the order."""
    assert GeoPoint(lat=40.72, lon=-73.99).to_wkt() == "POINT(-73.990000 40.720000)"
    path, params = PlaceInsights(area=AREA, take=5).endpoint()
    assert dict(params)["filter.location"] == "POINT(-73.990000 40.720000)"
    assert dict(params)["filter.location.radius"] == "1500"


def test_place_never_uses_location_query() -> None:
    """Trap 17: location.query resolves to the wrong area."""
    _, params = PlaceInsights(area=AREA).endpoint()
    assert "filter.location.query" not in dict(params)


def test_place_category_adds_its_tag_and_merges_with_filter_tags() -> None:
    extra = TagRef(tag_id="urn:tag:genre:place:live_music")
    _, params = PlaceInsights(
        area=AREA, category=PlaceCategory.BAR, filter_tags=(extra,)
    ).endpoint()
    assert (
        dict(params)["filter.tags"] == "urn:tag:genre:place:live_music,urn:tag:category:place:bar"
    )


def test_extra_fields_are_forbidden() -> None:
    """Trap 1: a misspelled parameter would be ignored with a 200; here it cannot be constructed."""
    with pytest.raises(ValidationError):
        ArtistInsights(signal_entities=(ID_A,), release_year_min=1990)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        ArtistInsights(signal_entities=(ID_A,), filter_pricelevel=2)  # type: ignore[call-arg]


def test_signal_tags_exist_on_places_only() -> None:
    """Trap 6: signal tags on other types return the wrong domain."""
    with pytest.raises(ValidationError):
        ArtistInsights(
            signal_entities=(ID_A,), signal_tags=(TagRef(tag_id="urn:tag:genre:qloo:folk"),)
        )  # type: ignore[call-arg]
    PlaceInsights(area=AREA, signal_tags=(TagRef(tag_id="urn:tag:genre:place:live_music"),))


def test_take_and_page_caps() -> None:
    """Rule G19: take=51 returns 400."""
    with pytest.raises(ValidationError):
        ArtistInsights(signal_entities=(ID_A,), take=51)
    with pytest.raises(ValidationError):
        ArtistInsights(signal_entities=(ID_A,), page=5)
    assert ArtistInsights(signal_entities=(ID_A,), take=50).take == 50


def test_ids_must_be_qloo_uuids_and_unique() -> None:
    with pytest.raises(ValidationError):
        ArtistInsights(signal_entities=("not-an-id",))
    with pytest.raises(ValidationError):
        ArtistInsights(signal_entities=(ID_A, ID_A))
    with pytest.raises(ValidationError):
        ArtistInsights(signal_entities=(ID_A,), exclude_entities=(ID_A,))


def test_results_entities_needs_a_signal() -> None:
    """Rule G21: checked locally to save a call."""
    with pytest.raises(ValidationError):
        ArtistInsights(results_entities=(ID_A,))
    _, params = ArtistInsights(signal_entities=(ID_B,), results_entities=(ID_A,)).endpoint()
    assert dict(params)["filter.results.entities"] == ID_A


def test_explainability_needs_signal_entities() -> None:
    with pytest.raises(ValidationError):
        ArtistInsights(explainability=True)
    _, params = ArtistInsights(signal_entities=(ID_A,), explainability=True).endpoint()
    assert dict(params)["feature.explainability"] == "true"


def test_popularity_bounds() -> None:
    with pytest.raises(ValidationError):
        ArtistInsights(signal_entities=(ID_A,), popularity_min=0.5, popularity_max=0.2)
    _, params = ArtistInsights(signal_entities=(ID_A,), popularity_max=0.25).endpoint()
    assert dict(params)["filter.popularity.max"] == "0.25"


def test_weekday_is_an_enum() -> None:
    """Trap 10: filter.hours=Sundae returns zero."""
    with pytest.raises(ValidationError):
        PlaceInsights(area=AREA, hours="Sundae")  # type: ignore[arg-type]
    _, params = PlaceInsights(area=AREA, hours=Weekday.SUNDAY).endpoint()
    assert dict(params)["filter.hours"] == "Sunday"


def test_price_level_range() -> None:
    with pytest.raises(ValidationError):
        PlaceInsights(area=AREA, price_level_min=0)
    with pytest.raises(ValidationError):
        PlaceInsights(area=AREA, price_level_min=3, price_level_max=2)


def test_demographics_needs_a_signal() -> None:
    with pytest.raises(ValidationError):
        DemographicsRequest(signal_entities=())
    path, params = DemographicsRequest(signal_entities=(ID_A,)).endpoint()
    assert (path, dict(params)["filter.type"]) == ("/v2/insights", "urn:demographics")


def test_compare_never_sends_take() -> None:
    """Rule G22."""
    _, params = CompareRequest(a=(ID_A,), b=(ID_B,)).endpoint()
    assert {k for k, _ in params} == {"a.signal.interests.entities", "b.signal.interests.entities"}


def test_entities_batch_param_name() -> None:
    path, params = EntitiesRequest(entity_ids=(ID_A, ID_B)).endpoint()
    assert (path, params) == ("/entities", [("entity_ids", f"{ID_A},{ID_B}")])


def test_tags_query_param_name() -> None:
    """Tags use filter.query, not q."""
    assert TagsRequest(query="jazz").endpoint()[1][0] == ("filter.query", "jazz")


def test_geopoint_range_checks() -> None:
    with pytest.raises(ValidationError):
        GeoPoint(lat=91, lon=0)
    with pytest.raises(ValidationError):
        GeoPoint(lat=0, lon=181)


def test_never_exposed_parameters_are_not_in_any_emitted_request() -> None:
    reqs = [
        ArtistInsights(signal_entities=(ID_A,), popularity_max=0.3, explainability=True),
        PlaceInsights(
            area=AREA, category=PlaceCategory.BAR, hours=Weekday.FRIDAY, sort_by_distance=True
        ),
    ]
    for r in reqs:
        names = {k for k, _ in r.endpoint()[1]}
        assert not names & set(NEVER_EXPOSED)
        assert names <= allowed_params(r.entity_type.value)


def test_documented_table_covers_every_type() -> None:
    for t in EntityType:
        assert "filter.type" in allowed_params(t.value) or allowed_params(t.value), t


@given(
    lat=st.floats(min_value=-90, max_value=90, allow_nan=False),
    lon=st.floats(min_value=-180, max_value=180, allow_nan=False),
)
def test_wkt_round_trips_longitude_first(lat: float, lon: float) -> None:
    wkt = GeoPoint(lat=lat, lon=lon).to_wkt()
    inner = wkt[len("POINT(") : -1].split(" ")
    assert abs(float(inner[0]) - lon) < 1e-5
    assert abs(float(inner[1]) - lat) < 1e-5


@given(st.permutations([("a", "1"), ("b", "2"), ("c", "3")]))
def test_cache_key_ignores_parameter_order(perm: list[tuple[str, str]]) -> None:
    from qloo_guard.canonical import cache_key

    base = cache_key("https://h", "/x", [("a", "1"), ("b", "2"), ("c", "3")])
    assert cache_key("https://h", "/x", list(perm)) == base
    assert cache_key("https://other", "/x", list(perm)) != base


def test_a_search_for_places_can_be_biased_to_a_point_written_latitude_first() -> None:
    """/search takes "lat,lon" (insights takes WKT, longitude first): a swapped pair would bias the search to the wrong ocean."""
    r = SearchRequest(
        query="corner tap",
        types=(EntityType.PLACE,),
        near=GeoPoint(lat=40.72224, lon=-73.98716),
        take=8,
    )
    path, params = r.endpoint()
    assert path == "/search"
    assert dict(params) == {
        "query": "corner tap",
        "types": "urn:entity:place",
        "take": "8",
        "filter.location": "40.7222,-73.9872",  # rounded to four places: one venue, one cache key
    }


@pytest.mark.parametrize(
    "types",
    [
        (EntityType.ARTIST,),
        (EntityType.PLACE, EntityType.ARTIST),
        (EntityType.BRAND, EntityType.PLACE),
    ],
)
def test_a_point_is_refused_for_anything_but_a_search_for_places_alone(
    types: tuple[EntityType, ...],
) -> None:
    """Qloo drops every non-place type from a search that has a point, so the request refuses to be built."""
    with pytest.raises(ValidationError, match="only be given to a search for places"):
        SearchRequest(query="x", types=types, near=GeoPoint(lat=1, lon=2))


def test_a_search_without_a_point_sends_no_location() -> None:
    params = SearchRequest(query="x", types=(EntityType.PLACE,)).endpoint()[1]
    assert all(k != "filter.location" for k, _ in params)


@pytest.mark.parametrize(("lat", "lon"), [(91, 0), (-91, 0), (0, 181), (0, -181)])
def test_a_point_outside_the_globe_cannot_be_built(lat: float, lon: float) -> None:
    with pytest.raises(ValidationError):
        GeoPoint(lat=lat, lon=lon)
