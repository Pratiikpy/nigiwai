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
    for unbuilt in ("grow", "sound", "moves"):
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
