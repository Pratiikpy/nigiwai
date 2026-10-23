"""Request and response models. Everything is strict: unknown fields are rejected."""

from __future__ import annotations

import unicodedata
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StrictBool,
    StrictInt,
    StringConstraints,
    field_validator,
    model_validator,
)


def _one_line(value: str) -> str:
    """Names and labels are single lines of text: no control characters (NUL would also be refused by Postgres)."""
    if any(unicodedata.category(ch) in ("Cc", "Cs", "Co") for ch in value):
        raise ValueError("must not contain control characters or line breaks")
    return unicodedata.normalize("NFC", value)


Name = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=120),
    AfterValidator(_one_line),
]
Short = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=60),
    AfterValidator(_one_line),
]
Line = Annotated[
    str, StringConstraints(strip_whitespace=True, max_length=300), AfterValidator(_one_line)
]


class Strict(BaseModel):
    """Unknown fields are refused and nothing is coerced: "true" is not a boolean, "51.5" is not a number."""

    model_config = ConfigDict(extra="forbid", strict=True)


# ---- auth -----------------------------------------------------------------------------------------------------
class SignupIn(Strict):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)
    business_name: Name


class LoginIn(Strict):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class TenantOut(Strict):
    id: UUID
    name: str
    role: Literal["owner", "manager", "viewer"]


class MeOut(Strict):
    user_id: UUID
    email: str
    csrf_token: str
    tenants: list[TenantOut]


# ---- business -------------------------------------------------------------------------------------------------
BUSINESS_TYPES = (
    "bar",
    "live_music_venue",
    "restaurant",
    "cafe",
    "brewery",
    "hotel_bar",
    "festival",
    "promoter",
    "shop",
    "other",
)


class BusinessIn(Strict):
    name: Name
    type: Literal[
        "bar",
        "live_music_venue",
        "restaurant",
        "cafe",
        "brewery",
        "hotel_bar",
        "festival",
        "promoter",
        "shop",
        "other",
    ]
    language: Literal["en"] = "en"
    currency: Annotated[str, StringConstraints(min_length=3, max_length=3, to_upper=True)] = "USD"


class BusinessOut(Strict):
    id: UUID
    tenant_id: UUID
    name: str
    type: str
    language: str
    currency: str


class LocationIn(Strict):
    name: Name
    address: Line | None = None
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    radius_m: int = Field(default=800, ge=50, le=50_000)
    timezone: str = Field(default="UTC", max_length=64)
    price_level: int | None = Field(default=None, ge=1, le=4)
    capacity: int | None = Field(default=None, ge=1, le=200_000)
    curfew: (
        Annotated[
            str, StringConstraints(strip_whitespace=True, max_length=20), AfterValidator(_one_line)
        ]
        | None
    ) = None
    excluded_genres: list[Short] = Field(default_factory=list, max_length=20)
    show_nights: list[int] = Field(default_factory=list, max_length=7)

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
            raise ValueError("unknown timezone; use an IANA name such as Europe/London") from exc
        return v

    @field_validator("show_nights")
    @classmethod
    def _weekdays(cls, v: list[int]) -> list[int]:
        if any(d < 0 or d > 6 for d in v) or len(set(v)) != len(v):
            raise ValueError("show_nights are distinct weekdays 0 (Monday) to 6 (Sunday)")
        return sorted(v)

    @model_validator(mode="after")
    def _both_coordinates(self) -> LocationIn:
        if (self.lat is None) != (self.lon is None):
            raise ValueError("give both lat and lon, or neither")
        return self


class LocationOut(Strict):
    id: UUID
    business_id: UUID
    name: str
    address: str | None
    lat: float | None
    lon: float | None
    radius_m: int
    timezone: str
    price_level: int | None
    capacity: int | None
    curfew: str | None
    excluded_genres: list[str]
    show_nights: list[int]


class QrPointIn(Strict):
    label: Name


class QrPointOut(Strict):
    id: UUID
    location_id: UUID
    label: str
    status: str
    token_hint: str
    created_at: datetime
    # The survey URL a poster encodes. Only people who can change the account receive it.
    url: str | None = None


PickerType = Literal["artist", "movie", "tv_show", "book", "brand", "podcast", "videogame"]
ALL_PICKER_TYPES: tuple[PickerType, ...] = (
    "artist",
    "movie",
    "tv_show",
    "brand",
    "podcast",
    "videogame",
    "book",
)


# ---- survey ---------------------------------------------------------------------------------------------------
class SurveyQuestions(Strict):
    """The core ask is the picks; the three extras are optional and each says who sees the answer."""

    min_picks: StrictInt = Field(default=3, ge=1, le=10)
    max_picks: StrictInt = Field(default=5, ge=3, le=10)
    ask_age_band: StrictBool = True
    ask_district: StrictBool = True
    ask_budget: StrictBool = True
    picker_types: list[PickerType] = Field(
        default_factory=lambda: list(ALL_PICKER_TYPES), min_length=1
    )

    @model_validator(mode="after")
    def _min_not_above_max(self) -> SurveyQuestions:
        if self.min_picks > self.max_picks:
            raise ValueError("min_picks cannot be more than max_picks")
        return self


class SurveyReward(Strict):
    title: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=80),
        AfterValidator(_one_line),
    ]
    detail: Annotated[
        str, StringConstraints(strip_whitespace=True, max_length=200), AfterValidator(_one_line)
    ] = ""


class SurveyIn(Strict):
    questions: SurveyQuestions = Field(default_factory=SurveyQuestions)
    reward: SurveyReward | None = None
    publish: bool = False


class SurveyOut(Strict):
    id: UUID
    version: int
    business_id: UUID
    status: str
    questions: SurveyQuestions
    reward: SurveyReward | None
    consent_text_version: str


# ---- public survey ----------------------------------------------------------------------------------------------
class PublicSurveyOut(Strict):
    business_name: str
    location_name: str
    questions: SurveyQuestions
    reward: SurveyReward | None
    consent_text_version: str
    consent_body: str
    nonce: str
    picker_min_chars: int


QR_CODE_FORMAT = r"^[A-Za-z0-9_-]{16,64}$"
Token = Annotated[str, StringConstraints(pattern=QR_CODE_FORMAT)]


class PickerIn(Strict):
    token: Token
    nonce: str = Field(min_length=10, max_length=200)
    q: str = Field(max_length=200)
    type: PickerType | None = None


class PickerItem(Strict):
    entity_id: str
    name: str
    type: str
    year: int | None = None
    description: str | None = None
    disambiguation: str | None = None


class PickerOut(Strict):
    items: list[PickerItem]
    source: Literal["local", "qloo", "cache", "none"]
    message: str | None = None


class SelectIn(Strict):
    token: Token
    nonce: str = Field(min_length=10, max_length=200)
    entity_id: str = Field(min_length=36, max_length=36)


class SelectOut(Strict):
    entity_id: str
    eligible: bool | None
    message: str | None = None


class ResponseIn(Strict):
    token: Token
    nonce: str = Field(min_length=10, max_length=200)
    picks: list[Annotated[str, StringConstraints(min_length=36, max_length=36)]] = Field(
        min_length=1, max_length=10
    )
    age_band: Literal["18-24", "25-34", "35-44", "45-54", "55-64", "65+"] | None = None
    district: str | None = Field(default=None, max_length=60)
    budget: StrictInt | None = Field(default=None, ge=1, le=4)
    consent: StrictBool
    # Honeypot: a real person never fills in a field that is hidden from view.
    website: str | None = Field(default=None, max_length=200)


class ResponseOut(Strict):
    ok: bool
    receipt: str
    reward: SurveyReward | None = None


class DeleteIn(Strict):
    receipt: str = Field(min_length=10, max_length=100)


class DeleteOut(Strict):
    removed: bool
