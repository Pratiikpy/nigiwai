"""The Sound plan (PRD M26): which acts to play at which time of the week, from the room's own groups.

Pure functions. Each stretch of the week (a part of the day on weekdays or on the weekend) has its own mix of groups,
measured from when their members scanned. An act's score for the stretch is the Fit Verdict's own formula applied with that
mix as the shares, using the per-group ranks Qloo's answers already gave for the act (nothing is asked of Qloo here).

What this is not: a claim about mood, spending or what a person would like to hear. The busyness line is scans per open
hour compared with the room's busiest stretch (measured); the acts are modelled; the product does not play or license music.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from nigiwai_fit import Weights, formula, raw_score

WEIGHTS = Weights()
MIN_CELL_SCANS = (
    20  # fewer scans than this in a stretch and it is not scored (an early look would be chance)
)
MIN_SCORED_SHARE = 0.6  # the groups an act was scored for must cover this much of the stretch
TOP = 5
DAYTYPES: tuple[tuple[str, str, tuple[int, ...]], ...] = (
    ("weekdays", "Monday to Thursday", (0, 1, 2, 3)),
    ("weekend", "Friday to Sunday", (4, 5, 6)),
)
DAYPARTS: tuple[tuple[str, str, tuple[int, ...]], ...] = (
    ("morning", "Morning", tuple(range(5, 12))),
    ("afternoon", "Afternoon", tuple(range(12, 17))),
    ("evening", "Evening", tuple(range(17, 22))),
    ("late", "Late night", (22, 23, 0, 1, 2, 3, 4)),
)
WATCH_SHARE = (
    0.2  # a group needs this much of a stretch before an act that ranks poorly for it is flagged
)
BUSY_FROM = 0.75  # a stretch at or above this share of the busiest one is "busy"
QUIET_BELOW = 0.35  # and below this "quiet"


@dataclass(frozen=True)
class SoundGroup:
    index: int
    label: str
    rhythm: tuple[
        tuple[float, ...], ...
    ]  # 7 weekdays (Monday first) x 24 hours of this group's scans


@dataclass(frozen=True)
class SoundAct:
    entity_id: str
    name: str
    genres: tuple[str, ...]
    popularity: float | None
    fits: dict[int, float] = field(
        default_factory=dict
    )  # group index -> rank among Qloo's references, 0 to 1


def hours_text(hours: tuple[int, ...]) -> str:
    first, last = hours[0], hours[-1]
    return f"{first:02d}:00 to {(last + 1) % 24:02d}:00"


def _cell_open(mask: list[list[bool]] | None, days: tuple[int, ...], hours: tuple[int, ...]) -> int:
    """How many weekday-hours of the stretch the venue is open; with no opening hours given, every one counts."""
    if mask is None or not any(any(day) for day in mask):
        return len(days) * len(hours)
    return sum(1 for d in days for h in hours if mask[d][h])


def _weights(
    groups: list[SoundGroup], days: tuple[int, ...], hours: tuple[int, ...]
) -> dict[int, float]:
    return {
        g.index: float(
            sum(
                g.rhythm[d][h]
                for d in days
                for h in hours
                if len(g.rhythm) == 7 and len(g.rhythm[d]) == 24
            )
        )
        for g in groups
    }


def _act_score(
    act: SoundAct, weight: dict[int, float]
) -> tuple[float, dict[int, float], float] | None:
    """The act's score for a stretch, its normalised shares, and the share of the stretch it was scored for. None if the
    groups it was scored for are too small a part of the stretch."""
    scored = {i: w for i, w in weight.items() if i in act.fits and w > 0}
    total = sum(weight.values())
    covered = sum(scored.values())
    if total <= 0 or covered / total < MIN_SCORED_SHARE:
        return None
    shares = {i: w / covered for i, w in scored.items()}
    order = sorted(shares)
    value = raw_score(
        np.array([shares[i] for i in order], dtype=float),
        np.array([act.fits[i] for i in order], dtype=float),
        None,
        WEIGHTS,
    )
    return value, shares, covered / total


def _watch(
    act: SoundAct, shares: dict[int, float], label_of: dict[int, str]
) -> dict[str, Any] | None:
    """The biggest part of the stretch the act ranks poorly for: a group with at least a fifth of the stretch that the act
    ranks below the Fit Verdict's own weak line. None when it suits everyone who is there."""
    weak = [i for i, share in shares.items() if share >= WATCH_SHARE and act.fits[i] < WEIGHTS.weak]
    if not weak:
        return None
    worst = max(weak, key=lambda i: (shares[i], -i))
    return {
        "label": label_of[worst],
        "share": round(shares[worst], 2),
        "rank": round(act.fits[worst], 2),
    }


def build_plan(
    groups: list[SoundGroup],
    acts: list[SoundAct],
    mask: list[list[bool]] | None,
    *,
    top: int = TOP,
    min_scans: int = MIN_CELL_SCANS,
) -> dict[str, Any]:
    """Every stretch of the week with its crowd, how busy it is, and the acts that fit it best."""
    label_of = {g.index: g.label for g in groups}
    raw: list[dict[str, Any]] = []
    for type_key, type_label, days in DAYTYPES:
        for part_key, part_label, hours in DAYPARTS:
            open_hours = _cell_open(mask, days, hours)
            cell: dict[str, Any] = {
                "key": f"{type_key}-{part_key}",
                "days": type_label,
                "part": part_label,
                "hours": hours_text(hours),
                "status": "ok",
                "reason": None,
                "scans": 0.0,
                "busy": None,
                "busy_label": None,
                "mix": [],
                "acts": [],
            }
            if open_hours == 0:
                cell.update(status="closed", reason="You are not open in this stretch.")
                raw.append(cell)
                continue
            weight = _weights(groups, days, hours)
            scans = sum(weight.values())
            cell["scans"] = round(scans, 1)
            cell["_per_hour"] = scans / open_hours
            cell["_weight"] = weight
            if scans < min_scans:
                cell.update(
                    status="thin",
                    reason=f"About {scans:.0f} scans fall in this stretch. The plan starts from {min_scans}, so it does not guess before then.",
                )
            raw.append(cell)
    peak = max(
        (c["_per_hour"] for c in raw if "_per_hour" in c and c["status"] == "ok"), default=0.0
    )
    for cell in raw:
        weight = cell.pop("_weight", None)
        per_hour = cell.pop("_per_hour", None)
        if cell["status"] != "ok" or weight is None or per_hour is None:
            continue
        total = sum(weight.values())
        cell["mix"] = [
            {"index": i, "label": label_of[i], "share": round(w / total, 3)}
            for i, w in sorted(weight.items(), key=lambda kv: (-kv[1], kv[0]))
            if w > 0
        ]
        if peak > 0:
            cell["busy"] = round(per_hour / peak, 2)
            cell["busy_label"] = (
                "busy"
                if cell["busy"] >= BUSY_FROM
                else "quiet"
                if cell["busy"] < QUIET_BELOW
                else "steady"
            )
        ranked: list[tuple[float, SoundAct, dict[int, float]]] = []
        for act in acts:
            got = _act_score(act, weight)
            if got is not None:
                ranked.append((got[0], act, got[1]))
        ranked.sort(key=lambda r: (-round(r[0], 6), r[1].name, r[1].entity_id))
        if not ranked:
            cell.update(
                status="thin",
                reason="Qloo could not rank any of the acts considered for the groups who come in this stretch.",
            )
            continue
        for value, act, shares in ranked[:top]:
            best = max(shares, key=lambda i: (shares[i] * act.fits[i], -i))
            cell["acts"].append(
                {
                    "entity_id": act.entity_id,
                    "name": act.name,
                    "genres": list(act.genres[:3]),
                    "score": round(value),
                    "best_for": label_of[best],
                    "best_share": round(shares[best], 2),
                    "best_rank": round(act.fits[best], 2),
                    "watch": _watch(act, shares, label_of),
                }
            )
    return {
        "version": WEIGHTS.version,
        "formula": formula(WEIGHTS, False),
        "acts_considered": len(acts),
        "cells": raw,
    }


def undated_plan(
    groups: list[tuple[int, str, float]], acts: list[SoundAct], *, top: int = TOP
) -> dict[str, Any]:
    """For a room known only from public lineups there is no time of day: one list for the whole crowd, with the weights of
    its scenes. `groups` is (index, label, share)."""
    weight = {i: share for i, _, share in groups}
    label_of = {i: label for i, label, _ in groups}
    ranked = []
    for act in acts:
        got = _act_score(act, weight)
        if got is not None:
            ranked.append((got[0], act, got[1]))
    ranked.sort(key=lambda r: (-round(r[0], 6), r[1].name, r[1].entity_id))
    return {
        "version": WEIGHTS.version,
        "formula": formula(WEIGHTS, False),
        "acts_considered": len(acts),
        "acts": [
            {
                "entity_id": act.entity_id,
                "name": act.name,
                "genres": list(act.genres[:3]),
                "score": round(value),
                "best_for": label_of[max(shares, key=lambda i: (shares[i] * act.fits[i], -i))],
                "watch": _watch(act, shares, label_of),
            }
            for value, act, shares in ranked[:top]
        ],
    }


# ---------------------------------------------------------------------------------------------------------------- M18
# The Don't-do list and stretch picks (PRD M18). Built only from the per-group ranks Qloo's answers already gave the acts the
# last suggestion run scored: no new Qloo call, no model. The PRD says to release it only after a held-out test, and there is
# none (nobody has told us which acts a crowd dislikes), so it is always labelled an idea and modelled, never advice.
MAIN_SHARE = 0.25  # a group with at least this share of the crowd is one of its main groups
STRETCH_FIT = 0.75  # an act this high for a smaller group is a stretch toward it...
STRETCH_MAIN_FLOOR = 0.4  # ...as long as it does not rank below this for the main groups
DONT_DO_MIN_ACTS = 6  # fewer scored acts than this and there is no "low end" to speak of
DONT_DO_TOP = 3
DONT_DO_NOTE = (
    "Idea only. This is read from the low end of Qloo's rankings, and how well that end predicts what a crowd dislikes has not been "
    "tested (nobody has told us which acts a crowd dislikes). It is modelled from your groups' picks. Use it to ask a question, "
    "not to rule an act out."
)


def _withheld(reason: str) -> dict[str, Any]:
    return {
        "state": "withheld",
        "label": "modelled",
        "idea_only": True,
        "reason": reason,
        "note": DONT_DO_NOTE,
        "leave_off": [],
        "stretch": [],
    }


def dont_do(
    groups: list[tuple[int, str, float]], acts: list[SoundAct], *, top: int = DONT_DO_TOP
) -> dict[str, Any]:
    """Acts the crowd's main groups rank poorly (what to leave off) and acts that reach toward a smaller group without
    alienating the main ones (stretch picks). `groups` is (index, label, share). Said plainly as an untested idea."""
    share = {i: s for i, _, s in groups if s > 0}
    label_of = {i: label for i, label, _ in groups}
    total = sum(share.values())
    if len(share) < 2 or total <= 0:
        return _withheld(
            "There are fewer than two groups, so there is no main crowd and no neighbouring one to compare."
        )
    main = [i for i, s in share.items() if s / total >= MAIN_SHARE] or [
        max(share, key=lambda i: (share[i], -i))
    ]
    leave: list[tuple[float, float, SoundAct, int, float]] = []
    stretch: list[tuple[float, SoundAct, int, float]] = []
    considered = 0
    for act in acts:
        scored = {i: act.fits[i] for i in share if i in act.fits}
        if sum(share[i] for i in scored) / total < MIN_SCORED_SHARE:
            continue
        main_scored = [i for i in main if i in scored]
        if not main_scored:
            continue
        considered += 1
        weight = sum(share[i] for i in main_scored)
        main_fit = sum(share[i] * scored[i] for i in main_scored) / weight
        worst = min(main_scored, key=lambda i: (scored[i], -share[i], i))
        if (
            scored[worst] < WEIGHTS.weak
        ):  # a main group ranks it below the Fit Verdict's own weak line
            leave.append((share[worst] / total, scored[worst], act, worst, main_fit))
            continue
        neighbours = [i for i in scored if i not in main]
        if neighbours and main_fit >= STRETCH_MAIN_FLOOR:
            toward = max(neighbours, key=lambda i: (scored[i], -i))
            if scored[toward] >= STRETCH_FIT:
                stretch.append((scored[toward], act, toward, main_fit))
    if considered < DONT_DO_MIN_ACTS:
        return _withheld(
            f"Only {considered} acts were scored for your main groups; at least {DONT_DO_MIN_ACTS} are needed before there is a low end to read."
        )
    leave.sort(
        key=lambda r: (-r[0], r[1], r[2].name, r[2].entity_id)
    )  # the biggest group put off first, then the lowest rank
    stretch.sort(key=lambda r: (-r[0], r[1].name, r[1].entity_id))
    return {
        "state": "idea_only",
        "label": "modelled",
        "idea_only": True,
        "reason": None,
        "note": DONT_DO_NOTE,
        "acts_considered": considered,
        "main_groups": [label_of[i] for i in sorted(main)],
        "leave_off": [
            {
                "entity_id": act.entity_id,
                "name": act.name,
                "genres": list(act.genres[:3]),
                "main_fit": round(main_fit, 2),
                "group": label_of[worst],
                "group_share": round(share[worst] / total, 2),
                "group_rank": round(rank, 2),
                "reason": (
                    f"Ranks {round(rank * 100)} out of 100 among the acts your crowd picks, for {label_of[worst]} "
                    f"({round(share[worst] / total * 100)}% of your crowd)."
                ),
            }
            for _, rank, act, worst, main_fit in leave[:top]
        ],
        "stretch": [
            {
                "entity_id": act.entity_id,
                "name": act.name,
                "genres": list(act.genres[:3]),
                "main_fit": round(main_fit, 2),
                "toward": label_of[toward],
                "toward_share": round(share[toward] / total, 2),
                "toward_rank": round(rank, 2),
                "reason": (
                    f"Ranks {round(rank * 100)} out of 100 for {label_of[toward]} ({round(share[toward] / total * 100)}% of your crowd) "
                    f"and {round(main_fit * 100)} for your main groups, so it reaches toward them without turning the rest away."
                ),
            }
            for rank, act, toward, main_fit in stretch[:top]
        ],
    }
