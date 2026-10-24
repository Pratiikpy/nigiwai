"""The shape of onboarding (PRD M1): the checklist of what Nigiwai needs to know about a business, the typed Business
Profile that comes out, and the Dashboard Plan chosen from it.

Nothing here talks to a model or a database, so every rule is tested on its own. The interviewer (a model, or a fixed form
when no model is connected) only chooses what to ask next and fills in a profile; this module decides which fields exist,
what a valid answer is, which are still needed, and which modules a profile switches on and why.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AfterValidator, Field, StringConstraints, field_validator, model_validator

from ..schemas import BUSINESS_TYPES, HoursDay, Line, Name, Short, Strict, _one_line

MAX_QUESTIONS = 8
Goal = Literal["know_crowd", "fill_quiet_hours", "book_acts", "plan_music", "grow"]
GOALS: dict[str, str] = {
    "know_crowd": "Understand who my customers are",
    "fill_quiet_hours": "Fill my quiet hours",
    "book_acts": "Book better acts",
    "plan_music": "Choose the right music to play",
    "grow": "Reach new kinds of customers",
}
TYPE_LABELS: dict[str, str] = {
    "bar": "Bar",
    "live_music_venue": "Live music venue",
    "restaurant": "Restaurant",
    "cafe": "Café",
    "brewery": "Brewery or taproom",
    "hotel_bar": "Hotel bar or lounge",
    "festival": "Festival",
    "promoter": "Promoter or events company",
    "shop": "Shop or market stall",
    "other": "Something else",
}
ALWAYS_LIVE = ("live_music_venue", "festival", "promoter")  # these book live acts by definition
NEVER_LIVE = ("shop",)  # a shop is not asked about live music
CURRENCIES = ("USD", "GBP", "EUR", "CAD", "AUD", "NZD", "JPY", "INR")
# ISO 4217 currency codes in circulation. A code outside this list is refused, so "XYZ" is not a currency.
ISO_4217 = frozenset(
    (
        "AED",
        "AFN",
        "ALL",
        "AMD",
        "ANG",
        "AOA",
        "ARS",
        "AUD",
        "AWG",
        "AZN",
        "BAM",
        "BBD",
        "BDT",
        "BGN",
        "BHD",
        "BIF",
        "BMD",
        "BND",
        "BOB",
        "BRL",
        "BSD",
        "BTN",
        "BWP",
        "BYN",
        "BZD",
        "CAD",
        "CDF",
        "CHF",
        "CLP",
        "CNY",
        "COP",
        "CRC",
        "CUP",
        "CVE",
        "CZK",
        "DJF",
        "DKK",
        "DOP",
        "DZD",
        "EGP",
        "ERN",
        "ETB",
        "EUR",
        "FJD",
        "FKP",
        "GBP",
        "GEL",
        "GHS",
        "GIP",
        "GMD",
        "GNF",
        "GTQ",
        "GYD",
        "HKD",
        "HNL",
        "HTG",
        "HUF",
        "IDR",
        "ILS",
        "INR",
        "IQD",
        "IRR",
        "ISK",
        "JMD",
        "JOD",
        "JPY",
        "KES",
        "KGS",
        "KHR",
        "KMF",
        "KPW",
        "KRW",
        "KWD",
        "KYD",
        "KZT",
        "LAK",
        "LBP",
        "LKR",
        "LRD",
        "LSL",
        "LYD",
        "MAD",
        "MDL",
        "MGA",
        "MKD",
        "MMK",
        "MNT",
        "MOP",
        "MRU",
        "MUR",
        "MVR",
        "MWK",
        "MXN",
        "MYR",
        "MZN",
        "NAD",
        "NGN",
        "NIO",
        "NOK",
        "NPR",
        "NZD",
        "OMR",
        "PAB",
        "PEN",
        "PGK",
        "PHP",
        "PKR",
        "PLN",
        "PYG",
        "QAR",
        "RON",
        "RSD",
        "RUB",
        "RWF",
        "SAR",
        "SBD",
        "SCR",
        "SDG",
        "SEK",
        "SGD",
        "SHP",
        "SLE",
        "SOS",
        "SRD",
        "SSP",
        "STN",
        "SVC",
        "SYP",
        "SZL",
        "THB",
        "TJS",
        "TMT",
        "TND",
        "TOP",
        "TRY",
        "TTD",
        "TWD",
        "TZS",
        "UAH",
        "UGX",
        "USD",
        "UYU",
        "UZS",
        "VES",
        "VND",
        "VUV",
        "WST",
        "XAF",
        "XCD",
        "XOF",
        "XPF",
        "YER",
        "ZAR",
        "ZMW",
        "ZWL",
    )
)
DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


class Profile(Strict):
    """What was understood about a business. Every field is either given by the owner or left empty: nothing is guessed."""

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
    area: Line
    goals: Annotated[list[Goal], Field(min_length=1, max_length=3)]
    language: Literal["en"] = "en"
    currency: Annotated[
        str, StringConstraints(min_length=3, max_length=3, to_upper=True, pattern=r"^[A-Za-z]{3}$")
    ] = "USD"
    hosts_live_music: bool = False
    hours: list[HoursDay | None] = Field(default_factory=list, max_length=7)
    capacity: int | None = Field(default=None, ge=1, le=200_000)
    curfew: (
        Annotated[
            str, StringConstraints(strip_whitespace=True, max_length=20), AfterValidator(_one_line)
        ]
        | None
    ) = None
    show_nights: list[int] = Field(default_factory=list, max_length=7)
    excluded_genres: list[Short] = Field(default_factory=list, max_length=20)
    price_level: int | None = Field(default=None, ge=1, le=4)
    # Where it is on the map, when the owner picked a match for the address. Both or neither.
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    place_label: Line | None = None
    timezone: str | None = Field(default=None, max_length=64)

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, v: str | None) -> str | None:
        if v is None:
            return v
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
            raise ValueError("unknown time zone; use a name such as Europe/London") from exc
        return v

    @field_validator("goals")
    @classmethod
    def _distinct_goals(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v):
            raise ValueError("goals must be distinct")
        return v

    @field_validator("hours")
    @classmethod
    def _a_week(cls, v: list[HoursDay | None]) -> list[HoursDay | None]:
        if v and len(v) != 7:
            raise ValueError("hours are seven days, Monday first, with null for a closed day")
        return v

    @field_validator("show_nights")
    @classmethod
    def _weekdays(cls, v: list[int]) -> list[int]:
        if any(d < 0 or d > 6 for d in v) or len(set(v)) != len(v):
            raise ValueError("show nights are distinct weekdays 0 (Monday) to 6 (Sunday)")
        return sorted(v)

    @model_validator(mode="after")
    def _consistent(self) -> Profile:
        if self.type in ALWAYS_LIVE:
            self.hosts_live_music = True
        if (self.lat is None) != (self.lon is None):
            raise ValueError("give both latitude and longitude, or neither")
        return self


# ---------------------------------------------------------------------------------------------------- the checklist
@dataclass(frozen=True)
class Field_:
    id: str
    kind: Literal["choice", "multi", "text", "hours", "number", "days", "list", "yesno", "place"]
    required: bool
    text: str
    why: str


CHECKLIST: dict[str, Field_] = {
    f.id: f
    for f in (
        Field_(
            "type",
            "choice",
            True,
            "What kind of business is it?",
            "It decides which tools make sense for you.",
        ),
        Field_(
            "area",
            "text",
            True,
            "Where is it? Give the street address, or the neighbourhood and city.",
            "Places and the map are drawn around it. You can set the exact position later.",
        ),
        Field_(
            "goals",
            "multi",
            True,
            "What would you most like Nigiwai to help with? Choose up to three.",
            "It decides what your Today board leads with.",
        ),
        Field_(
            "currency",
            "choice",
            True,
            "Which currency do you price in?",
            "Budget answers and money figures use it.",
        ),
        Field_(
            "hours",
            "hours",
            False,
            "When are you open?",
            "Without it a quiet hour cannot be told from a closed one. You can skip this and add it later.",
        ),
        Field_(
            "hosts_live_music",
            "yesno",
            False,
            "Do you host live music?",
            "Acts, Soundcheck and the Booking Brief are for rooms that book live acts.",
        ),
        Field_(
            "show_nights",
            "days",
            False,
            "Which nights do you usually have live music?",
            "Soundcheck scores an act against the nights you actually run.",
        ),
        Field_(
            "excluded_genres",
            "list",
            False,
            "Are there genres you will not book? Separate them with commas.",
            "An act in a genre you exclude is never suggested.",
        ),
        Field_(
            "capacity",
            "number",
            False,
            "Roughly how many people does the room hold?",
            "It lets a Soundcheck warn when a big act will not fit.",
        ),
        # Never asked on its own: it is recorded when the owner picks a match for the address.
        Field_(
            "place",
            "place",
            False,
            "Is this the place?",
            "It puts you on the map, so places and acts are looked for around you.",
        ),
    )
}
FORM_ORDER = (
    "type",
    "area",
    "goals",
    "currency",
    "hours",
    "hosts_live_music",
    "show_nights",
    "excluded_genres",
    "capacity",
)
REQUIRED = tuple(f.id for f in CHECKLIST.values() if f.required)


def asks_about_music(known: dict[str, Any]) -> bool:
    """Whether the question about live music is worth asking: yes for a business that might host it, no where it is
    obvious (a live-music venue, a festival, a promoter always do; a shop is not asked)."""
    t = known.get("type")
    return t is not None and t not in ALWAYS_LIVE and t not in NEVER_LIVE


def hosts_music(known: dict[str, Any]) -> bool | None:
    if known.get("type") in ALWAYS_LIVE:
        return True
    if known.get("type") in NEVER_LIVE and "hosts_live_music" not in known:
        return False
    value = known.get("hosts_live_music")
    return value if isinstance(value, bool) else None


def applicable(field_id: str, known: dict[str, Any]) -> bool:
    """Whether a field is worth asking given what is already known."""
    if field_id == "hosts_live_music":
        return asks_about_music(known)
    if field_id in ("show_nights", "excluded_genres"):
        return hosts_music(known) is True
    if field_id == "capacity":
        return hosts_music(known) is True or known.get("type") in ("bar", "hotel_bar", "brewery")
    return True


def remaining(known: dict[str, Any], *, skipped: set[str] | None = None) -> list[str]:
    """Fields still to ask, in form order: not known, not skipped, and applicable."""
    skipped = skipped or set()
    return [f for f in FORM_ORDER if f not in known and f not in skipped and applicable(f, known)]


def choices_for(field_id: str) -> list[dict[str, str]] | None:
    if field_id == "type":
        return [{"value": t, "label": TYPE_LABELS[t]} for t in BUSINESS_TYPES]
    if field_id == "goals":
        return [{"value": k, "label": v} for k, v in GOALS.items()]
    if field_id == "currency":
        return [{"value": c, "label": c} for c in CURRENCIES]
    return None


def question_for(field_id: str, known: dict[str, Any]) -> dict[str, Any]:
    spec = CHECKLIST[field_id]
    q: dict[str, Any] = {
        "field": spec.id,
        "kind": spec.kind,
        "text": spec.text,
        "why": spec.why,
        "optional": not spec.required,
        "choices": choices_for(spec.id),
    }
    if field_id == "goals":
        q["max"] = 3
    if field_id == "hours":
        q["days"] = list(DAYS)
    return q


# ---------------------------------------------------------------------------------------------------- answers
class AnswerError(ValueError):
    """An answer that does not fit its question; the message is written for the owner."""


_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def normalise(field_id: str, value: Any) -> Any:
    """A valid value for a field, or an AnswerError saying what is wrong. The owner's words are never reinterpreted."""
    spec = CHECKLIST.get(field_id)
    if spec is None:
        raise AnswerError("That is not something I asked about.")
    if field_id == "type":
        if value not in BUSINESS_TYPES:
            raise AnswerError("Choose one of the kinds of business listed.")
        return value
    if field_id == "goals":
        picked = value if isinstance(value, list) else [value]
        if (
            not 1 <= len(picked) <= 3
            or any(g not in GOALS for g in picked)
            or len(set(picked)) != len(picked)
        ):
            raise AnswerError("Choose between one and three of the goals listed.")
        return list(picked)
    if field_id == "currency":
        code = str(value or "").strip().upper()
        if code not in ISO_4217:
            raise AnswerError("Give a currency code such as USD, GBP or EUR.")
        return code
    if field_id == "area":
        text = " ".join(str(value or "").split())
        if len(text) < 3:
            raise AnswerError("Give a street address, or at least the neighbourhood and city.")
        if len(text) > 300 or any(ord(c) < 32 for c in text):
            raise AnswerError(
                "That is too long, or has characters I cannot keep. Shorten it to the address."
            )
        return text
    if field_id == "hosts_live_music":
        if isinstance(value, bool):
            return value
        if str(value).lower() in ("yes", "true"):
            return True
        if str(value).lower() in ("no", "false"):
            return False
        raise AnswerError("Answer yes or no.")
    if field_id == "hours":
        if not isinstance(value, list) or len(value) != 7:
            raise AnswerError(
                "Give seven days, Monday first, each with opening and closing times or closed."
            )
        week: list[dict[str, str] | None] = []
        for day in value:
            if day is None:
                week.append(None)
                continue
            if not isinstance(day, dict) or set(day) != {"open", "close"}:
                raise AnswerError("Each open day needs an opening and a closing time.")
            if not (_TIME.match(str(day["open"])) and _TIME.match(str(day["close"]))):
                raise AnswerError("Times look like 09:30 or 23:00.")
            if day["open"] == day["close"]:
                raise AnswerError("Opening and closing times must differ.")
            week.append({"open": str(day["open"]), "close": str(day["close"])})
        if not any(week):
            raise AnswerError("Give at least one day you are open, or skip this question.")
        return week
    if field_id == "place":
        if not isinstance(value, dict) or set(value) != {"lat", "lon", "label"}:
            raise AnswerError("Pick one of the places found.")
        lat, lon = value["lat"], value["lon"]
        if (
            isinstance(lat, bool)
            or isinstance(lon, bool)
            or not isinstance(lat, int | float)
            or not isinstance(lon, int | float)
            or not -90 <= lat <= 90
            or not -180 <= lon <= 180
        ):
            raise AnswerError("That position is not on Earth.")
        label = " ".join(str(value["label"]).split())[:300]
        if not label:
            raise AnswerError("Pick one of the places found.")
        return {"lat": float(lat), "lon": float(lon), "label": label}
    if field_id == "capacity":
        try:
            n = int(value)
        except (TypeError, ValueError) as exc:
            raise AnswerError("Give a whole number of people.") from exc
        if not 1 <= n <= 200_000:
            raise AnswerError("That does not look like a room's capacity.")
        return n
    if field_id == "show_nights":
        if not isinstance(value, list) or any(
            not isinstance(d, int) or isinstance(d, bool) or not 0 <= d <= 6 for d in value
        ):
            raise AnswerError("Choose days of the week.")
        if len(set(value)) != len(value):
            raise AnswerError("Choose each day once.")
        return sorted(value)
    if field_id == "excluded_genres":
        parts = value if isinstance(value, list) else re.split(r"[,;\n]", str(value or ""))
        genres = list(dict.fromkeys(" ".join(str(p).split()) for p in parts if str(p).strip()))
        if len(genres) > 20 or any(len(g) > 60 for g in genres):
            raise AnswerError("List up to 20 genres, each a few words.")
        return genres
    raise AnswerError("That is not something I asked about.")


def build_profile(name: str, known: dict[str, Any], *, timezone: str | None = None) -> Profile:
    """The confirmed facts as a typed profile. Raises if a required field is missing or any value is invalid."""
    data = dict(known)
    data["name"] = name
    if timezone is not None:
        data["timezone"] = timezone
    data.setdefault("currency", "USD")
    data["hosts_live_music"] = bool(hosts_music(known))
    place = data.pop("place", None)
    if place:
        data["lat"], data["lon"], data["place_label"] = place["lat"], place["lon"], place["label"]
    for optional in ("hours", "show_nights", "excluded_genres"):
        data.setdefault(optional, [])
    return Profile.model_validate({k: v for k, v in data.items() if k in Profile.model_fields})


# ---------------------------------------------------------------------------------------------------- the plan
@dataclass(frozen=True)
class Module:
    id: str
    label: str
    href: str
    core: bool  # always on: the owner cannot switch it off
    built: bool = True


MODULES: tuple[Module, ...] = (
    Module("today", "Today", "/app/today", True),
    Module("venue", "Your venue", "/app/venue", True),
    Module("survey", "Survey", "/app/survey", True),
    Module("people", "My people", "/app/people", True),
    Module("ask", "Ask Nigiwai", "/app/ask", True),
    Module("posters", "QR posters", "/app/posters", True),
    Module("proof", "Proof", "/app/proof", True),
    Module("map", "Crowd map", "/app/map", False),
    Module("soundcheck", "Soundcheck", "/app/soundcheck", False),
    Module("brief", "Booking Brief", "/app/brief", False),
    Module("grow", "Grow", "/app/grow", False, built=False),
    Module("sound", "Sound plan", "/app/sound", False),
    Module("moves", "Moves", "/app/moves", False),
    Module("drafts", "Drafts", "/app/drafts", False),
)
MODULE_IDS = tuple(m.id for m in MODULES)
CORE_REASONS = {
    "today": "Your week at a glance: your quietest hours and what to do about them.",
    "venue": "Where you are and when you open.",
    "survey": "What guests are asked when they scan.",
    "people": "Who your guests are, as groups.",
    "ask": "Questions about your crowd and about the culture, answered from Qloo.",
    "posters": "The QR codes guests scan.",
    "proof": "Every Qloo call made for you, so nothing is a black box.",
}


@dataclass
class PlanEntry:
    id: str
    label: str
    href: str
    on: bool
    locked: bool
    available: bool
    reason: str
    changed: bool = False  # the owner switched it away from what the planner chose


@dataclass
class Plan:
    entries: list[PlanEntry] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "version": 1,
            "modules": [
                {
                    "id": e.id,
                    "label": e.label,
                    "href": e.href,
                    "on": e.on,
                    "locked": e.locked,
                    "available": e.available,
                    "reason": e.reason,
                    "changed": e.changed,
                }
                for e in self.entries
            ],
        }


def plan_for(profile: Profile, overrides: dict[str, bool] | None = None) -> Plan:
    """Which modules a profile switches on, each with its reason. Only modules in the list can appear; Today, My people and
    Ask Nigiwai are always on. A module that is not built yet is listed off and says so. `overrides` are the owner's own
    switches: they win over the planner for any module that is not locked."""
    overrides = overrides or {}
    entries: list[PlanEntry] = []
    for m in MODULES:
        if m.core:
            entries.append(PlanEntry(m.id, m.label, m.href, True, True, True, CORE_REASONS[m.id]))
            continue
        if not m.built:
            entries.append(PlanEntry(m.id, m.label, m.href, False, False, False, "Not built yet."))
            continue
        if m.id == "map":
            what = "Where your guests scan and what is around you."
            on, reason = True, what
        elif m.id == "drafts":
            what = "Drafts prepares an enquiry, an event page, a post or an ad angle for you to review and approve; it sends nothing."
            on, reason = True, f"On because every business tells people what it is doing. {what}"
        elif m.id == "moves":
            what = "Moves log what you change and show whether scans in the same slot moved."
            on, reason = True, f"On because every business changes things. {what}"
        elif m.id == "sound":
            what = "The Sound plan ranks acts to play by time of the week from who is in the room then."
            if profile.type in ("promoter", "festival"):
                on, reason = (
                    False,
                    f"Off because you are not a room that plays music through the day. {what}",
                )
            else:
                on, reason = True, f"On because any room that plays music can use it. {what}"
        else:
            what = f"{m.label} checks an act against your crowd."
            if profile.hosts_live_music:
                on, reason = True, f"On because you host live music. {what}"
            elif "book_acts" in profile.goals:
                on, reason = True, f"On because you want to book better acts. {what}"
            else:
                on, reason = False, f"Off because you do not host live music. {what}"
        entry = PlanEntry(m.id, m.label, m.href, on, False, True, reason)
        if m.id in overrides and overrides[m.id] != on:
            entry.on = overrides[m.id]
            entry.changed = True
            entry.reason = f"Switched {'on' if entry.on else 'off'} by you. {what}"
        entries.append(entry)
    return Plan(entries)


# ---------------------------------------------------------------------------------------------------- in plain words
SHORT_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def hours_summary(week: list[Any]) -> str:
    """A week of opening hours as one line, with runs of days that share hours joined: Mon-Sat 08:00-17:00, Sun closed."""
    if not week:
        return "not given"
    runs: list[tuple[int, int, str]] = []
    for i, day in enumerate(week):
        text = "closed" if not day else f"{day['open']}-{day['close']}"
        if runs and runs[-1][2] == text and runs[-1][1] == i - 1:
            runs[-1] = (runs[-1][0], i, text)
        else:
            runs.append((i, i, text))
    parts = []
    for first, last, text in runs:
        days = SHORT_DAYS[first] if first == last else f"{SHORT_DAYS[first]}-{SHORT_DAYS[last]}"
        parts.append(f"{days} {text}")
    return ", ".join(parts)


def describe_answer(field_id: str, value: Any) -> str:
    """What an accepted answer says, in the owner's terms: shown back to them and kept in the conversation."""
    if field_id == "type":
        return TYPE_LABELS.get(str(value), str(value))
    if field_id == "goals":
        return "; ".join(GOALS.get(g, g) for g in value)
    if field_id == "hours":
        return hours_summary(value)
    if field_id == "hosts_live_music":
        return "Yes" if value else "No"
    if field_id == "show_nights":
        return ", ".join(DAYS[d] for d in value) if value else "No regular nights"
    if field_id == "excluded_genres":
        return ", ".join(value) if value else "None"
    if field_id == "capacity":
        return f"About {value:,} people"
    if field_id == "place":
        return str(value["label"])
    return str(value)


FIELD_LABELS = {
    "type": "Kind of business",
    "area": "Where",
    "goals": "What you want help with",
    "currency": "Currency",
    "hours": "Opening hours",
    "hosts_live_music": "Live music",
    "show_nights": "Show nights",
    "excluded_genres": "Genres you will not book",
    "capacity": "Room size",
    "place": "On the map",
}


def understood(known: dict[str, Any]) -> list[dict[str, str]]:
    """ "Here is what I understood", one line per field, in the order a person would read it. A field that matters for
    this business and was not given is listed as not given, never filled in; one that does not apply is left out."""
    lines: list[dict[str, str]] = []
    for fid in ("type", "area", "place", "goals", "currency", "hours"):
        if fid == "place" and fid not in known:
            text = "Not placed yet"
        elif fid == "place" and known["place"]["label"] == known.get("area"):
            text = "Found on the map"  # the address is the match the owner picked; saying it twice adds nothing
        else:
            text = describe_answer(fid, known[fid]) if fid in known else "Not given"
        lines.append({"field": fid, "label": FIELD_LABELS[fid], "text": text})
    music = hosts_music(known)
    if known.get("type") not in NEVER_LIVE:
        lines.append(
            {
                "field": "hosts_live_music",
                "label": FIELD_LABELS["hosts_live_music"],
                "text": "Not given"
                if music is None
                else describe_answer("hosts_live_music", music),
            }
        )
    for fid in ("show_nights", "excluded_genres", "capacity"):
        if applicable(fid, known) or fid in known:
            text = describe_answer(fid, known[fid]) if fid in known else "Not given"
            lines.append({"field": fid, "label": FIELD_LABELS[fid], "text": text})
    return lines


def missing_required(known: dict[str, Any]) -> list[str]:
    return [f for f in REQUIRED if f not in known]


def may_ask(field_id: str, known: dict[str, Any], asked: int) -> bool:
    """Whether one more question is allowed: the cap is eight, and the required questions are never crowded out."""
    others = [f for f in missing_required(known) if f != field_id]
    return asked + 1 + len(others) <= MAX_QUESTIONS


def profile_known(profile: dict[str, Any]) -> dict[str, Any]:
    """A stored profile as the interview's `known` answers: the facts it holds, with nothing added."""
    known: dict[str, Any] = {}
    for fid in ("type", "area", "goals", "currency", "hosts_live_music", "capacity"):
        if profile.get(fid) is not None:
            known[fid] = profile[fid]
    for fid in ("hours", "show_nights", "excluded_genres"):
        if profile.get(fid):
            known[fid] = profile[fid]
    if profile.get("lat") is not None and profile.get("lon") is not None:
        known["place"] = {
            "lat": profile["lat"],
            "lon": profile["lon"],
            "label": profile.get("place_label") or profile.get("area") or "Saved position",
        }
    return known
