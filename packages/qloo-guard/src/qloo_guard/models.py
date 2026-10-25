"""Domain models: entity types, geometry, the trimmed Entity record, rule events and guard results.

Shapes were checked against live responses on 2026-10-23: /search and /entities return `types[]` and
`location{lat,lon}`; /v2/insights returns `type`, `subtype`, `query.affinity` and, for places, `query.distance`
in metres; search tags carry `tag_id` while insights tags carry `id`.
"""

from __future__ import annotations

import math
import re
import unicodedata
from enum import StrEnum
from typing import Any, Literal, TypeVar
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

T = TypeVar("T")

_QLOO_ID = re.compile(
    r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$"
)
_TAG_URN = re.compile(r"^urn:tag:[a-z0-9_:\-\.]+$", re.IGNORECASE)


class EntityType(StrEnum):
    """Entity types the product can target. Person-like types are deliberately absent (trap 12)."""

    ARTIST = "urn:entity:artist"
    BOOK = "urn:entity:book"
    BRAND = "urn:entity:brand"
    DESTINATION = "urn:entity:destination"
    MOVIE = "urn:entity:movie"
    PLACE = "urn:entity:place"
    PODCAST = "urn:entity:podcast"
    TV_SHOW = "urn:entity:tv_show"
    VIDEOGAME = (
        "urn:entity:videogame"  # not video_game: that string is a known bug in other projects
    )


# Types a customer can pick in the survey (no person and no destination). A place is searched near the venue and on its own
# (SearchRequest.near); the groups engine keeps only a place's taste tags, never its facilities.
PICKER_TYPES: tuple[EntityType, ...] = (
    EntityType.ARTIST,
    EntityType.MOVIE,
    EntityType.TV_SHOW,
    EntityType.BOOK,
    EntityType.BRAND,
    EntityType.PLACE,
    EntityType.PODCAST,
    EntityType.VIDEOGAME,
)

# Types the API will refuse anywhere in a request (trap 12).
FORBIDDEN_TYPE_SUFFIXES: frozenset[str] = frozenset({"person", "actor", "director", "author"})


def type_name(urn: str) -> str:
    """`urn:entity:artist` -> `artist`; `urn:entity:place:restaurant` -> `place`."""
    parts = urn.split(":")
    return parts[2] if len(parts) >= 3 else urn


def is_forbidden_type(urn: str) -> bool:
    return type_name(urn) in FORBIDDEN_TYPE_SUFFIXES


def is_qloo_id(value: str) -> bool:
    return bool(_QLOO_ID.match(value))


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def norm_name(text: str) -> str:
    """NFC, casefolded, punctuation-light key used for duplicate detection."""
    return re.sub(r"\s+", " ", nfc(text).casefold()).strip()


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class GeoPoint(FrozenModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)

    def to_wkt(self) -> str:
        """Insights wants WKT with longitude first. The serialiser owns the order so callers cannot swap it."""
        return f"POINT({self.lon:.6f} {self.lat:.6f})"

    def distance_m(self, other: GeoPoint) -> float:
        r = 6_371_000.0
        p1, p2 = math.radians(self.lat), math.radians(other.lat)
        dphi = p2 - p1
        dl = math.radians(other.lon - self.lon)
        a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        return 2 * r * math.asin(min(1.0, math.sqrt(a)))


class AreaRef(FrozenModel):
    """Our geocoded point plus a radius in metres. `location.query` is never used (trap 17)."""

    center: GeoPoint
    radius_m: int = Field(ge=50, le=50_000)


class TagRef(FrozenModel):
    """A tag URN that came from /v2/tags or from a verified table, never from model text (trap 7)."""

    tag_id: str

    @field_validator("tag_id")
    @classmethod
    def _valid(cls, v: str) -> str:
        if not _TAG_URN.match(v):
            raise ValueError("tag id must look like urn:tag:<type>:<...>")
        return v

    @property
    def namespace(self) -> str:
        return ":".join(self.tag_id.split(":")[:4])


class EntityTag(FrozenModel):
    tag_id: str
    name: str
    type: str | None = None


class Entity(FrozenModel):
    """The trimmed record the rest of the product sees (rule G29). Names are NFC."""

    entity_id: str
    name: str
    types: tuple[str, ...]
    subtype: str | None = None
    popularity: float | None = None
    tags: tuple[EntityTag, ...] = ()
    description: str | None = None
    image_url: str | None = None
    # place fields
    location: GeoPoint | None = None
    address: str | None = None
    price_level: int | None = None
    is_closed: bool | None = None
    distance_m: float | None = None
    neighborhood: str | None = None
    # taste fields
    affinity: float | None = None
    explain: dict[str, float] = Field(
        default_factory=dict
    )  # seed entity id -> share, when requested
    release_year: int | None = None
    # outside ids carried by Qloo
    musicbrainz_id: str | None = None
    spotify_id: str | None = None
    lastfm_listeners: int | None = None

    @property
    def primary_type(self) -> str:
        return self.types[0] if self.types else ""


class RuleEvent(FrozenModel):
    rule: str
    stage: Literal["pre", "post"]
    effect: Literal["rejected", "dropped", "adjusted", "flagged", "info"]
    detail: str = ""
    count: int = 1


class QlooWarning(FrozenModel):
    type: str
    raw: dict[str, Any] = Field(default_factory=dict)

    def entity_ids(self) -> tuple[str, ...]:
        ids: list[str] = []
        for value in self.raw.values():
            if isinstance(value, list):
                ids.extend(v for v in value if isinstance(v, str) and is_qloo_id(v))
        return tuple(ids)


class Tag(FrozenModel):
    tag_id: str
    name: str
    type: str | None = None
    popularity: float | None = None


class CompareResult(FrozenModel):
    shared_tags: tuple[Tag, ...]
    a_tags: tuple[Tag, ...] = ()
    b_tags: tuple[Tag, ...] = ()


class DemographicsItem(FrozenModel):
    """One demographics item per signal entity. Ages and gender are relative to the average (about -1..1)."""

    entity_id: str
    age: dict[str, float]
    gender: dict[str, float]


GuardStatus = Literal["ok", "empty", "degraded", "rejected", "budget_exhausted", "unavailable"]
CacheState = Literal["hit", "miss", "stale", "replay", "bypass"]
Purpose = Literal[
    "picker", "card", "ask", "fit", "board", "tribes", "eval", "canary", "lineup", "system"
]
Mode = Literal["live", "record", "replay"]


class GuardResult[T](BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    status: GuardStatus
    items: T
    call_id: UUID = Field(default_factory=uuid4)
    cache: CacheState = "miss"
    transport: str = "none"
    rule_events: list[RuleEvent] = Field(default_factory=list)
    warnings: list[QlooWarning] = Field(default_factory=list)
    latency_ms: int = 0
    result_entity_ids: list[str] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status in ("ok", "degraded")
