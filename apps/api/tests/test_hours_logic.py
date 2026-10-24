"""Opening hours and scan rhythm: the pure rules behind the Today board's quietest hours."""

from __future__ import annotations

from nigiwai_api.services import hours as h

OPEN = {"open": "12:00", "close": "23:00"}


def week(*days: dict[str, str] | None) -> list[dict[str, str] | None]:
    return list(days)


def test_a_normal_day_is_open_from_the_opening_hour_to_the_hour_before_closing() -> None:
    mask = h.open_mask(week(OPEN, None, None, None, None, None, None))
    assert [i for i, on in enumerate(mask[0]) if on] == list(range(12, 23))
    assert not any(any(day) for day in mask[1:])


def test_a_closing_time_with_minutes_keeps_the_hour_it_falls_in() -> None:
    mask = h.open_mask(week({"open": "09:30", "close": "17:30"}, *[None] * 6))
    assert [i for i, on in enumerate(mask[0]) if on] == list(range(9, 18))


def test_closing_after_midnight_spills_into_the_next_days_small_hours() -> None:
    mask = h.open_mask(
        week(None, None, None, None, None, {"open": "18:00", "close": "02:00"}, None)
    )
    assert [i for i, on in enumerate(mask[5]) if on] == list(range(18, 24))
    assert [i for i, on in enumerate(mask[6]) if on] == [
        0,
        1,
    ]  # Sunday's small hours belong to Saturday's night


def test_the_last_night_of_the_week_spills_into_monday() -> None:
    mask = h.open_mask(
        week(None, None, None, None, None, None, {"open": "20:00", "close": "01:00"})
    )
    assert [i for i, on in enumerate(mask[0]) if on] == [0]


def test_a_midnight_close_opens_nothing_on_the_next_day() -> None:
    mask = h.open_mask(week({"open": "12:00", "close": "00:00"}, *[None] * 6))
    assert [i for i, on in enumerate(mask[0]) if on] == list(range(12, 24))
    assert not any(mask[1])


def test_no_hours_given_means_nothing_is_open_and_nothing_can_be_called_quiet() -> None:
    assert not any(any(day) for day in h.open_mask([]))
    assert not any(
        any(day) for day in h.open_mask([OPEN] * 3)
    )  # not a week: ignored, never guessed
    cells = h.scan_grid([(2, 15)] * 50, h.open_mask([]))
    assert all(c is None for row in cells for c in row)
    assert h.quiet_windows(cells, 50) == []
    assert h.span(h.open_mask([])) is None


def test_scans_land_in_their_cell_and_scans_outside_opening_hours_are_in_none() -> None:
    mask = h.open_mask(week(OPEN, *[None] * 6))
    cells = h.scan_grid([(0, 12), (0, 12), (0, 13), (0, 3), (1, 12), (9, 1), (0, 30)], mask)
    assert cells[0][12] == 2 and cells[0][13] == 1 and cells[0][14] == 0
    assert cells[0][3] is None and cells[1][12] is None
    assert sum(c or 0 for row in cells for c in row) == 3  # the three that fell in an open hour


def test_the_drawn_span_runs_from_the_earliest_opening_to_the_latest_closing() -> None:
    mask = h.open_mask(
        week({"open": "11:00", "close": "17:00"}, {"open": "16:00", "close": "23:00"}, *[None] * 5)
    )
    assert h.span(mask) == (11, 23)


def _grid(counts_by_day: dict[int, list[int]], start: int = 12) -> list[list[int | None]]:
    cells: list[list[int | None]] = [[None] * 24 for _ in range(7)]
    for day, counts in counts_by_day.items():
        for i, c in enumerate(counts):
            cells[day][start + i] = c
    return cells


def test_quiet_windows_are_the_emptiest_three_hour_stretches_one_per_day() -> None:
    cells = _grid(
        {
            0: [9, 9, 9, 9, 9, 9, 9, 9],
            1: [9, 9, 0, 0, 0, 9, 9, 9],  # a gap on Tuesday
            2: [9, 9, 9, 9, 9, 9, 9, 9],
            3: [9, 9, 9, 9, 9, 0, 1, 0],  # and a deeper one on Thursday evening
            4: [9, 9, 9, 9, 9, 9, 9, 9],
        }
    )
    total = sum(c or 0 for row in cells for c in row)
    found = h.quiet_windows(cells, total)
    assert [(w.weekday, w.start, w.end, w.scans) for w in found] == [(1, 14, 17, 0), (3, 17, 20, 1)]
    assert h.describe(found[0]) == "Tuesday 14:00 to 17:00"


def test_an_even_week_has_no_quiet_window() -> None:
    cells = _grid({d: [5] * 8 for d in range(5)})
    assert h.quiet_windows(cells, 200) == []


def test_too_few_scans_say_nothing_about_gaps() -> None:
    cells = _grid({0: [1, 0, 0, 0, 0, 0, 0, 3]})
    assert h.quiet_windows(cells, 4) == [] and h.busy_windows(cells, 4) == []
    assert h.quiet_windows(cells, h.MIN_SCANS_FOR_WINDOWS - 1) == []


def test_busy_windows_do_not_repeat_the_same_stretch_shifted_by_an_hour() -> None:
    cells = _grid({4: [0, 0, 0, 6, 9, 8, 0, 0], 5: [0, 0, 0, 0, 0, 4, 4, 4]})
    found = h.busy_windows(cells, 100)
    assert (found[0].weekday, found[0].start, found[0].scans) == (4, 15, 23)
    assert [w.weekday for w in found] == [
        4,
        5,
    ]  # Friday once, then Saturday, never Friday again an hour later


def test_sparse_windows_find_the_stretch_closest_to_having_enough_scans() -> None:
    cells = _grid(
        {5: [0, 0, 3, 3, 2, 0, 0, 0], 6: [0, 0, 0, 1, 0, 0, 0, 0], 0: [9, 9, 9, 9, 9, 9, 9, 9]}
    )
    found = h.sparse_windows(cells, threshold=10)
    assert len(found) == 1 and (found[0].weekday, found[0].scans) == (5, 8)
    assert (
        h.sparse_windows(_grid({0: [9, 9, 9, 9, 9, 9, 9, 9]})) == []
    )  # nothing is sparse: no card


def test_a_grid_built_from_counts_per_hour_equals_one_built_scan_by_scan() -> None:
    mask = h.open_mask([{"open": "12:00", "close": "23:00"}] * 7)
    one_by_one = (
        [(2, 15)] * 3 + [(4, 19)] * 5 + [(4, 3)] * 2
    )  # the last two fall outside opening hours
    counted = [(2, 15, 3), (4, 19, 5), (4, 3, 2)]
    assert h.scan_grid(counted, mask) == h.scan_grid(one_by_one, mask)
    assert h.scan_grid([(2, 15, 3), (2, 15)], mask)[2][15] == 4  # forms mix
