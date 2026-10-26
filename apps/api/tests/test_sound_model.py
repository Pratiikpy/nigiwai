"""The Sound plan's rules with no database: how a stretch of the week gets its crowd, which acts rank for it, when it says
nothing instead of guessing. Every name is invented."""

from __future__ import annotations

from nigiwai_api.services import hours as hrs
from nigiwai_api.services import sound_model as sm

OPEN_ALL = [{"open": "07:00", "close": "02:00"}] * 7


def rhythm(*cells: tuple[int, int, float]) -> tuple[tuple[float, ...], ...]:
    grid = [[0.0] * 24 for _ in range(7)]
    for day, hour, n in cells:
        grid[day][hour] += n
    return tuple(tuple(row) for row in grid)


def spread(
    days: tuple[int, ...], hours: tuple[int, ...], each: float
) -> tuple[tuple[float, ...], ...]:
    return rhythm(*[(d, h, each) for d in days for h in hours])


def act(name: str, **fits: float) -> sm.SoundAct:
    return sm.SoundAct(
        name.lower().replace(" ", "-"),
        name,
        ("indie",),
        0.4,
        {int(k[1:]): v for k, v in fits.items()},
    )


MORNING_FOLK = sm.SoundGroup(0, "Morning folk", spread((0, 1, 2, 3), (8, 9, 10), 4.0))  # 48 scans
LATE_DANCE = sm.SoundGroup(
    1, "Weekend dancers", spread((4, 5, 6), (21, 22, 23), 5.0)
)  # 45 scans: 15 in the evening, 30 after 22:00
MASK = hrs.open_mask(OPEN_ALL)
ACTS = [
    act("Quiet Fields", g0=0.95, g1=0.1),
    act("Neon Feast", g0=0.1, g1=0.9),
    act("Middle Road", g0=0.6, g1=0.6),
]


def cell(plan: dict, key: str) -> dict:
    return next(c for c in plan["cells"] if c["key"] == key)


def test_each_stretch_is_ranked_by_the_groups_who_actually_come_then() -> None:
    plan = sm.build_plan([MORNING_FOLK, LATE_DANCE], ACTS, MASK)
    morning = cell(plan, "weekdays-morning")
    assert morning["status"] == "ok"
    assert [a["name"] for a in morning["acts"]] == ["Quiet Fields", "Middle Road", "Neon Feast"]
    assert morning["mix"] == [{"index": 0, "label": "Morning folk", "share": 1.0}]
    assert morning["acts"][0]["best_for"] == "Morning folk"
    # the stretch is wholly one group, so the score is the Fit formula with that group's rank: 100 x 0.95, no risk
    assert morning["acts"][0]["score"] == 95
    assert cell(plan, "weekend-evening")["status"] == "thin"  # 15 scans: under the bar of 20
    weekend_late = cell(plan, "weekend-late")
    assert weekend_late["acts"][0]["name"] == "Neon Feast"
    assert weekend_late["acts"][0]["score"] == 90
    # Neon Feast ranks the morning folk at 0.1, below the 0.5 floor: the score takes the risk off
    assert morning["acts"][-1]["name"] == "Neon Feast"
    assert morning["acts"][-1]["score"] == round(100 * 0.1 * (1 - 0.5 * ((0.5 - 0.1) / 0.5)))


def test_a_stretch_with_too_few_scans_says_so_and_names_no_act() -> None:
    few = sm.SoundGroup(0, "Few", spread((0,), (9,), 4.0))  # 4 scans
    plan = sm.build_plan([few], ACTS, MASK)
    thin = cell(plan, "weekdays-morning")
    assert thin["status"] == "thin"
    assert thin["acts"] == []
    assert "starts from 20" in thin["reason"]
    assert cell(plan, "weekend-evening")["status"] == "thin"
    assert all(c["acts"] == [] for c in plan["cells"])


def test_a_stretch_when_the_room_is_closed_is_left_out_not_guessed() -> None:
    weekday_only = [{"open": "08:00", "close": "17:00"}] * 4 + [None, None, None]
    plan = sm.build_plan([MORNING_FOLK], ACTS, hrs.open_mask(weekday_only))
    assert cell(plan, "weekend-morning")["status"] == "closed"
    assert cell(plan, "weekdays-late")["status"] == "closed"
    assert cell(plan, "weekdays-morning")["status"] == "ok"
    assert cell(plan, "weekdays-afternoon")["status"] in ("thin", "ok")
    assert cell(plan, "weekend-morning")["acts"] == []


def test_with_no_opening_hours_every_stretch_is_considered_and_the_scans_decide() -> None:
    plan = sm.build_plan([MORNING_FOLK], ACTS, None)
    assert cell(plan, "weekdays-morning")["status"] == "ok"
    assert cell(plan, "weekend-late")["status"] == "thin"
    assert not any(c["status"] == "closed" for c in plan["cells"])


def test_an_act_scored_for_too_little_of_a_stretch_is_not_ranked_there() -> None:
    both = sm.SoundGroup(1, "Also mornings", spread((0, 1, 2, 3), (8, 9, 10), 4.0))
    plan = sm.build_plan(
        [MORNING_FOLK, both], [act("Half Known", g0=0.9), act("Fully Known", g0=0.7, g1=0.7)], MASK
    )
    names = [a["name"] for a in cell(plan, "weekdays-morning")["acts"]]
    assert names == [
        "Fully Known"
    ]  # the first was scored for only half of the stretch, under the 60% bar


def test_busyness_is_scans_per_open_hour_against_the_busiest_stretch() -> None:
    busy = sm.SoundGroup(0, "Busy", spread((4, 5, 6), (19, 20, 21), 10.0))  # evenings, heavy
    quiet = sm.SoundGroup(1, "Quiet", spread((0, 1, 2, 3), (13, 14), 2.5))  # afternoons, light
    plan = sm.build_plan([busy, quiet], ACTS, MASK, min_scans=5)
    assert cell(plan, "weekend-evening")["busy"] == 1.0
    assert cell(plan, "weekend-evening")["busy_label"] == "busy"
    assert cell(plan, "weekdays-afternoon")["busy_label"] == "quiet"
    assert 0 < cell(plan, "weekdays-afternoon")["busy"] < sm.QUIET_BELOW


def test_ties_are_broken_by_name_and_the_list_is_capped() -> None:
    many = [act(f"Act {c}", g0=0.8) for c in "DBACEFGH"]
    plan = sm.build_plan([MORNING_FOLK], many, MASK, top=3)
    assert [a["name"] for a in cell(plan, "weekdays-morning")["acts"]] == [
        "Act A",
        "Act B",
        "Act C",
    ]


def test_the_plan_states_its_formula_and_how_many_acts_it_weighed() -> None:
    plan = sm.build_plan([MORNING_FOLK], ACTS, MASK)
    assert plan["acts_considered"] == 3
    assert "Score = 100 x group fit" in plan["formula"]
    assert plan["version"] == "v0"


def test_a_room_known_only_from_public_lineups_gets_one_list_and_no_time_of_day() -> None:
    plan = sm.undated_plan([(0, "Folk scene", 0.7), (1, "Dance scene", 0.3)], ACTS)
    assert plan["acts"][0]["name"] == "Quiet Fields"
    assert plan["acts"][0]["best_for"] == "Folk scene"
    assert "cells" not in plan


def test_the_hours_of_a_stretch_read_as_a_span() -> None:
    assert sm.hours_text((5, 6, 7, 8, 9, 10, 11)) == "05:00 to 12:00"
    assert sm.hours_text((22, 23, 0, 1, 2, 3, 4)) == "22:00 to 05:00"


def test_an_act_that_ranks_poorly_for_a_big_part_of_a_stretch_is_flagged_and_one_that_suits_everyone_is_not() -> (
    None
):
    both = [
        sm.SoundGroup(0, "Morning folk", spread((0, 1, 2, 3), (8, 9, 10), 4.0)),
        sm.SoundGroup(
            1, "Also mornings", spread((0, 1, 2, 3), (8, 9, 10), 3.0)
        ),  # 3 of every 7 scans
    ]
    split = act("Folk Only", g0=0.95, g1=0.1)
    everyone = act("Common Ground", g0=0.7, g1=0.7)
    plan = sm.build_plan(both, [split, everyone], MASK)
    acts = {a["name"]: a for a in cell(plan, "weekdays-morning")["acts"]}
    assert acts["Folk Only"]["watch"] == {"label": "Also mornings", "share": 0.43, "rank": 0.1}
    assert acts["Common Ground"]["watch"] is None
    # a poorly ranked group that is only a sliver of the stretch is not worth a warning
    sliver = [
        sm.SoundGroup(0, "Morning folk", spread((0, 1, 2, 3), (8, 9, 10), 9.0)),
        sm.SoundGroup(1, "A few others", spread((0, 1, 2, 3), (8, 9, 10), 1.0)),
    ]
    only = cell(sm.build_plan(sliver, [split], MASK), "weekdays-morning")["acts"][0]
    assert only["watch"] is None
    # the same flag on the one list a lineup-only room gets
    flagged = sm.undated_plan([(0, "Folk scene", 0.6), (1, "Dance scene", 0.4)], [split])
    assert flagged["acts"][0]["watch"] == {"label": "Dance scene", "share": 0.4, "rank": 0.1}


# ------------------------------------------------------------------------------------------------- M18, Don't-do list
BIG = [(0, "Quiet crowd", 0.6), (1, "Dance crowd", 0.3), (2, "Jazz crowd", 0.1)]
POOL = [
    act("Quiet Fields", g0=0.95, g1=0.5, g2=0.4),
    act("Soft Rain", g0=0.9, g1=0.6, g2=0.5),
    act("Neon Feast", g0=0.1, g1=0.9, g2=0.3),  # the big group ranks it low
    act("Hard Floor", g0=0.15, g1=0.95, g2=0.2),
    act("Middle Road", g0=0.6, g1=0.6, g2=0.6),
    act(
        "Late Brass", g0=0.5, g1=0.5, g2=0.9
    ),  # reaches toward the small jazz group, not off-putting to the big one
    act("Plain Pop", g0=0.7, g1=0.7, g2=0.7),
]


def test_the_dont_do_list_is_what_the_main_groups_rank_lowest_and_is_always_called_an_idea() -> (
    None
):
    got = sm.dont_do(BIG, POOL)
    assert got["state"] == "idea_only" and got["label"] == "modelled" and got["idea_only"] is True
    assert "Idea only" in got["note"] and "has not been tested" in got["note"]
    assert got["main_groups"] == [
        "Quiet crowd",
        "Dance crowd",
    ]  # 60% and 30% of the crowd; the 10% group is not main
    names = [a["name"] for a in got["leave_off"]]
    assert names == [
        "Neon Feast",
        "Hard Floor",
    ]  # both put off the 60% group; the lower rank comes first
    first = got["leave_off"][0]
    assert first["group"] == "Quiet crowd" and first["group_rank"] == 0.1
    assert "out of 100" in first["reason"] and "60% of your crowd" in first["reason"]
    assert all(
        a["group_rank"] < 0.35 for a in got["leave_off"]
    )  # below the Fit Verdict's own weak line


def test_a_stretch_pick_reaches_a_smaller_group_without_alienating_the_main_ones() -> None:
    got = sm.dont_do(BIG, POOL)
    assert [a["name"] for a in got["stretch"]] == ["Late Brass"]
    pick = got["stretch"][0]
    assert pick["toward"] == "Jazz crowd" and pick["toward_rank"] == 0.9
    assert pick["main_fit"] >= sm.STRETCH_MAIN_FLOOR
    # an act the main groups rank low is never a stretch, however well it ranks for a small group
    assert "Neon Feast" not in [a["name"] for a in got["stretch"]]


def test_the_dont_do_list_is_the_same_every_time_and_says_nothing_without_a_low_end() -> None:
    assert sm.dont_do(BIG, POOL) == sm.dont_do(BIG, list(reversed(POOL)))
    few = sm.dont_do(BIG, POOL[:3])
    assert few["state"] == "withheld" and few["leave_off"] == [] and "at least 6" in few["reason"]
    one = sm.dont_do([(0, "Only", 1.0)], POOL)
    assert one["state"] == "withheld" and "fewer than two groups" in one["reason"]
    # acts scored for too little of the crowd are not read at all
    thin = [act(f"Act {n}", g2=0.1) for n in range(8)]
    assert sm.dont_do(BIG, thin)["state"] == "withheld"
