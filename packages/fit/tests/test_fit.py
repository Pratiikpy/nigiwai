"""The Fit Verdict, checked against hand calculations and the rules in the README. No Qloo data is used: every number is
invented for the test."""

from __future__ import annotations

import json
import re

import numpy as np
import pytest
from nigiwai_fit import (
    Constraint,
    Crowd,
    Group,
    Observation,
    Weights,
    compute_fit,
    percentile_rank,
    raw_score,
    to_dict,
)

REFS_MID = tuple(0.60 + 0.01 * i for i in range(10))  # 0.60 .. 0.69
TEN = tuple(0.1 * i + 0.01 for i in range(10))  # 0.01, 0.11 .. 0.91


def group(index: int, label: str, share: float, weekday: tuple[float, ...] | None = None) -> Group:
    return Group(
        index,
        label,
        share,
        40.0,
        (f"s{index}a", f"s{index}b"),
        (f"Seed {index}A", f"Seed {index}B"),
        weekday,
    )


def crowd(**over: object) -> Crowd:
    base: dict[str, object] = {"kind": "guests", "n": 112, "provisional": False, "sufficient": True}
    base.update(over)
    return Crowd(**base)  # type: ignore[arg-type]


def test_percentile_rank_counts_ties_as_half() -> None:
    assert percentile_rank(0.7, (0.1, 0.2, 0.3, 0.4)) == 1.0
    assert percentile_rank(0.0, (0.1, 0.2, 0.3, 0.4)) == 0.0
    assert percentile_rank(0.25, (0.1, 0.2, 0.3, 0.4)) == 0.5
    assert percentile_rank(0.3, (0.1, 0.2, 0.3, 0.4)) == 0.625  # beats 2, ties 1
    with pytest.raises(ValueError, match="at least one reference"):
        percentile_rank(0.5, ())


def test_score_matches_the_formula_worked_by_hand_without_peer_evidence() -> None:
    # Shares .6 and .4, ranks .9 and .3: group fit .66, risk = .4 * (.5 - .3) / .5 = .16,
    # score = 100 * .66 * (1 - .5 * .16).
    groups = [group(0, "Late-night listeners", 0.6), group(1, "Slow-Sunday readers", 0.4)]
    obs = [
        Observation(0, 0.85, TEN),  # beats 9 of 10 -> 0.9
        Observation(1, 0.295, TEN),  # beats 3 of 10 -> 0.3
    ]
    res = compute_fit("cand", groups, obs, crowd())
    assert res.status == "ok"
    assert res.score == round(100 * (0.6 * 0.9 + 0.4 * 0.3) * (1 - 0.5 * 0.16))
    assert res.components["group_fit"] == pytest.approx(0.66)
    assert res.components["risk"] == pytest.approx(0.16)
    assert not res.peer_used and any("Peer evidence is omitted" in n for n in res.notes)
    assert "carries no weight" in res.formula


def test_peer_evidence_enters_with_its_weight_when_present() -> None:
    groups = [group(0, "A", 1.0)]
    obs = [Observation(0, 0.5, TEN)]  # beats 5 of 10 -> 0.5
    without = compute_fit("c", groups, obs, crowd())
    with_peer = compute_fit("c", groups, obs, crowd(), peer=1.0)
    assert without.score == 50
    assert with_peer.score == round(100 * (0.8 * 0.5 + 0.2 * 1.0))
    assert with_peer.peer_used and "0.2 x peer evidence" in with_peer.formula


def test_the_same_inputs_give_the_same_score_band_and_hash() -> None:
    groups = [group(0, "A", 0.5), group(1, "B", 0.5)]
    obs = [Observation(0, 0.65, REFS_MID), Observation(1, 0.45, REFS_MID)]
    mem = tuple((float(a), 1.0 - float(a)) for a in np.linspace(0, 1, 40))
    a = compute_fit("c", groups, obs, crowd(memberships=mem))
    b = compute_fit("c", groups, obs, crowd(memberships=mem))
    assert to_dict(a) == to_dict(b)
    c = compute_fit("c", groups, [Observation(0, 0.66, REFS_MID), obs[1]], crowd(memberships=mem))
    assert c.input_hash != a.input_hash


def test_renaming_a_group_or_a_seed_changes_neither_the_hash_nor_the_score() -> None:
    obs = [Observation(0, 0.65, REFS_MID)]
    a = compute_fit("c", [group(0, "Late-night listeners", 1.0)], obs, crowd())
    renamed = Group(0, "Night owls", 1.0, 40.0, ("s0a", "s0b"), ("Other A", "Other B"), None)
    b = compute_fit("c", [renamed], obs, crowd())
    assert (a.input_hash, a.score, a.band) == (b.input_hash, b.score, b.band)


def test_band_contains_the_score_and_narrows_with_more_references() -> None:
    groups = [group(0, "A", 0.5), group(1, "B", 0.5)]
    few_refs = tuple(0.10 * i for i in range(8))
    many_refs = tuple(0.0125 * i for i in range(80))
    few = compute_fit(
        "c", groups, [Observation(0, 0.35, few_refs), Observation(1, 0.35, few_refs)], crowd()
    )
    many = compute_fit(
        "c", groups, [Observation(0, 0.35, many_refs), Observation(1, 0.35, many_refs)], crowd()
    )
    for r in (few, many):
        assert r.band is not None and r.band[0] <= (r.score or 0) <= r.band[1]
    assert many.band is not None and few.band is not None
    assert (many.band[1] - many.band[0]) <= (few.band[1] - few.band[0])


def test_a_small_mixed_crowd_widens_the_band() -> None:
    groups = [group(0, "A", 0.5), group(1, "B", 0.5)]
    obs = [
        Observation(0, 0.95, REFS_MID),
        Observation(1, 0.10, REFS_MID),
    ]  # rank 1.0 for A, 0.0 for B
    fixed = compute_fit("c", groups, obs, crowd())
    mixed = tuple(
        (1.0, 0.0) if i % 2 else (0.0, 1.0) for i in range(8)
    )  # eight members, half in each
    varying = compute_fit("c", groups, obs, crowd(memberships=mixed))
    assert varying.band is not None and fixed.band is not None
    assert (varying.band[1] - varying.band[0]) > (fixed.band[1] - fixed.band[0])


def test_no_number_when_the_crowd_is_too_thin() -> None:
    res = compute_fit(
        "c",
        [group(0, "A", 1.0)],
        [Observation(0, 0.5, REFS_MID)],
        crowd(sufficient=False, reason="Only 6 events with a lineup; this needs 10."),
    )
    assert res.status == "insufficient" and res.score is None and res.band is None
    assert "needs 10" in res.reason


def test_a_failed_constraint_gives_no_score_and_says_why() -> None:
    cons = [
        Constraint("excluded genres", "fail", "Death Metal is on your excluded list"),
        Constraint("capacity", "not_scored", "Qloo has no stage size for acts"),
    ]
    res = compute_fit("c", [group(0, "A", 1.0)], [Observation(0, 0.5, REFS_MID)], crowd(), cons)
    assert res.status == "fails_constraint" and res.score is None
    assert res.reason == "Fails: Death Metal is on your excluded list."
    assert [c.status for c in res.constraints] == ["fail", "not_scored"]


def test_a_group_qloo_could_not_score_is_left_out_and_the_shares_renormalise() -> None:
    groups = [group(0, "A", 0.5), group(1, "B", 0.3), group(2, "C", 0.2)]
    obs = [
        Observation(0, 0.5, TEN),  # 0.5
        Observation(1, None, ()),  # Qloo dropped the act for this group
        Observation(2, 0.95, TEN),  # 1.0
    ]
    res = compute_fit("c", groups, obs, crowd())
    assert res.status == "ok"
    by = {g.index: g for g in res.groups}
    assert by[1].status == "no_affinity" and by[1].share == 0.0
    assert by[0].share == pytest.approx(0.5 / 0.7) and by[2].share == pytest.approx(0.2 / 0.7)
    assert any("no taste link" in w and "B" in w for w in res.watch)


def test_too_little_of_the_crowd_scored_gives_no_number() -> None:
    groups = [group(0, "A", 0.3), group(1, "B", 0.7)]
    obs = [Observation(0, 0.5, REFS_MID), Observation(1, None, ())]
    res = compute_fit("c", groups, obs, crowd())
    assert res.status == "insufficient" and "30%" in res.reason


def test_nothing_scored_is_unscored() -> None:
    res = compute_fit("c", [group(0, "A", 1.0)], [Observation(0, None, ())], crowd())
    assert res.status == "unscored" and res.score is None


def test_too_few_references_leaves_the_group_out() -> None:
    groups = [group(0, "A", 0.5), group(1, "B", 0.5)]
    obs = [Observation(0, 0.5, REFS_MID), Observation(1, 0.9, REFS_MID[:5])]
    res = compute_fit("c", groups, obs, crowd(), weights=Weights(min_scored_share=0.4))
    assert {g.index: g.status for g in res.groups} == {0: "scored", 1: "too_few_references"}


def test_the_score_if_the_whole_crowd_were_one_group() -> None:
    groups = [group(0, "A", 0.5), group(1, "B", 0.5)]
    obs = [Observation(0, 0.95, REFS_MID), Observation(1, 0.10, REFS_MID)]
    res = compute_fit("c", groups, obs, crowd())
    assert {g.index: g.alone for g in res.groups} == {0: 100, 1: 0}


def test_reasons_and_watch_outs_name_the_groups_and_their_seed_acts() -> None:
    groups = [group(0, "Late-night listeners", 0.6), group(1, "Run-club regulars", 0.4)]
    obs = [Observation(0, 0.95, REFS_MID), Observation(1, 0.10, REFS_MID)]
    res = compute_fit("c", groups, obs, crowd())
    assert any(
        "Late-night listeners" in w and "Seed 0A and Seed 0B" in w and "60%" in w for w in res.why
    )
    assert any("Run-club regulars" in w and "40%" in w for w in res.watch)


def test_a_lineup_crowd_is_provisional_and_counts_acts() -> None:
    res = compute_fit(
        "c",
        [group(0, "Scene A", 1.0)],
        [Observation(0, 0.95, REFS_MID)],
        crowd(kind="lineup", n=33, provisional=True),
    )
    assert res.provisional and any("Provisional" in n for n in res.notes)
    assert any("acts" in w for w in res.why)


def test_nights_follow_each_group_weekday_pattern_weighted_by_share_and_fit() -> None:
    fri_sat = (0, 0, 0, 0, 0.5, 0.5, 0.0)
    sun = (0, 0, 0, 0, 0, 0, 1.0)
    groups = [group(0, "A", 0.5, fri_sat), group(1, "B", 0.5, sun)]
    obs = [Observation(0, 0.95, REFS_MID), Observation(1, 0.10, REFS_MID)]  # fits A, not B
    res = compute_fit("c", groups, obs, crowd())
    assert res.suits == (4, 5) and res.nights is not None and res.nights[6] == 0.0


def test_a_group_with_no_pattern_of_its_own_uses_the_venues_weekdays() -> None:
    groups = [group(0, "A", 1.0)]
    obs = [Observation(0, 0.95, REFS_MID)]
    venue = (0, 0, 0, 0, 0.55, 0.45, 0)
    res = compute_fit("c", groups, obs, crowd(), venue_weekday=venue)
    assert res.suits == (4, 5)
    assert (
        compute_fit("c", groups, obs, crowd(), venue_weekday=venue).input_hash
        != compute_fit("c", groups, obs, crowd()).input_hash
    )


def test_no_weekday_data_means_no_nights() -> None:
    res = compute_fit("c", [group(0, "A", 1.0)], [Observation(0, 0.95, REFS_MID)], crowd())
    assert res.nights is None and res.suits == ()


def test_raw_score_is_monotone_in_group_fit() -> None:
    w = Weights()
    shares = np.array([0.5, 0.5])
    low = raw_score(shares, np.array([0.2, 0.2]), None, w)
    high = raw_score(shares, np.array([0.8, 0.8]), None, w)
    assert 0 <= low < high <= 100


def test_wording_is_fit_never_success_revenue_or_probability() -> None:
    groups = [group(0, "A", 0.6), group(1, "B", 0.4)]
    obs = [Observation(0, 0.95, REFS_MID), Observation(1, 0.10, REFS_MID)]
    res = compute_fit("c", groups, obs, crowd(provisional=True))
    text = json.dumps(to_dict(res)).lower()
    assert not re.search(r"\b(success|revenue|probab|sales|forecast|guarantee)", text)
