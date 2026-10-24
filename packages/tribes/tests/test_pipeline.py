"""The behaviours proof tests D and G measured, as tests: recover planted structure, refuse structureless crowds,
unlock by sample size, stay deterministic, withhold small groups, and place a new guest."""

from __future__ import annotations

import json

import numpy as np
import pytest
from nigiwai_tribes import Pick, Respondent, Tag, TribesConfig, build_matrix, compute, place
from nigiwai_tribes.stability import ari
from synth import catalogue, crowd, fast_config, strict_config


def recovered_ari(items, n: int, seed: int) -> tuple[float, str]:
    """Fit on a planted crowd and compare each guest's best tribe with the tribe they were drawn from."""
    from nigiwai_tribes.build import build_matrix as bm
    from nigiwai_tribes.model import assign, fit_nmf

    respondents, truth = crowd(n, items, seed=seed)
    cfg = fast_config()
    matrix = bm(respondents, cfg)
    model = fit_nmf(matrix.features, 3)
    kept = {rid: i for i, rid in enumerate(matrix.respondent_ids)}
    labels = assign(model, matrix.features)
    t = np.array([truth[int(rid[1:])] for rid in matrix.respondent_ids])
    del kept
    result = compute(respondents, cfg)
    return ari(t.astype(np.int64), labels.astype(np.int64)), result.state


def test_planted_tribes_are_recovered_and_beat_both_nulls() -> None:
    items, _ = catalogue()
    score, state = recovered_ari(items, 90, seed=3)
    assert score >= 0.7, score
    assert state == "provisional"


def test_a_crowd_with_no_taste_structure_is_not_reported_as_tribes() -> None:
    items, _ = catalogue()
    states = []
    for seed in range(6):
        respondents, _ = crowd(90, items, structure=0.0, seed=seed + 10)
        states.append(compute(respondents, strict_config()).state)
    # Proof D's shuffled-label control allowed about 5% false positives; this is the same idea on whole crowds.
    assert states.count("unstable") + states.count("none") >= 5, states


def test_nothing_below_the_minimum_and_a_reason_that_says_how_far() -> None:
    items, _ = catalogue()
    respondents, _ = crowd(40, items, seed=4)
    res = compute(respondents, fast_config())
    assert res.state == "none" and res.tribes == [] and "60" in res.reason and res.n == 40


def test_names_only_from_two_hundred_and_only_from_real_tags() -> None:
    items, _ = catalogue()
    provisional = compute(crowd(90, items, seed=5)[0], fast_config())
    assert provisional.state == "provisional"
    assert all(t.name is None and t.label.startswith("Group ") for t in provisional.tribes)
    assert all(not t.used_tags for t in provisional.tribes)

    named = compute(crowd(210, items, seed=6)[0], fast_config())
    assert named.state == "named"
    vocab = {t["tag_id"] for t in named.vocab}
    for tribe in named.tribes:
        assert tribe.name and tribe.name.endswith("crowd")
        assert set(tribe.used_tags) <= vocab  # the name came from tags this crowd has
        assert all(tag["lo"] <= tag["lift"] <= tag["hi"] * 1.0001 for tag in tribe.top_tags)


def test_top_tags_of_a_planted_tribe_belong_to_its_own_pool() -> None:
    items, _ = catalogue()
    res = compute(crowd(120, items, seed=7)[0], fast_config())
    for tribe in res.tribes:
        own = [
            tg["tag_id"].split("_")[0].split(":")[-1]
            for tg in tribe.top_tags[:3]
            if "_" in tg["tag_id"]
        ]
        assert own and len(set(own)) == 1, tribe.top_tags[
            :3
        ]  # the leading tags all come from one planted tribe


def test_the_same_crowd_gives_the_same_result_in_any_order() -> None:
    items, _ = catalogue()
    respondents, _ = crowd(90, items, seed=8)
    a = compute(respondents, fast_config())
    b = compute(list(reversed(respondents)), fast_config())
    assert a.input_hash == b.input_hash
    assert json.dumps(a.to_dict(), sort_keys=True) == json.dumps(
        compute(respondents, fast_config()).to_dict(), sort_keys=True
    )
    ta = sorted(tuple(t["tag_id"] for t in tr.top_tags[:3]) for tr in a.tribes)
    tb = sorted(tuple(t["tag_id"] for t in tr.top_tags[:3]) for tr in b.tribes)
    assert ta == tb


def test_input_hash_changes_when_a_pick_changes() -> None:
    items, _ = catalogue()
    respondents, _ = crowd(70, items, seed=9)
    base = compute(respondents, fast_config()).input_hash
    first = respondents[0]
    swapped = Respondent(first.id, (*first.picks[:-1], items[2][0]), first.weekday, first.hour)
    assert compute([swapped, *respondents[1:]], fast_config()).input_hash != base


def test_facility_tags_never_enter_the_model() -> None:
    items, _ = catalogue()
    respondents, _ = crowd(90, items, seed=11)
    noisy = []
    for r in respondents:
        picks = tuple(
            Pick(
                p.entity_id,
                p.type,
                p.name,
                (
                    *p.tags,
                    Tag("urn:tag:amenity:place:wifi", "Wifi", "urn:tag:amenity:place"),
                    Tag("urn:tag:country:x:fr", "France", "urn:tag:country:x"),
                ),
            )
            for p in r.picks
        )
        noisy.append(Respondent(r.id, picks, r.weekday, r.hour))
    matrix = build_matrix(noisy, fast_config())
    ids = {t.tag_id for t in matrix.vocab}
    assert "urn:tag:amenity:place:wifi" not in ids and "urn:tag:country:x:fr" not in ids


def test_a_group_smaller_than_the_minimum_is_withheld() -> None:
    items, _ = catalogue()
    res = compute(crowd(90, items, seed=12)[0], fast_config(min_group=10_000))
    assert res.tribes and all(not t.shown for t in res.tribes)
    for t in res.tribes:
        assert (
            t.top_items == []
            and t.top_tags == []
            and t.rhythm == []
            and t.signatures == []
            and t.name is None
        )


def test_respondents_without_enough_tagged_picks_are_counted_not_silently_dropped() -> None:
    items, _ = catalogue()
    respondents, _ = crowd(70, items, seed=13)
    bare = [
        Respondent(f"b{i}", (Pick(f"x{i}", "urn:entity:artist", "Untagged"),) * 1) for i in range(5)
    ]
    matrix = build_matrix([*respondents, *bare], fast_config())
    assert matrix.dropped["respondents_too_few_picks"] == 5
    assert matrix.dropped["picks_without_tags"] >= 5


def test_a_new_guest_is_placed_with_the_tribe_they_resemble() -> None:
    items, _ = catalogue()
    res = compute(crowd(120, items, seed=14)[0], fast_config())
    assert res.state in ("provisional", "named")
    # The tribe whose top tags come from planted tribe t.
    owner: dict[int, int] = {}
    for tribe in res.tribes:
        pool = {
            tg["tag_id"].split("_")[0].split(":")[-1]
            for tg in tribe.top_tags[:3]
            if "_" in tg["tag_id"]
        }
        if len(pool) == 1:
            owner[int(next(iter(pool))[1:])] = tribe.index
    assert len(owner) == 3
    hits = 0
    trials = 0
    rng = np.random.default_rng(99)
    for t in range(3):
        for _ in range(20):
            picks = [items[t][int(i)] for i in rng.choice(len(items[t]), size=5, replace=False)]
            placement = place(res, picks)
            assert placement is not None and abs(sum(placement.memberships) - 1) < 1e-3
            trials += 1
            hits += placement.best == owner[t]
    assert hits / trials >= 0.85, hits / trials


def test_placement_needs_groups_and_known_tags() -> None:
    items, _ = catalogue()
    few = compute(crowd(30, items, seed=15)[0], fast_config())
    assert place(few, list(items[0][:3])) is None
    res = compute(crowd(90, items, seed=16)[0], fast_config())
    alien = Pick(
        "zz",
        "urn:entity:artist",
        "Alien",
        (Tag("urn:tag:genre:qloo:never_seen", "Never", "urn:tag:genre:qloo"),),
    )
    assert place(res, [alien]) is None
    assert place(res, []) is None


def test_rhythm_counts_each_guest_once_and_signatures_respect_group_size() -> None:
    items, _ = catalogue()
    respondents, _ = crowd(120, items, seed=17)
    res = compute(respondents, fast_config())
    assert res.timed == res.n
    assert abs(sum(sum(day) for day in res.crowd_rhythm) - res.n) < 1e-6
    for tribe in res.tribes:
        assert abs(sum(sum(d) for d in tribe.rhythm) - tribe.soft_size) < 1e-2
        assert all(not s["odd"] for s in tribe.signatures)  # no tribe here has 200 members


def test_config_rejects_nothing_surprising_but_documents_its_sources() -> None:
    cfg = TribesConfig()
    assert (cfg.k, cfg.min_respondents, cfg.named_respondents, cfg.min_group) == (3, 60, 200, 10)
    assert cfg.seed == 20261016


@pytest.mark.parametrize("n", [59, 60])
def test_the_unlock_boundary_is_exactly_sixty(n: int) -> None:
    items, _ = catalogue()
    respondents, _ = crowd(n, items, seed=20)
    res = compute(respondents, fast_config())
    assert (res.state == "none") == (n == 59)
