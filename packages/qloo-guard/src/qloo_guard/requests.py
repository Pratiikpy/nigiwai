"""Typed requests. Each model has `extra="forbid"` and builds its own query parameters, so a typo, an unsupported
parameter or a hand-built coordinate string cannot be sent (traps 1, 2, 3, 4, 5, 6, 9, 10, 11, 15, 17).

The per-type parameter table comes from Qloo's public docs (data/params_by_type.json). Anything the Guard
exposes must be in that table or in `VERIFIED_LIVE_EXTRAS`, which lists parameters confirmed by live tests
that the docs table does not list.
"""

from __future__ import annotations

import json
from enum import StrEnum
from functools import lru_cache
from importlib import resources
from typing import ClassVar, Literal

from pydantic import Field, field_validator, model_validator

from .models import (
    PICKER_TYPES,
    AreaRef,
    EntityType,
    FrozenModel,
    GeoPoint,
    TagRef,
    is_forbidden_type,
    is_qloo_id,
)

Params = list[tuple[str, str]]

TAKE_MAX = 50  # rule G19: take=51 returns 400
PAGE_MAX = 4  # rule G19
SIGNAL_MAX = 20

# Parameters confirmed by live tests (QLOO_TESTS.md 5.4, 5.6) that the docs table does not list.
VERIFIED_LIVE_EXTRAS: dict[str, frozenset[str]] = {
    "urn:entity:place": frozenset(
        {"sort_by", "diversify.by", "diversify.take", "feature.explainability"}
    ),
}
COMMON_EXTRAS = frozenset({"feature.explainability", "page"})


@lru_cache(maxsize=1)
def _docs_table() -> dict[str, frozenset[str]]:
    raw = json.loads(
        resources.files("qloo_guard")
        .joinpath("data/params_by_type.json")
        .read_text(encoding="utf-8")
    )
    return {t: frozenset(v) for t, v in raw["types"].items()}


def documented_params(entity_type: str) -> frozenset[str]:
    return _docs_table().get(entity_type, frozenset())


def allowed_params(entity_type: str) -> frozenset[str]:
    return (
        documented_params(entity_type)
        | VERIFIED_LIVE_EXTRAS.get(entity_type, frozenset())
        | COMMON_EXTRAS
    )


# Parameters the Guard refuses to expose, with the reason (each is a measured trap).
NEVER_EXPOSED: dict[str, str] = {
    "bias.trends": "trap 3: changes no ranks and returns 400 on videogames",
    "signal.demographics.audiences": "trap 4: lowers scores uniformly",
    "signal.demographics.audiences.weight": "trap 4",
    "signal.demographics.age": "traps 5 and proofs L, M: no effect on place rankings",
    "signal.demographics.gender": "proofs L, M: no effect on place rankings",
    "filter.location.query": "trap 17: resolves to the wrong area; use an AreaRef",
    "filter.geocode.name": "trap 17",
    "filter.properties.business_rating.min": "trap 10: has no effect",
    "filter.properties.business_rating.max": "trap 10",
    "filter.release_country": "trap 8: country codes return zero",
}


class Weekday(StrEnum):
    MONDAY = "Monday"
    TUESDAY = "Tuesday"
    WEDNESDAY = "Wednesday"
    THURSDAY = "Thursday"
    FRIDAY = "Friday"
    SATURDAY = "Saturday"
    SUNDAY = "Sunday"


class PlaceCategory(StrEnum):
    """Place categories and the tag that selects them (tag urns confirmed by live tests; see tests/live)."""

    BAR = "urn:tag:category:place:bar"
    CAFE = "urn:tag:category:place:cafe"
    RESTAURANT = "urn:tag:category:place:restaurant"
    COCKTAIL_BAR = "urn:tag:category:place:cocktail_bar"
    HOTEL = "urn:tag:category:place:hotel"


# Tags whose presence marks a place as a different category (rule G26: category leakage).
LEAKAGE_TAG_FRAGMENTS: dict[PlaceCategory, tuple[str, ...]] = {
    PlaceCategory.BAR: (
        "hotel",
        "lodging",
        "shopping_mall",
        "department_store",
        "stadium",
        "arena",
        "airport",
    ),
    PlaceCategory.COCKTAIL_BAR: (
        "hotel",
        "lodging",
        "shopping_mall",
        "department_store",
        "stadium",
        "arena",
    ),
    PlaceCategory.CAFE: ("hotel", "lodging", "stadium", "arena", "airport"),
    PlaceCategory.RESTAURANT: ("stadium", "arena", "airport"),
    PlaceCategory.HOTEL: (),
}


def _ids(values: tuple[str, ...], what: str, limit: int) -> None:
    if len(values) > limit:
        raise ValueError(f"{what}: at most {limit} ids")
    if len(set(values)) != len(values):
        raise ValueError(f"{what}: duplicate ids")
    for v in values:
        if not is_qloo_id(v):
            raise ValueError(f"{what}: {v!r} is not a Qloo entity id")


def _csv(values: tuple[str, ...]) -> str:
    return ",".join(values)


class SearchRequest(FrozenModel):
    """`/search`. `types` is required (rule G20) and never includes a person type (trap 12)."""

    query: str = Field(min_length=1, max_length=200)
    types: tuple[EntityType, ...] = Field(min_length=1, max_length=8)
    take: int = Field(default=5, ge=1, le=100)
    page: int = Field(default=1, ge=1, le=PAGE_MAX)
    # Places only. Qloo treats the point as a bias, not a bound: `filter.location.radius` changes nothing on /search (probed live,
    # 2026-10-25: the same 20 results from a radius of 300 m to 50 km), but an exact name near the point finds the branch near it.
    # A mixed-type search with a point drops every non-place type (QLOO_TESTS.md 5.4), so a point is refused for any other type.
    near: GeoPoint | None = None

    @field_validator("query")
    @classmethod
    def _strip(cls, v: str) -> str:
        s = " ".join(v.split())
        if not s:
            raise ValueError("query is empty")
        return s

    @field_validator("types")
    @classmethod
    def _no_person(cls, v: tuple[EntityType, ...]) -> tuple[EntityType, ...]:
        if any(is_forbidden_type(t.value) for t in v):
            raise ValueError("person-like types are not searchable")
        if len(set(v)) != len(v):
            raise ValueError("duplicate types")
        return v

    @model_validator(mode="after")
    def _a_point_is_for_places_alone(self) -> SearchRequest:
        if self.near is not None and self.types != (EntityType.PLACE,):
            raise ValueError("a location can only be given to a search for places and nothing else")
        return self

    def endpoint(self) -> tuple[str, Params]:
        params: Params = [
            ("query", self.query),
            ("types", ",".join(t.value for t in self.types)),
            ("take", str(self.take)),
        ]
        if self.page != 1:
            params.append(("page", str(self.page)))
        if self.near is not None:
            # /search wants "lat,lon" (insights wants WKT, longitude first). Rounded to about 11 m, so one venue is one cache key.
            params.append(("filter.location", f"{self.near.lat:.4f},{self.near.lon:.4f}"))
        return "/search", params


class EntitiesRequest(FrozenModel):
    entity_ids: tuple[str, ...] = Field(min_length=1, max_length=50)

    @field_validator("entity_ids")
    @classmethod
    def _valid(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        _ids(v, "entity_ids", 50)
        return v

    def endpoint(self) -> tuple[str, Params]:
        return "/entities", [("entity_ids", _csv(self.entity_ids))]


class TagsRequest(FrozenModel):
    query: str = Field(min_length=1, max_length=100)
    take: int = Field(default=10, ge=1, le=20)

    def endpoint(self) -> tuple[str, Params]:
        return "/v2/tags", [
            ("filter.query", " ".join(self.query.split())),
            ("take", str(self.take)),
        ]


class CompareRequest(FrozenModel):
    """`/v2/analysis/compare`. `take` is never sent (rule G22)."""

    a: tuple[str, ...] = Field(min_length=1, max_length=10)
    b: tuple[str, ...] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def _valid(self) -> CompareRequest:
        _ids(self.a, "a", 10)
        _ids(self.b, "b", 10)
        return self

    def endpoint(self) -> tuple[str, Params]:
        return "/v2/analysis/compare", [
            ("a.signal.interests.entities", _csv(self.a)),
            ("b.signal.interests.entities", _csv(self.b)),
        ]


class DemographicsRequest(FrozenModel):
    """`filter.type=urn:demographics`: one item per signal entity. Needs at least one signal (rule G21)."""

    signal_entities: tuple[str, ...] = Field(min_length=1, max_length=SIGNAL_MAX)

    @field_validator("signal_entities")
    @classmethod
    def _valid(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        _ids(v, "signal_entities", SIGNAL_MAX)
        return v

    def endpoint(self) -> tuple[str, Params]:
        return "/v2/insights", [
            ("filter.type", "urn:demographics"),
            ("signal.interests.entities", _csv(self.signal_entities)),
        ]


class _InsightsBase(FrozenModel):
    entity_type: ClassVar[EntityType]

    signal_entities: tuple[str, ...] = ()
    exclude_entities: tuple[str, ...] = ()
    filter_tags: tuple[TagRef, ...] = ()
    exclude_tags: tuple[TagRef, ...] = ()
    popularity_min: float | None = Field(default=None, ge=0, le=1)
    popularity_max: float | None = Field(default=None, ge=0, le=1)
    results_entities: tuple[str, ...] = ()
    take: int = Field(default=20, ge=1, le=TAKE_MAX)
    page: int = Field(default=1, ge=1, le=PAGE_MAX)
    explainability: bool = False

    @model_validator(mode="after")
    def _common(self) -> _InsightsBase:
        _ids(self.signal_entities, "signal_entities", SIGNAL_MAX)
        _ids(self.exclude_entities, "exclude_entities", 50)
        _ids(self.results_entities, "results_entities", 50)
        if (
            self.popularity_min is not None
            and self.popularity_max is not None
            and self.popularity_min > self.popularity_max
        ):
            raise ValueError("popularity_min is above popularity_max")
        overlap = set(self.signal_entities) & set(self.exclude_entities)
        if overlap:
            raise ValueError("an entity cannot be both a signal and an exclusion")
        if self.results_entities and not (self.signal_entities or self._has_signal_tags()):
            raise ValueError("results_entities needs a signal (rule G21)")
        if self.explainability and not self.signal_entities:
            raise ValueError("explainability needs signal_entities")
        return self

    def _has_signal_tags(self) -> bool:
        return False

    def _extra_params(self) -> Params:
        return []

    def endpoint(self) -> tuple[str, Params]:
        params: Params = [("filter.type", self.entity_type.value), ("take", str(self.take))]
        if self.page != 1:
            params.append(("page", str(self.page)))
        if self.signal_entities:
            params.append(("signal.interests.entities", _csv(self.signal_entities)))
        if self.exclude_entities:
            params.append(("filter.exclude.entities", _csv(self.exclude_entities)))
        if self.filter_tags:
            params.append(("filter.tags", _csv(tuple(t.tag_id for t in self.filter_tags))))
        if self.exclude_tags:
            params.append(("filter.exclude.tags", _csv(tuple(t.tag_id for t in self.exclude_tags))))
        if self.popularity_min is not None:
            params.append(("filter.popularity.min", _num(self.popularity_min)))
        if self.popularity_max is not None:
            params.append(("filter.popularity.max", _num(self.popularity_max)))
        if self.results_entities:
            params.append(("filter.results.entities", _csv(self.results_entities)))
        if self.explainability:
            params.append(("feature.explainability", "true"))
        params.extend(self._extra_params())
        names = {k for k, _ in params}
        illegal = names - allowed_params(self.entity_type.value)
        if illegal:  # defence in depth: the table is the contract
            raise ValueError(
                f"parameters not allowed for {self.entity_type.value}: {sorted(illegal)}"
            )
        return "/v2/insights", params


def _num(x: float) -> str:
    return f"{x:.6g}"


class ArtistInsights(_InsightsBase):
    entity_type: ClassVar[EntityType] = EntityType.ARTIST
    filter_type: Literal["artist"] = "artist"


class BrandInsights(_InsightsBase):
    entity_type: ClassVar[EntityType] = EntityType.BRAND
    filter_type: Literal["brand"] = "brand"


class PodcastInsights(_InsightsBase):
    entity_type: ClassVar[EntityType] = EntityType.PODCAST
    filter_type: Literal["podcast"] = "podcast"


class VideogameInsights(_InsightsBase):
    """No content rating filter: it is ignored on videogames (trap 11)."""

    entity_type: ClassVar[EntityType] = EntityType.VIDEOGAME
    filter_type: Literal["videogame"] = "videogame"


class BookInsights(_InsightsBase):
    entity_type: ClassVar[EntityType] = EntityType.BOOK
    filter_type: Literal["book"] = "book"
    publication_year_min: int | None = Field(default=None, ge=1000, le=2100)
    publication_year_max: int | None = Field(default=None, ge=1000, le=2100)

    def _extra_params(self) -> Params:
        out: Params = []
        if self.publication_year_min is not None:
            out.append(("filter.publication_year.min", str(self.publication_year_min)))
        if self.publication_year_max is not None:
            out.append(("filter.publication_year.max", str(self.publication_year_max)))
        return out


class _ScreenInsights(_InsightsBase):
    release_year_min: int | None = Field(default=None, ge=1850, le=2100)
    release_year_max: int | None = Field(default=None, ge=1850, le=2100)

    def _extra_params(self) -> Params:
        out: Params = []
        if self.release_year_min is not None:
            out.append(("filter.release_year.min", str(self.release_year_min)))
        if self.release_year_max is not None:
            out.append(("filter.release_year.max", str(self.release_year_max)))
        return out


class MovieInsights(_ScreenInsights):
    entity_type: ClassVar[EntityType] = EntityType.MOVIE
    filter_type: Literal["movie"] = "movie"


class TvShowInsights(_ScreenInsights):
    entity_type: ClassVar[EntityType] = EntityType.TV_SHOW
    filter_type: Literal["tv_show"] = "tv_show"


class PlaceInsights(_InsightsBase):
    """Places inside an exact area. `signal_tags` is allowed here only (trap 6)."""

    entity_type: ClassVar[EntityType] = EntityType.PLACE
    filter_type: Literal["place"] = "place"

    area: AreaRef
    category: PlaceCategory | None = None
    signal_tags: tuple[TagRef, ...] = ()
    price_level_min: int | None = Field(default=None, ge=1, le=4)
    price_level_max: int | None = Field(default=None, ge=1, le=4)
    hours: Weekday | None = None
    sort_by_distance: bool = False
    diversify_by_city: int | None = Field(default=None, ge=1, le=20)
    external_exists: tuple[Literal["michelin"], ...] = ()

    def _has_signal_tags(self) -> bool:
        return bool(self.signal_tags)

    @model_validator(mode="after")
    def _place(self) -> PlaceInsights:
        if (
            self.price_level_min
            and self.price_level_max
            and self.price_level_min > self.price_level_max
        ):
            raise ValueError("price_level_min is above price_level_max")
        return self

    def endpoint(self) -> tuple[str, Params]:
        path, params = super().endpoint()
        params.append(("filter.location", self.area.center.to_wkt()))
        params.append(("filter.location.radius", str(self.area.radius_m)))
        if self.category is not None:
            tags = [t for t in params if t[0] == "filter.tags"]
            if tags:
                params.remove(tags[0])
                params.append(("filter.tags", tags[0][1] + "," + self.category.value))
            else:
                params.append(("filter.tags", self.category.value))
        if self.signal_tags:
            params.append(
                ("signal.interests.tags", _csv(tuple(t.tag_id for t in self.signal_tags)))
            )
        if self.price_level_min is not None:
            params.append(("filter.price_level.min", str(self.price_level_min)))
        if self.price_level_max is not None:
            params.append(("filter.price_level.max", str(self.price_level_max)))
        if self.hours is not None:
            params.append(("filter.hours", self.hours.value))
        if self.sort_by_distance:
            params.append(("sort_by", "distance"))
        if self.diversify_by_city is not None:
            params.append(("diversify.by", "properties.geocode.city"))
            params.append(("diversify.take", str(self.diversify_by_city)))
        if self.external_exists:
            params.append(("filter.external.exists", _csv(self.external_exists)))
        names = {k for k, _ in params}
        illegal = names - allowed_params(self.entity_type.value)
        if illegal:
            raise ValueError(f"parameters not allowed for place: {sorted(illegal)}")
        return path, params


InsightsRequest = (
    ArtistInsights
    | BrandInsights
    | PodcastInsights
    | VideogameInsights
    | BookInsights
    | MovieInsights
    | TvShowInsights
    | PlaceInsights
)

INSIGHTS_BY_TYPE: dict[EntityType, type[_InsightsBase]] = {
    EntityType.ARTIST: ArtistInsights,
    EntityType.BRAND: BrandInsights,
    EntityType.PODCAST: PodcastInsights,
    EntityType.VIDEOGAME: VideogameInsights,
    EntityType.BOOK: BookInsights,
    EntityType.MOVIE: MovieInsights,
    EntityType.TV_SHOW: TvShowInsights,
    EntityType.PLACE: PlaceInsights,
}

__all__ = [
    "INSIGHTS_BY_TYPE",
    "NEVER_EXPOSED",
    "PICKER_TYPES",
    "ArtistInsights",
    "BookInsights",
    "BrandInsights",
    "CompareRequest",
    "DemographicsRequest",
    "EntitiesRequest",
    "InsightsRequest",
    "MovieInsights",
    "PlaceCategory",
    "PlaceInsights",
    "PodcastInsights",
    "SearchRequest",
    "TagsRequest",
    "TvShowInsights",
    "VideogameInsights",
    "Weekday",
    "allowed_params",
]
