"""When a tribe shows up: membership-weighted counts by weekday and hour, in the venue's local time. Measured, not modelled."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from .types import Respondent


def weekday_hour(
    respondents: list[Respondent], ids: list[str], m: NDArray[np.float64]
) -> tuple[list[list[list[float]]], list[list[float]], int]:
    """(per-tribe 7x24 grids, whole-crowd 7x24 grid, number of respondents that had a time). Grids sum membership
    weights, so a guest who is half in one tribe adds half to it."""
    by_id = {r.id: r for r in respondents}
    k = m.shape[1]
    grids = np.zeros((k, 7, 24))
    crowd = np.zeros((7, 24))
    timed = 0
    for row, rid in enumerate(ids):
        r = by_id[rid]
        if r.weekday is None or r.hour is None or not (0 <= r.weekday <= 6 and 0 <= r.hour <= 23):
            continue
        timed += 1
        crowd[r.weekday, r.hour] += 1.0
        for t in range(k):
            grids[t, r.weekday, r.hour] += m[row, t]
    return (
        [[[round(float(x), 4) for x in hours] for hours in day] for day in grids],
        [[round(float(x), 4) for x in hours] for hours in crowd],
        timed,
    )
