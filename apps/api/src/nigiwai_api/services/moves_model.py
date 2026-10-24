"""Did a change coincide with more scans? (PRD M11 and M20), as plain arithmetic with its uncertainty shown.

A move is something the owner changed: an act booked, a menu item added, a price. It carries the slot it was aimed at (days
of the week and hours; empty means everywhere) and when it started. The comparison is the same slot in the weeks just before
and the weeks just after, counted per day the slot occurred, so a Friday evening is compared with Friday evenings.

What this can and cannot say. Scans are guests who chose to answer, not a headcount. A small count is mostly chance, so the
rate ratio comes with a 90% interval from the exact conditional method (given the total, the share that fell after follows a
binomial) and the verdict is "inconclusive" whenever the interval holds 1. Nothing here says the move caused a change: a
season, the weather or a neighbour's event moves scans too, and a single before and after has no control group.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from scipy.stats import beta, binomtest

WEEKS = 4  # how far before and after a move the comparison looks
MIN_DAYS = 2  # a period needs at least this many matching days
MIN_SCANS = 8  # and the two together at least this many scans, or it is too early to say
CONFIDENCE = 0.90
MIX_MIN = 10  # scans needed in a period before the mix of groups is shown for it (the product-wide minimum group size)


@dataclass(frozen=True)
class Slot:
    weekdays: tuple[int, ...]  # empty means every day
    hour_from: int | None  # None means every hour
    hour_to: int | None  # exclusive, 1 to 24

    def covers_day(self, weekday: int) -> bool:
        return not self.weekdays or weekday in self.weekdays

    def covers_hour(self, hour: int) -> bool:
        if self.hour_from is None or self.hour_to is None:
            return True
        return self.hour_from <= hour < self.hour_to

    def text(self) -> str:
        names = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
        days = "every day" if not self.weekdays else ", ".join(names[d] for d in self.weekdays)
        if self.hour_from is None or self.hour_to is None:
            return days
        return f"{days} {self.hour_from:02d}:00 to {self.hour_to % 24:02d}:00"


def matching_days(start: date, end: date, slot: Slot, open_days: set[int] | None = None) -> int:
    """How many days in [start, end) the slot occurred: its weekday matches, and the venue was open that weekday when its
    opening hours are known."""
    n = 0
    d = start
    while d < end:
        wd = d.weekday()
        if slot.covers_day(wd) and (open_days is None or wd in open_days):
            n += 1
        d += timedelta(days=1)
    return n


def _count(scans: list[tuple[date, int, int]], start: date, end: date, slot: Slot) -> int:
    return sum(
        1
        for d, wd, hr in scans
        if start <= d < end and slot.covers_day(wd) and slot.covers_hour(hr)
    )


def periods(
    started: date, ended: date | None, today: date, weeks: int = WEEKS
) -> tuple[tuple[date, date], tuple[date, date]]:
    """(before, after) as half-open date ranges. After runs from the start for up to `weeks` weeks, stops when the move
    ended, and never reaches into days that have not happened."""
    before = (started - timedelta(weeks=weeks), started)
    stop = min(started + timedelta(weeks=weeks), today + timedelta(days=1))
    if ended is not None:
        stop = min(stop, ended + timedelta(days=1))
    return before, (started, max(started, stop))


def rate_ratio(n_before: int, e_before: int, n_after: int, e_after: int) -> dict[str, Any]:
    """The rate after over the rate before, per matching day, with an exact interval. Needs both exposures above zero."""
    total = n_before + n_after
    rb = n_before / e_before
    ra = n_after / e_after
    out: dict[str, Any] = {
        "before": round(rb, 2),
        "after": round(ra, 2),
        "ratio": None,
        "low": None,
        "high": None,
        "p": None,
    }
    if total == 0:
        return out
    share_exposure = e_after / (e_after + e_before)
    test = binomtest(n_after, total, share_exposure)
    lo_p, hi_p = (0.0, 1.0)
    alpha = 1 - CONFIDENCE
    if n_after > 0:
        lo_p = float(beta.ppf(alpha / 2, n_after, total - n_after + 1))
    if n_after < total:
        hi_p = float(beta.ppf(1 - alpha / 2, n_after + 1, total - n_after))

    def to_ratio(p: float) -> float | None:
        if p >= 1.0:
            return None  # unbounded above
        return (p / (1 - p)) * (e_before / e_after)

    out["p"] = round(float(test.pvalue), 3)
    out["ratio"] = None if n_before == 0 else round((ra / rb), 2)
    out["low"] = round(to_ratio(lo_p) or 0.0, 2)
    high = to_ratio(hi_p)
    out["high"] = None if high is None else round(high, 2)
    return out


def evaluate(
    scans: list[tuple[date, int, int]],
    slot: Slot,
    started: date,
    ended: date | None,
    today: date,
    open_days: set[int] | None = None,
    weeks: int = WEEKS,
) -> dict[str, Any]:
    """Scans in the move's slot before and after it started, and what that does and does not show."""
    (b0, b1), (a0, a1) = periods(started, ended, today, weeks)
    e_b = matching_days(b0, b1, slot, open_days)
    e_a = matching_days(a0, a1, slot, open_days)
    n_b = _count(scans, b0, b1, slot)
    n_a = _count(scans, a0, a1, slot)
    base: dict[str, Any] = {
        "slot": slot.text(),
        "before": {
            "from": b0.isoformat(),
            "to": (b1 - timedelta(days=1)).isoformat(),
            "days": e_b,
            "scans": n_b,
        },
        "after": {
            "from": a0.isoformat(),
            "to": (a1 - timedelta(days=1)).isoformat() if a1 > a0 else None,
            "days": e_a,
            "scans": n_a,
        },
        "interval": f"{int(CONFIDENCE * 100)}%",
        "rate": None,
        "verdict": "too_early",
        "text": "",
    }
    # the weeks before are always at least as long as the days after, so enough days after means enough to compare with
    if e_a < MIN_DAYS:
        base["text"] = (
            f"Only {e_a} matching {'day has' if e_a == 1 else 'days have'} passed since this started. Nothing can be said until at least {MIN_DAYS} have."
        )
        return base
    if n_b + n_a < MIN_SCANS:
        base["text"] = (
            f"Only {n_b + n_a} scans fell in this slot across both periods. Below {MIN_SCANS} the difference is mostly chance, so nothing is said."
        )
        return base
    rate = rate_ratio(n_b, e_b, n_a, e_a)
    base["rate"] = rate
    low, high = rate["low"], rate["high"]
    if low is not None and low > 1.0:
        base["verdict"] = "more"
    elif high is not None and high < 1.0:
        base["verdict"] = "fewer"
    else:
        base["verdict"] = "inconclusive"
    base["text"] = {
        "more": f"Scans in this slot were higher after: {rate['after']:g} per day against {rate['before']:g} before. Other things can raise scans too, so this does not show the change caused it.",
        "fewer": f"Scans in this slot were lower after: {rate['after']:g} per day against {rate['before']:g} before. Other things can lower scans too, so this does not show the change caused it.",
        "inconclusive": f"{rate['after']:g} scans a day after against {rate['before']:g} before. That difference is within what chance alone produces at this sample size, so it is inconclusive.",
    }[base["verdict"]]
    return base


def ledger(results: list[dict[str, Any]]) -> dict[str, Any]:
    """What the moves so far add up to, by kind, counting 'inconclusive' and 'too early' as the answers they are."""
    kinds: dict[str, dict[str, int]] = {}
    for r in results:
        k = kinds.setdefault(
            r["kind"], {"moves": 0, "more": 0, "fewer": 0, "inconclusive": 0, "waiting": 0}
        )
        k["moves"] += 1
        key = r["verdict"] if r["verdict"] in ("more", "fewer", "inconclusive") else "waiting"
        k[key] += 1
    return {
        "kinds": [{"kind": kind, **counts} for kind, counts in sorted(kinds.items())],
        "moves": len(results),
    }
