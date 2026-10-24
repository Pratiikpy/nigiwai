"""Opening hours and scan rhythm: which hours a venue is open, how many scans came in each, and where the quiet and busy
stretches are. Pure functions with no database, so every rule here is tested on its own.

A scan is a guest who chose to answer, not a headcount: the figures say how scans spread across the week, and every
caller labels them measured and says so.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

WINDOW = 3  # hours in a quiet or busy stretch
MIN_SCANS_FOR_WINDOWS = 20  # fewer scans than this is an early look: gaps may be chance
QUIET_BELOW = 0.5  # a quiet stretch has under half the scans of an average stretch


@dataclass(frozen=True)
class Window:
    weekday: int  # 0 = Monday
    start: int  # first hour, 0 to 23
    end: int  # hour after the last one, up to 24
    scans: int


def _hour(hhmm: str) -> int:
    return int(hhmm[:2])


def open_mask(hours: list[dict[str, str] | None]) -> list[list[bool]]:
    """7 x 24: whether the venue is open in that weekday-hour. A closing time at or before the opening time runs past
    midnight into the next day's small hours. With no hours given, every cell is False: nothing can be called quiet."""
    mask = [[False] * 24 for _ in range(7)]
    if len(hours) != 7:
        return mask
    for day, span in enumerate(hours):
        if not span:
            continue
        opens, closes = _hour(span["open"]), _hour(span["close"])
        minutes_close = int(span["close"][3:5])
        # an hour is open if any of it is: a 17:30 close keeps the 17:00 hour
        last = closes + (1 if minutes_close else 0)
        if last > opens:
            for h in range(opens, min(last, 24)):
                mask[day][h] = True
        else:
            for h in range(opens, 24):
                mask[day][h] = True
            for h in range(0, last):
                mask[(day + 1) % 7][h] = True
    return mask


def scan_grid(
    scans: Sequence[tuple[int, int] | tuple[int, int, int]], mask: list[list[bool]]
) -> list[list[int | None]]:
    """Scans per weekday and hour inside opening hours; None where the venue is closed. A scan outside opening hours
    (a guest who answered the next morning, or a venue with no hours) is in no cell. Each entry is (weekday, hour), or the same
    with how many scans fell in that hour."""
    cells: list[list[int | None]] = [
        [0 if mask[d][h] else None for h in range(24)] for d in range(7)
    ]
    for entry in scans:
        weekday, hour = entry[0], entry[1]
        if 0 <= weekday < 7 and 0 <= hour < 24 and cells[weekday][hour] is not None:
            cells[weekday][hour] = (cells[weekday][hour] or 0) + (
                entry[2] if len(entry) == 3 else 1
            )
    return cells


def span(mask: list[list[bool]]) -> tuple[int, int] | None:
    """The hours worth drawing: from the earliest opening to the latest closing across the week, or None if never open."""
    hours = [h for day in mask for h, on in enumerate(day) if on]
    if not hours:
        return None
    return min(hours), max(hours) + 1


def _windows(cells: list[list[int | None]]) -> list[Window]:
    out: list[Window] = []
    for day, row in enumerate(cells):
        for start in range(0, 24 - WINDOW + 1):
            part = row[start : start + WINDOW]
            if any(c is None for c in part):
                continue
            out.append(Window(day, start, start + WINDOW, sum(c or 0 for c in part)))
    return out


def quiet_windows(cells: list[list[int | None]], total_scans: int, take: int = 3) -> list[Window]:
    """The quietest three-hour stretch of each day that has one, fewest scans first, at most `take`, and only stretches
    with clearly fewer scans than an average stretch. Nothing is returned on too few scans: gaps may be chance."""
    if total_scans < MIN_SCANS_FOR_WINDOWS:
        return []
    every = _windows(cells)
    if not every:
        return []
    mean = sum(w.scans for w in every) / len(every)
    best: dict[int, Window] = {}
    for w in every:
        if w.scans < QUIET_BELOW * mean and (
            w.weekday not in best
            or (w.scans, w.start) < (best[w.weekday].scans, best[w.weekday].start)
        ):
            best[w.weekday] = w
    return sorted(best.values(), key=lambda w: (w.scans, w.weekday, w.start))[:take]


def busy_windows(cells: list[list[int | None]], total_scans: int, take: int = 3) -> list[Window]:
    """The busiest three-hour stretches of the week, most scans first, only when there are enough scans to say."""
    if total_scans < MIN_SCANS_FOR_WINDOWS:
        return []
    every = [w for w in _windows(cells) if w.scans > 0]
    chosen: list[Window] = []
    for w in sorted(every, key=lambda x: (-x.scans, x.weekday, x.start)):
        # stretches that overlap an already chosen one on the same day are the same stretch, shifted
        if any(c.weekday == w.weekday and abs(c.start - w.start) < WINDOW for c in chosen):
            continue
        chosen.append(w)
        if len(chosen) == take:
            break
    return chosen


def sparse_windows(
    cells: list[list[int | None]], threshold: int = 10, take: int = 1
) -> list[Window]:
    """Stretches with some scans but fewer than `threshold`: too few to say anything about who comes, the most scans first
    (the closest to being enough)."""
    every = [w for w in _windows(cells) if 0 < w.scans < threshold]
    chosen: list[Window] = []
    for w in sorted(every, key=lambda x: (-x.scans, x.weekday, x.start)):
        if any(c.weekday == w.weekday and abs(c.start - w.start) < WINDOW for c in chosen):
            continue
        chosen.append(w)
        if len(chosen) == take:
            break
    return chosen


def window_json(w: Window) -> dict[str, Any]:
    return {"weekday": w.weekday, "start": w.start, "end": w.end, "scans": w.scans}


WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def describe(w: Window) -> str:
    """ "Wednesday 14:00 to 17:00"."""
    return f"{WEEKDAYS[w.weekday]} {w.start:02d}:00 to {w.end:02d}:00"
