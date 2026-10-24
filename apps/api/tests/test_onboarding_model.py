"""Onboarding's rules, with no model and no database: what is asked, what a valid answer is, which modules a profile turns
on and why. The personas are invented owners; the question is whether eight questions or fewer give a profile that matches
what each of them is."""

from __future__ import annotations

from typing import Any

import pytest
from nigiwai_api.services import onboarding_model as om
from pydantic import ValidationError

WEEK: list[dict[str, str] | None] = [{"open": "08:00", "close": "17:00"}] * 6 + [None]
LATE: list[dict[str, str] | None] = [{"open": "17:00", "close": "01:00"}] * 7

PERSONAS: dict[str, dict[str, Any]] = {
    "cafe": {
        "name": "Quill Street Café",
        "answers": {
            "type": "cafe",
            "area": "12 Quill Street, Manchester",
            "goals": ["fill_quiet_hours"],
            "currency": "GBP",
            "hours": WEEK,
            "hosts_live_music": False,
        },
        "modules_on": {"map"},
        "modules_off": {"soundcheck", "brief"},
        "asked": ["type", "area", "goals", "currency", "hours", "hosts_live_music"],
    },
    "bar": {
        "name": "The Lamplighter",
        "answers": {
            "type": "bar",
            "area": "Hackney, London",
            "goals": ["book_acts", "know_crowd"],
            "currency": "GBP",
            "hours": LATE,
            "hosts_live_music": True,
            "show_nights": [4, 5],
            "excluded_genres": "metal, drill",
            "capacity": 100,
        },
        "modules_on": {"map", "soundcheck", "brief"},
        "modules_off": set(),
        # capacity would be a ninth question, so it is left for the venue page
        "asked": [
            "type",
            "area",
            "goals",
            "currency",
            "hours",
            "hosts_live_music",
            "show_nights",
            "excluded_genres",
        ],
    },
    "hotel": {
        "name": "The Halcyon Lounge",
        "answers": {
            "type": "hotel_bar",
            "area": "Old Mill Road, Leeds",
            "goals": ["plan_music"],
            "currency": "GBP",
            "hours": LATE,
            "hosts_live_music": False,
            "capacity": 80,
        },
        "modules_on": {"map"},
        "modules_off": {"soundcheck", "brief"},
        "asked": ["type", "area", "goals", "currency", "hours", "hosts_live_music", "capacity"],
    },
    "boutique": {
        "name": "Thread & Needle",
        "answers": {
            "type": "shop",
            "area": "Corn Exchange, Bristol",
            "goals": ["grow"],
            "currency": "GBP",
            "hours": WEEK,
        },
        "modules_on": {"map"},
        "modules_off": {"soundcheck", "brief"},
        "asked": ["type", "area", "goals", "currency", "hours"],
    },
    "venue": {
        "name": "The Cellar",
        "answers": {
            "type": "live_music_venue",
            "area": "Lower East Side, New York",
            "goals": ["book_acts"],
            "currency": "USD",
            "hours": LATE,
            "show_nights": [3, 4, 5, 6],
            "excluded_genres": "",
            "capacity": 250,
        },
        "modules_on": {"map", "soundcheck", "brief"},
        "modules_off": set(),
        "asked": [
            "type",
            "area",
            "goals",
            "currency",
            "hours",
            "show_nights",
            "excluded_genres",
            "capacity",
        ],
    },
}


def run_form(
    persona: dict[str, Any], *, skip: set[str] | None = None
) -> tuple[list[str], dict[str, Any]]:
    """Answer the fixed form the way this persona would. Returns the fields asked, in order, and what was learned."""
    known: dict[str, Any] = {}
    asked: list[str] = []
    skipped = set(skip or ())
    answers = persona["answers"]
    while len(asked) < om.MAX_QUESTIONS:
        left = om.remaining(known, skipped=skipped)
        if not left:
            break
        field = left[0]
        asked.append(field)
        if field in answers:
            known[field] = om.normalise(field, answers[field])
        else:
            skipped.add(field)
    return asked, known


@pytest.mark.parametrize("name", list(PERSONAS))
def test_each_persona_is_understood_in_eight_questions_or_fewer_and_gets_the_modules_it_needs(
    name: str,
) -> None:
    persona = PERSONAS[name]
    asked, known = run_form(persona)
    assert len(asked) <= om.MAX_QUESTIONS
    assert asked == persona["asked"]
    profile = om.build_profile(persona["name"], known)
    for key in ("type", "area", "goals", "currency"):
        assert getattr(profile, key) == persona["answers"][key]
    plan = om.plan_for(profile)
    on = {e.id for e in plan.entries if e.on}
    assert {"today", "people", "ask"} <= on  # always on, whoever the owner is
    assert persona["modules_on"] <= on
    assert not (persona["modules_off"] & on)
    assert all(e.reason for e in plan.entries)  # every choice comes with its reason
    assert {e.id for e in plan.entries} == set(om.MODULE_IDS)  # nothing outside the list


def test_a_music_room_that_books_acts_is_asked_eight_questions_and_never_a_ninth() -> None:
    asked, _ = run_form(PERSONAS["venue"])
    assert len(asked) == 8
    asked, known = run_form(PERSONAS["bar"])
    assert len(asked) == 8
    assert asked[-1] == "excluded_genres"
    assert "capacity" not in known  # it would be a ninth; the owner sets it on the venue page


def test_a_skipped_question_is_not_asked_again_and_the_profile_is_still_built() -> None:
    asked, known = run_form(PERSONAS["bar"], skip={"hours", "excluded_genres"})
    assert "hours" not in asked
    assert "hours" not in known
    assert asked[-1] == "capacity"  # the freed places go to the next useful question
    profile = om.build_profile("The Lamplighter", known)
    assert profile.hours == []
    assert profile.excluded_genres == []
    assert profile.capacity == 100


def test_what_is_already_known_is_never_asked_again() -> None:
    known = {"type": "cafe", "currency": "GBP", "area": "Leeds"}
    assert om.remaining(known)[0] == "goals"
    assert om.remaining(known, skipped={"goals", "hours"}) == ["hosts_live_music"]
    done = {**known, "goals": ["grow"], "hours": WEEK, "hosts_live_music": False}
    assert om.remaining(done) == []


def test_follow_ups_depend_on_the_answers_before_them() -> None:
    base = {"type": "bar", "area": "x y z", "goals": ["grow"], "currency": "GBP", "hours": WEEK}
    assert om.remaining(base) == ["hosts_live_music", "capacity"]
    assert om.remaining({**base, "hosts_live_music": True}) == [
        "show_nights",
        "excluded_genres",
        "capacity",
    ]
    assert om.remaining({**base, "hosts_live_music": False}) == ["capacity"]
    # a live-music venue hosts music by definition, so that is not asked
    assert om.remaining({**base, "type": "live_music_venue"}) == [
        "show_nights",
        "excluded_genres",
        "capacity",
    ]
    assert om.remaining({**base, "type": "shop"}) == []  # a shop is not asked about music
    assert om.remaining({**base, "type": "cafe"}) == ["hosts_live_music"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("type", "spaceship"),
        ("type", None),
        ("goals", []),
        ("goals", ["know_crowd", "grow", "plan_music", "book_acts"]),
        ("goals", ["nonsense"]),
        ("goals", ["grow", "grow"]),
        ("currency", "US"),
        ("currency", "dollars"),
        ("currency", "12$"),
        ("currency", "XYZ"),
        ("currency", ""),
        ("area", "x"),
        ("area", "a" * 301),
        ("area", "line\x00break"),
        ("hours", "9 to 5"),
        ("hours", [None] * 7),
        ("hours", [{"open": "9:00", "close": "17:00"}] + [None] * 6),
        ("hours", [{"open": "09:00", "close": "09:00"}] + [None] * 6),
        ("hours", [{"open": "09:00"}] + [None] * 6),
        ("hours", [{"open": "25:00", "close": "17:00"}] + [None] * 6),
        ("hours", [{"open": "09:00", "close": "17:00"}] * 6),
        ("capacity", "lots"),
        ("capacity", 0),
        ("capacity", 300_000),
        ("show_nights", [7]),
        ("show_nights", [1, 1]),
        ("show_nights", "friday"),
        ("show_nights", [True]),
        ("hosts_live_music", "maybe"),
        ("excluded_genres", [f"genre {i}" for i in range(21)]),
        ("excluded_genres", ["y" * 61]),
        ("favourite_colour", "blue"),
    ],
)
def test_an_answer_that_does_not_fit_its_question_is_refused_with_a_reason(
    field: str, value: Any
) -> None:
    with pytest.raises(om.AnswerError) as exc:
        om.normalise(field, value)
    assert 0 < len(str(exc.value)) < 120


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("type", "cafe", "cafe"),
        ("goals", "grow", ["grow"]),
        ("currency", " gbp ", "GBP"),
        ("area", "  12   Quill  Street ", "12 Quill Street"),
        ("capacity", "120", 120),
        ("show_nights", [5, 4], [4, 5]),
        ("hosts_live_music", "Yes", True),
        ("hosts_live_music", False, False),
        ("excluded_genres", "metal,  drill; metal\nhonky tonk", ["metal", "drill", "honky tonk"]),
        ("excluded_genres", "", []),
    ],
)
def test_a_good_answer_is_kept_in_its_plain_form(field: str, value: Any, expected: Any) -> None:
    assert om.normalise(field, value) == expected


def test_the_profile_refuses_what_the_checklist_would_have_refused() -> None:
    ok = {"name": "X", "type": "bar", "area": "Leeds", "goals": ["grow"]}
    assert om.Profile.model_validate(ok).currency == "USD"
    for patch in (
        {"type": "spaceship"},
        {"goals": []},
        {"goals": ["grow", "grow"]},
        {"currency": "pounds"},
        {"show_nights": [9]},
        {"hours": [None] * 3},
        {"capacity": -4},
        {"price_level": 5},
        {"unexpected": 1},
        {"language": "fr"},
    ):
        with pytest.raises(ValidationError):
            om.Profile.model_validate({**ok, **patch})
    festival = om.Profile.model_validate({**ok, "type": "festival"})
    assert festival.hosts_live_music is True  # by definition


def test_the_plan_gives_a_reason_for_every_module_and_says_what_is_not_built() -> None:
    profile = om.build_profile("The Lamplighter", run_form(PERSONAS["bar"])[1])
    by_id = {m["id"]: m for m in om.plan_for(profile).to_json()["modules"]}
    assert by_id["soundcheck"]["on"]
    assert "On because you host live music" in by_id["soundcheck"]["reason"]
    for core in ("today", "people", "ask", "venue", "survey", "posters", "proof"):
        assert by_id[core]["locked"]
        assert by_id[core]["on"]
    for unbuilt in ("grow",):
        assert by_id[unbuilt]["on"] is False
        assert by_id[unbuilt]["available"] is False
        assert by_id[unbuilt]["reason"] == "Not built yet."
    wants_acts = om.build_profile(
        "The Halcyon",
        {"type": "hotel_bar", "area": "Leeds", "goals": ["book_acts"], "hosts_live_music": False},
    )
    reason = {m["id"]: m for m in om.plan_for(wants_acts).to_json()["modules"]}["soundcheck"][
        "reason"
    ]
    assert "On because you want to book better acts" in reason
    quiet = om.build_profile(
        "Quill", {"type": "cafe", "area": "Leeds", "goals": ["grow"], "hosts_live_music": False}
    )
    off = {m["id"]: m for m in om.plan_for(quiet).to_json()["modules"]}["brief"]
    assert off["on"] is False
    assert "Off because you do not host live music" in off["reason"]


def test_the_owners_own_switches_win_except_on_a_core_module_or_one_that_is_not_built() -> None:
    profile = om.build_profile(
        "Quill", {"type": "cafe", "area": "Leeds", "goals": ["grow"], "hosts_live_music": False}
    )
    switches = {"soundcheck": True, "map": False, "today": False, "ask": False, "grow": True}
    plan = {e.id: e for e in om.plan_for(profile, switches).entries}
    assert plan["soundcheck"].on
    assert plan["soundcheck"].changed
    assert plan["soundcheck"].reason.startswith("Switched on by you.")
    assert (
        "Off because" not in plan["soundcheck"].reason
    )  # the planner's own reason is not repeated
    assert not plan["map"].on
    assert plan["map"].changed
    assert plan["map"].reason.startswith("Switched off by you.")
    assert plan["today"].on
    assert plan["ask"].on
    assert not plan["today"].changed  # core: cannot be switched off
    assert plan["grow"].on is False  # not built: cannot be switched on
    same = {e.id: e for e in om.plan_for(profile, {"map": True}).entries}
    assert not same["map"].changed  # asking for what the planner chose changes nothing


def test_a_picked_place_becomes_a_position_and_a_bad_one_is_refused() -> None:
    place = om.normalise(
        "place", {"lat": 53.48, "lon": -2.24, "label": "  Quill Street,\n Manchester "}
    )
    assert place == {"lat": 53.48, "lon": -2.24, "label": "Quill Street, Manchester"}
    for bad in (
        None,
        "Manchester",
        {"lat": 53.48, "lon": -2.24},
        {"lat": 95, "lon": 0, "label": "x"},
        {"lat": 0, "lon": 181, "label": "x"},
        {"lat": True, "lon": 0, "label": "x"},
        {"lat": "53", "lon": 0, "label": "x"},
        {"lat": 1, "lon": 1, "label": "   "},
    ):
        with pytest.raises(om.AnswerError):
            om.normalise("place", bad)
    known = {"type": "cafe", "area": "Quill Street", "goals": ["grow"], "place": place}
    profile = om.build_profile("Quill", known)
    assert (profile.lat, profile.lon, profile.place_label) == (
        53.48,
        -2.24,
        "Quill Street, Manchester",
    )
    assert "place" not in om.FORM_ORDER  # recorded with the address, never asked on its own
    with pytest.raises(ValidationError):
        om.Profile.model_validate({**profile.model_dump(), "lon": None})


def test_the_time_zone_must_be_a_real_one() -> None:
    ok = {"name": "X", "type": "bar", "area": "Leeds", "goals": ["grow"]}
    assert (
        om.Profile.model_validate({**ok, "timezone": "Europe/London"}).timezone == "Europe/London"
    )
    assert om.Profile.model_validate(ok).timezone is None
    for bad in ("Mars/Olympus", "", "../etc/passwd", "x" * 65):
        with pytest.raises(ValidationError):
            om.Profile.model_validate({**ok, "timezone": bad})


def test_hours_are_summarised_in_runs_and_every_answer_can_be_said_back_in_plain_words() -> None:
    assert om.hours_summary(WEEK) == "Mon-Sat 08:00-17:00, Sun closed"
    assert om.hours_summary(LATE) == "Mon-Sun 17:00-01:00"
    mixed: list[dict[str, str] | None] = [
        None,
        *[{"open": "12:00", "close": "23:00"}] * 3,
        None,
        None,
        None,
    ]
    assert om.hours_summary(mixed) == "Mon closed, Tue-Thu 12:00-23:00, Fri-Sun closed"
    assert om.hours_summary([]) == "not given"
    assert om.describe_answer("type", "hotel_bar") == "Hotel bar or lounge"
    assert (
        om.describe_answer("goals", ["book_acts", "grow"])
        == "Book better acts; Reach new kinds of customers"
    )
    assert om.describe_answer("show_nights", [4, 5]) == "Friday, Saturday"
    assert om.describe_answer("show_nights", []) == "No regular nights"
    assert om.describe_answer("capacity", 1200) == "About 1,200 people"
    assert om.describe_answer("excluded_genres", []) == "None"
    assert om.describe_answer("hosts_live_music", False) == "No"


def test_what_was_understood_lists_only_what_applies_and_never_fills_a_gap() -> None:
    cafe = {"type": "cafe", "area": "Quill Street", "goals": ["grow"], "currency": "GBP"}
    by_field = {line["field"]: line["text"] for line in om.understood(cafe)}
    assert by_field["hours"] == "Not given"
    assert by_field["hosts_live_music"] == "Not given"
    assert by_field["place"] == "Not placed yet"
    assert "show_nights" not in by_field
    shop = {**cafe, "type": "shop"}
    assert "hosts_live_music" not in {line["field"] for line in om.understood(shop)}
    venue = {**cafe, "type": "live_music_venue", "show_nights": [4]}
    by_field = {line["field"]: line["text"] for line in om.understood(venue)}
    assert by_field["hosts_live_music"] == "Yes"
    assert by_field["show_nights"] == "Friday"
    assert by_field["excluded_genres"] == "Not given"
    assert by_field["capacity"] == "Not given"


def test_a_question_is_allowed_only_while_the_required_ones_still_fit_in_eight() -> None:
    assert om.may_ask("type", {}, 0)
    known = {"type": "bar", "area": "x y", "goals": ["grow"], "currency": "GBP"}
    assert om.may_ask("hours", known, 4)
    assert om.may_ask("capacity", known, 7)
    assert not om.may_ask("capacity", known, 8)
    assert not om.may_ask("hours", {"type": "bar"}, 5)  # area, goals and currency still need places
    assert om.may_ask("area", {"type": "bar"}, 5)
    assert om.missing_required({"type": "bar"}) == ["area", "goals", "currency"]


def test_a_stored_profile_reads_back_as_the_answers_it_came_from() -> None:
    profile = om.build_profile(
        "The Lamplighter",
        {
            "type": "bar",
            "area": "Hackney",
            "goals": ["book_acts"],
            "currency": "GBP",
            "hosts_live_music": True,
            "show_nights": [4],
            "place": {"lat": 51.5, "lon": -0.05, "label": "Hackney, London"},
        },
    )
    known = om.profile_known(profile.model_dump())
    assert known["place"] == {"lat": 51.5, "lon": -0.05, "label": "Hackney, London"}
    assert known["show_nights"] == [4]
    assert known["hosts_live_music"] is True
    assert "hours" not in known
    assert "excluded_genres" not in known  # empty is "not given", as in the interview
    assert "capacity" not in known


def test_the_sound_plan_is_on_for_a_room_that_plays_music_and_off_for_a_promoter_or_a_festival() -> (
    None
):
    def sound(kind: str) -> om.PlanEntry:
        profile = om.build_profile(
            "X", {"type": kind, "area": "Leeds", "goals": ["grow"], "hosts_live_music": False}
        )
        return next(e for e in om.plan_for(profile).entries if e.id == "sound")

    for kind in (
        "cafe",
        "bar",
        "restaurant",
        "shop",
        "hotel_bar",
        "brewery",
        "live_music_venue",
        "other",
    ):
        assert sound(kind).on, kind
        assert sound(kind).reason.startswith("On because any room that plays music can use it.")
    for kind in ("promoter", "festival"):
        assert not sound(kind).on
        assert sound(kind).reason.startswith(
            "Off because you are not a room that plays music through the day."
        )
    assert sound("cafe").available


def test_drafts_are_on_for_every_kind_of_business() -> None:
    for kind in om.TYPE_LABELS:
        profile = om.build_profile(
            "X", {"type": kind, "area": "Leeds", "goals": ["grow"], "hosts_live_music": False}
        )
        drafts = next(e for e in om.plan_for(profile).entries if e.id == "drafts")
        assert drafts.on, kind
        assert "sends nothing" in drafts.reason


def test_moves_are_on_for_every_kind_of_business() -> None:
    for kind in om.TYPE_LABELS:
        profile = om.build_profile(
            "X", {"type": kind, "area": "Leeds", "goals": ["grow"], "hosts_live_music": False}
        )
        moves = next(e for e in om.plan_for(profile).entries if e.id == "moves")
        assert moves.on, kind
        assert moves.available
        assert moves.reason.startswith("On because every business changes things.")
