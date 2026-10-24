"""The before-and-after arithmetic for a move, with no database: which days count, what is compared, and above all when it
refuses to say anything. Every date is invented."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from nigiwai_api.services import moves_model as mm

FRIDAY_EVENING = mm.Slot((4,), 18, 22)
START = date(2026, 3, 6)  # a Friday


def weekly(
    day0: date, weeks: int, per_day: int, weekday: int = 4, hour: int = 19
) -> list[tuple[date, int, int]]:
    """`per_day` scans at the given hour on that weekday of each of `weeks` weeks starting from day0 (a date of that weekday)."""
    out: list[tuple[date, int, int]] = []
    for w in range(weeks):
        d = day0 + timedelta(weeks=w)
        out += [(d, weekday, hour)] * per_day
    return out


def test_the_periods_are_the_weeks_around_the_start_and_never_reach_into_the_future() -> None:
    (b0, b1), (a0, a1) = mm.periods(START, None, today=date(2026, 5, 1))
    assert (b0, b1) == (date(2026, 2, 6), START)
    assert (a0, a1) == (START, date(2026, 4, 3))
    (_, _), (a0, a1) = mm.periods(START, None, today=date(2026, 3, 13))
    assert a1 == date(2026, 3, 14)  # up to and including today, no further
    (_, _), (a0, a1) = mm.periods(START, date(2026, 3, 20), today=date(2026, 5, 1))
    assert a1 == date(2026, 3, 21)  # a move that ended stops counting when it ended


def test_only_days_the_slot_occurs_on_count_and_closed_days_do_not() -> None:
    assert mm.matching_days(START, START + timedelta(weeks=4), FRIDAY_EVENING) == 4
    assert mm.matching_days(START, START + timedelta(weeks=4), mm.Slot((), None, None)) == 28
    assert (
        mm.matching_days(START, START + timedelta(weeks=4), FRIDAY_EVENING, open_days={0, 1}) == 0
    )
    assert mm.Slot((), None, None).text() == "every day"
    assert FRIDAY_EVENING.text() == "Friday 18:00 to 22:00"
    assert mm.Slot((4, 5), 22, 24).text() == "Friday, Saturday 22:00 to 00:00"


def test_scans_outside_the_slot_are_not_counted_at_all() -> None:
    scans = [
        *weekly(START - timedelta(weeks=4), 4, 2),  # before: 2 on each Friday evening
        *weekly(START, 4, 2, hour=12),  # after, but at lunchtime: not in the slot
        *weekly(START, 4, 2, weekday=5),  # after, but on Saturdays: not in the slot
    ]
    result = mm.evaluate(scans, FRIDAY_EVENING, START, None, today=date(2026, 5, 1))
    assert result["before"]["scans"] == 8
    assert result["after"]["scans"] == 0
    assert result["before"]["days"] == result["after"]["days"] == 4


def test_a_clear_rise_is_called_more_with_the_interval_and_an_honest_caveat() -> None:
    scans = [*weekly(START - timedelta(weeks=4), 4, 3), *weekly(START, 4, 12)]
    r = mm.evaluate(scans, FRIDAY_EVENING, START, None, today=date(2026, 5, 1))
    assert r["verdict"] == "more"
    assert r["rate"]["before"] == 3.0
    assert r["rate"]["after"] == 12.0
    assert r["rate"]["ratio"] == 4.0
    assert r["rate"]["low"] > 1.0
    assert r["rate"]["low"] < 4.0 < r["rate"]["high"]
    assert "does not show the change caused it" in r["text"]
    assert r["interval"] == "90%"


def test_a_clear_fall_is_called_fewer() -> None:
    scans = [*weekly(START - timedelta(weeks=4), 4, 12), *weekly(START, 4, 3)]
    r = mm.evaluate(scans, FRIDAY_EVENING, START, None, today=date(2026, 5, 1))
    assert r["verdict"] == "fewer"
    assert r["rate"]["high"] < 1.0


def test_a_small_difference_in_small_numbers_is_inconclusive_not_a_win() -> None:
    scans = [*weekly(START - timedelta(weeks=4), 4, 1), *weekly(START, 4, 2)]  # 4 against 8 scans
    r = mm.evaluate(scans, FRIDAY_EVENING, START, None, today=date(2026, 5, 1))
    assert r["verdict"] == "inconclusive"
    assert r["rate"]["ratio"] == 2.0
    assert r["rate"]["low"] < 1.0 < r["rate"]["high"]
    assert "inconclusive" in r["text"]


def test_no_change_at_all_is_inconclusive() -> None:
    scans = [*weekly(START - timedelta(weeks=4), 4, 6), *weekly(START, 4, 6)]
    r = mm.evaluate(scans, FRIDAY_EVENING, START, None, today=date(2026, 5, 1))
    assert r["verdict"] == "inconclusive"
    assert r["rate"]["ratio"] == 1.0
    assert r["rate"]["p"] == 1.0


@pytest.mark.parametrize(
    ("today", "verdict", "fragment"),
    [
        (date(2026, 3, 6), "too_early", "matching day"),  # the start day itself: one day
        (date(2026, 3, 7), "too_early", "matching day"),  # a Saturday: still one Friday
    ],
)
def test_too_early_is_said_before_any_number_is(today: date, verdict: str, fragment: str) -> None:
    scans = [*weekly(START - timedelta(weeks=4), 4, 6), *weekly(START, 1, 6)]
    r = mm.evaluate(scans, FRIDAY_EVENING, START, None, today)
    assert r["verdict"] == verdict
    assert r["rate"] is None
    assert fragment in r["text"]


def test_too_few_scans_overall_are_not_turned_into_a_verdict() -> None:
    scans = [(START - timedelta(weeks=1), 4, 19), (START + timedelta(weeks=1), 4, 19)]
    r = mm.evaluate(scans, FRIDAY_EVENING, START, None, today=date(2026, 5, 1))
    assert r["verdict"] == "too_early"
    assert "mostly chance" in r["text"]


def test_a_move_that_ended_is_compared_over_the_days_it_ran() -> None:
    scans = [*weekly(START - timedelta(weeks=4), 4, 3), *weekly(START, 2, 12)]
    r = mm.evaluate(scans, FRIDAY_EVENING, START, START + timedelta(days=9), today=date(2026, 5, 1))
    assert r["after"]["days"] == 2  # the Fridays of 6 and 13 March
    assert r["verdict"] == "more"


def test_the_exact_interval_widens_when_there_is_less_to_go_on() -> None:
    wide = mm.rate_ratio(3, 4, 6, 4)
    narrow = mm.rate_ratio(30, 4, 60, 4)
    assert (wide["high"] - wide["low"]) > (narrow["high"] - narrow["low"])
    assert wide["ratio"] == narrow["ratio"] == 2.0
    # nothing before: the ratio is not defined, and the interval has no upper end
    from_nothing = mm.rate_ratio(0, 4, 9, 4)
    assert from_nothing["ratio"] is None
    assert from_nothing["high"] is None
    assert from_nothing["low"] > 1.0
    # nothing after: the lower end is zero
    to_nothing = mm.rate_ratio(9, 4, 0, 4)
    assert to_nothing["low"] == 0.0
    assert to_nothing["high"] < 1.0


def test_the_ledger_counts_every_answer_including_the_unsure_ones() -> None:
    results = [
        {"kind": "act", "verdict": "more"},
        {"kind": "act", "verdict": "inconclusive"},
        {"kind": "act", "verdict": "too_early"},
        {"kind": "menu", "verdict": "fewer"},
        {"kind": "menu", "verdict": "too_early"},
    ]
    ledger = mm.ledger(results)
    assert ledger["moves"] == 5
    assert ledger["kinds"] == [
        {"kind": "act", "moves": 3, "more": 1, "fewer": 0, "inconclusive": 1, "waiting": 1},
        {"kind": "menu", "moves": 2, "more": 0, "fewer": 1, "inconclusive": 0, "waiting": 1},
    ]


def test_counts_given_per_hour_equal_the_same_scans_listed_one_by_one() -> None:
    one_by_one = [
        *weekly(START - timedelta(weeks=4), 4, 5),
        *weekly(START, 4, 9),
        *weekly(START, 4, 3, hour=12),
    ]
    grouped = [
        *[(START - timedelta(weeks=4) + timedelta(weeks=w), 4, 19, 5) for w in range(4)],
        *[(START + timedelta(weeks=w), 4, 19, 9) for w in range(4)],
        *[(START + timedelta(weeks=w), 4, 12, 3) for w in range(4)],
    ]
    today = date(2026, 5, 1)
    assert mm.evaluate(grouped, FRIDAY_EVENING, START, None, today) == mm.evaluate(
        one_by_one, FRIDAY_EVENING, START, None, today
    )
    mixed = [*grouped[:4], *one_by_one[20:]]  # both forms may be mixed in one list
    assert mm.evaluate(mixed, FRIDAY_EVENING, START, None, today)["before"]["scans"] == 20
