"""Grow's rules with no database or Qloo: which genres count as missing from a crowd, when ghost customers are group-specific, and
when a list of places may say it was matched to the crowd or to one group. Every name is invented."""

from __future__ import annotations

import pytest
from nigiwai_api.services import grow_model as gm

INDIE = "urn:tag:genre:qloo:indie"
FOLK = "urn:tag:genre:qloo:folk"
SHOEGAZE = "urn:tag:subgenre:qloo:shoegaze"
DREAM = "urn:tag:genre:qloo:dream_pop"
LOUD = "urn:tag:theme:qloo:loud"


def act(entity_id: str, name: str, *tags: tuple[str, str], affinity: float = 0.9) -> gm.Neighbour:
    return gm.Neighbour(entity_id, name, affinity, tuple(tags))


def presence(
    total: int = 400,
    carriers: dict[str, int] | None = None,
    share: dict[int, dict[str, float]] | None = None,
    min_group: int = gm.MIN_GROUP_GUESTS,
) -> gm.Presence:
    return gm.Presence(
        "guests",
        total,
        min_group,
        carriers if carriers is not None else {INDIE: 300, FOLK: 120},
        share if share is not None else {0: {INDIE: 0.7, FOLK: 0.2}},
        {INDIE: "Indie", FOLK: "Folk"},
    )


GROUP = gm.GroupInfo(0, "Indie lovers", 1.0, 120.0)
NEAR = [
    act("a1", "Amber Lanes", (INDIE, "Indie"), (SHOEGAZE, "Shoegaze"), affinity=0.95),
    act("a2", "Birch and Wire", (INDIE, "Indie"), (SHOEGAZE, "Shoegaze"), affinity=0.9),
    act("a3", "Cold Harbour", (INDIE, "Indie"), (DREAM, "Dream pop"), affinity=0.85),
]


# --------------------------------------------------------------------------------------------- comparing lists
def test_jaccard_is_shared_over_combined() -> None:
    assert gm.jaccard(["a", "b", "c"], ["b", "c", "d"]) == pytest.approx(0.5)
    assert gm.jaccard(["a"], ["a"]) == 1.0
    assert gm.jaccard(["a"], ["b"]) == 0.0
    assert gm.jaccard([], []) == 0.0


def test_mean_pairwise_needs_two_lists_and_only_reads_the_first_ten() -> None:
    assert gm.mean_pairwise({0: ["a"]}) is None
    ten = [f"x{i}" for i in range(10)]
    # the eleventh item is outside what is compared
    assert gm.mean_pairwise({0: [*ten, "only-here"], 1: [*ten, "only-there"]}) == 1.0
    assert gm.mean_pairwise({0: ["a", "b"], 1: ["c", "d"], 2: ["a", "b"]}) == pytest.approx(1 / 3)


def test_seed_effect_is_how_much_the_list_changed() -> None:
    assert gm.seed_effect(["a", "b"], ["a", "b"]) == 0.0
    assert gm.seed_effect(["a", "b"], ["c", "d"]) == 1.0
    assert gm.seed_effect([], ["a"]) is None
    assert gm.seed_effect(["a"], []) is None


# -------------------------------------------------------------------------------------------------- genre tags
def test_only_genre_and_subgenre_tags_are_kept_whatever_the_stored_type() -> None:
    got = gm.genre_tags(
        [
            ("urn:tag:genre:qloo:indie", "Indie", "urn:tag:genre:qloo"),
            ("urn:tag:subgenre:qloo:shoegaze", "Shoegaze", ""),
            ("urn:tag:theme:qloo:heartbreak", "Heartbreak", "urn:tag:theme:qloo"),
            ("urn:tag:audience:qloo:loyal", "Loyal", "urn:tag:audience:qloo"),
            ("urn:tag:instrument:qloo:drums", "Drums", "urn:tag:instrument:qloo"),
            ("urn:tag:keywords:qloo:x", "Odd id, genre type", "urn:tag:genre:qloo"),
            ("urn:tag:genre:qloo:blank", "   ", "urn:tag:genre:qloo"),
            ("urn:tag:genre:qloo:indie", "Indie again", "urn:tag:genre:qloo"),
            ("short", "No namespace", "urn:tag:genre:qloo"),
        ]
    )
    assert dict(got) == {
        "urn:tag:genre:qloo:indie": "Indie",
        "urn:tag:subgenre:qloo:shoegaze": "Shoegaze",
        "urn:tag:keywords:qloo:x": "Odd id, genre type",
        "short": "No namespace",
    }


# --------------------------------------------------------------------------------------------------- ghosts
def test_a_genre_the_crowd_lacks_in_acts_that_share_one_it_has_is_a_ghost() -> None:
    found = gm.find_ghosts([GROUP], {0: NEAR}, presence())
    assert [g.tag for g in found] == ["Shoegaze"]
    ghost = found[0]
    assert ghost.bridges == ("Indie",)
    assert ghost.neighbours_with_tag == 2
    assert [a[1] for a in ghost.acts] == ["Amber Lanes", "Birch and Wire"]  # best first
    assert ghost.acts[0][2] == ("Indie", "Shoegaze")
    assert ghost.unit == "guests"


def test_a_count_under_the_minimum_group_size_is_not_shown() -> None:
    # nobody in the crowd carries it
    assert gm.find_ghosts([GROUP], {0: NEAR}, presence())[0].carrying is None
    # 15 of 400 carry it (3.75%): absent enough, and a count of 15 may be shown
    shown = gm.find_ghosts([GROUP], {0: NEAR}, presence(carriers={INDIE: 300, SHOEGAZE: 15}))
    assert shown[0].carrying == 15
    # 5 of 400 carry it: under the minimum of 10, so only "under 10" can be said
    small = gm.find_ghosts([GROUP], {0: NEAR}, presence(carriers={INDIE: 300, SHOEGAZE: 5}))
    assert small[0].carrying is None


def test_a_genre_many_guests_already_carry_is_not_missing() -> None:
    common = presence(carriers={INDIE: 300, SHOEGAZE: 30})  # 7.5%
    assert gm.find_ghosts([GROUP], {0: NEAR}, common) == []
    own = presence(share={0: {INDIE: 0.7, SHOEGAZE: 0.06}})  # the group itself has it, a little
    assert gm.find_ghosts([GROUP], {0: NEAR}, own) == []


def test_one_act_is_not_enough_and_neither_is_a_genre_with_no_link_to_the_group() -> None:
    lone = [NEAR[0], act("a9", "Dune Parade", (INDIE, "Indie"))]
    assert gm.find_ghosts([GROUP], {0: lone}, presence()) == []
    unlinked = [
        act("b1", "Ember Choir", (SHOEGAZE, "Shoegaze")),
        act("b2", "Fallow Fields", (SHOEGAZE, "Shoegaze")),
        act("b3", "Garnet Row", (INDIE, "Indie")),
    ]
    assert gm.find_ghosts([GROUP], {0: unlinked}, presence()) == []


def test_a_genre_the_group_already_has_is_never_a_ghost() -> None:
    folk = [
        act("c1", "Hollow Pines", (INDIE, "Indie"), (FOLK, "Folk")),
        act("c2", "Iron Meadow", (INDIE, "Indie"), (FOLK, "Folk")),
    ]
    both_groups_have_it = presence(
        share={0: {INDIE: 0.7, FOLK: 0.4}}, carriers={INDIE: 300, FOLK: 2}
    )
    assert gm.find_ghosts([GROUP], {0: folk}, both_groups_have_it) == []


def test_a_group_with_nothing_it_clearly_has_or_too_few_members_is_not_read() -> None:
    faint = presence(share={0: {INDIE: 0.1}})
    assert gm.find_ghosts([GROUP], {0: NEAR}, faint) == []
    tiny = gm.GroupInfo(0, "Indie lovers", 1.0, 6.0)
    assert gm.find_ghosts([tiny], {0: NEAR}, presence()) == []
    # public lineups count acts, so a scene of three acts is readable
    lineup = gm.Presence(
        "acts", 40, gm.MIN_GROUP_ACTS, {INDIE: 30}, {0: {INDIE: 0.8}}, {INDIE: "Indie"}
    )
    scene = gm.GroupInfo(0, "Indie scene", 1.0, 3.0)
    got = gm.find_ghosts([scene], {0: NEAR}, lineup)
    assert [g.tag for g in got] == ["Shoegaze"]
    assert got[0].unit == "acts"


def test_a_variant_of_a_genre_the_group_has_is_not_a_ghost() -> None:
    assert gm.variant_of("Metal", "Heavy Metal")
    assert gm.variant_of("Electropop", "Pop")
    assert gm.variant_of("Indie", "Indie Rock")
    assert not gm.variant_of("Shoegaze", "Indie")
    assert not gm.variant_of("R&B", "Blues")
    assert not gm.variant_of("Ab", "Abc")  # under three letters is not compared
    heavy = "urn:tag:genre:qloo:heavy_metal"
    metal = "urn:tag:genre:qloo:metal"
    crowd = gm.Presence(
        "guests", 400, gm.MIN_GROUP_GUESTS, {heavy: 200}, {0: {heavy: 0.7}}, {heavy: "Heavy Metal"}
    )
    near = [
        act("m1", "Dio", (heavy, "Heavy Metal"), (metal, "Metal")),
        act("m2", "Halford", (heavy, "Heavy Metal"), (metal, "Metal")),
    ]
    assert gm.find_ghosts([GROUP], {0: near}, crowd) == []


def test_ghosts_are_ranked_and_capped_deterministically() -> None:
    many = [
        act(f"d{i}", f"Act {i}", (INDIE, "Indie"), (f"urn:tag:genre:qloo:g{g}", f"Genre {g}"))
        for g in range(6)
        for i in range(2 + (g % 3))  # genres carried by 2, 3 or 4 acts
    ]
    many = [
        act(f"{n.entity_id}-{k}", n.name, *n.genres, affinity=n.affinity)
        for k, n in enumerate(many)
    ]
    first = gm.find_ghosts([GROUP], {0: many}, presence())
    second = gm.find_ghosts([GROUP], {0: list(reversed(many))}, presence())
    assert len(first) == gm.GHOSTS_PER_GROUP
    assert [g.tag_id for g in first] == [g.tag_id for g in second]
    counts = [g.neighbours_with_tag for g in first]
    assert counts == sorted(counts, reverse=True)
    assert all(len(g.acts) <= gm.ACTS_PER_GHOST for g in first)


def test_the_section_says_when_qloo_gave_every_group_the_same_acts() -> None:
    groups = [GROUP, gm.GroupInfo(1, "Folk lovers", 0.5, 80.0)]
    shared = {0: NEAR, 1: NEAR}
    out = gm.ghost_section(groups, shared, presence(share={0: {INDIE: 0.7}, 1: {FOLK: 0.6}}), {})
    assert out["status"] == "not_group_specific"
    assert out["items"] == []
    assert out["act_similarity"] == 1.0
    assert "mostly the same neighbouring acts" in out["reason"]


def test_the_section_reports_groups_it_could_not_read_and_a_run_with_nothing() -> None:
    other = [act("e1", "Jade Tower", (FOLK, "Folk")), act("e2", "Kelp Road", (FOLK, "Folk"))]
    groups = [GROUP, gm.GroupInfo(1, "Folk lovers", 0.5, 80.0)]
    share = {0: {INDIE: 0.7}, 1: {FOLK: 0.6}}
    ok = gm.ghost_section(groups, {0: NEAR, 1: other}, presence(share=share), {})
    assert ok["status"] == "ok"
    assert ok["act_similarity"] == 0.0
    assert ok["items"][0]["tag"] == "Shoegaze"
    partial = gm.ghost_section(
        groups, {0: NEAR}, presence(share=share), {1: "Qloo did not answer for this group."}
    )
    assert partial["status"] == "ok"
    assert partial["skipped"] == [
        {"group_index": 1, "reason": "Qloo did not answer for this group."}
    ]
    assert partial["act_similarity"] is None  # one list has nothing to be compared with
    none = gm.ghost_section(groups, {}, presence(), {0: "x", 1: "y"})
    assert none["status"] == "none"
    assert none["items"] == []


# --------------------------------------------------------------------------------------------------- places
def places(prefix: str, n: int, base: int = 100) -> list[gm.Place]:
    return [gm.Place(f"{prefix}{i}", f"Place {prefix}{i}", base + 40 * i) for i in range(n)]


GROUPS = [GROUP, gm.GroupInfo(1, "Folk lovers", 0.5, 80.0)]


def test_a_list_that_did_not_change_with_the_crowds_taste_is_only_near_you() -> None:
    same = places("p", 10)
    section = gm.places_section(gm.PlaceLists(crowd=same, plain=same), GROUPS, label="x")
    assert section["mode"] == "near"
    assert section["seed_effect"] == 0.0
    assert section["told_apart"] is False
    assert section["by_group"] is None
    assert "did not change" in gm.nearby_note(section)
    assert len(section["items"]) == gm.SHOW_N


def test_a_list_that_changed_is_matched_to_the_crowd_but_not_to_a_group_unless_told_apart() -> None:
    crowd = places("c", 10)
    plain = places("p", 10)
    shared = places("s", 10)
    section = gm.places_section(
        gm.PlaceLists(crowd=crowd, plain=plain, by_group={0: shared, 1: shared}), GROUPS, label="x"
    )
    assert section["mode"] == "taste"
    assert section["seed_effect"] == 1.0
    assert section["similarity"] == 1.0
    assert section["told_apart"] is False
    assert section["by_group"] is None
    assert gm.gaps_from(section) == []
    assert "mostly the same places" in gm.nearby_note(section)


def test_overlap_close_to_chance_is_not_told_apart() -> None:
    plain = places("p", 10)
    a = places("s", 10)
    b = places("s", 7) + places("t", 3)  # 7 shared of 13 distinct: 0.54, the Mercury Lounge probe
    section = gm.places_section(
        gm.PlaceLists(crowd=a, plain=plain, by_group={0: a, 1: b}), GROUPS, label="x"
    )
    assert section["similarity"] == pytest.approx(7 / 13, abs=0.01)
    assert section["told_apart"] is False


def test_groups_that_got_different_places_are_listed_on_their_own_and_a_group_without_its_own_is_a_gap() -> (
    None
):
    plain = places("p", 10)
    crowd = places("c", 10)
    one = places("a", 10)
    two = places("b", 10)
    section = gm.places_section(
        gm.PlaceLists(crowd=crowd, plain=plain, by_group={0: one, 1: two}), GROUPS, label="x"
    )
    assert section["told_apart"] is True
    assert section["similarity"] == 0.0
    assert [g["group"] for g in section["by_group"]] == ["Indie lovers", "Folk lovers"]
    assert all(g["own"] for g in section["by_group"])
    assert gm.gaps_from(section) == []
    assert "each group is listed on its own" in gm.nearby_note(section)


def test_a_group_whose_top_places_are_all_found_in_other_groups_lists_has_no_place_of_its_own() -> (
    None
):
    three = [*GROUPS, gm.GroupInfo(2, "Loud lovers", 0.3, 50.0)]
    plain = places("p", 10)
    crowd = places("c", 10)
    # group 0: ten places of its own; group 1: ten places of its own; group 2: five from group 0's list and five from group 1's
    g0 = places("a", 10)
    g1 = places("b", 10)
    g2 = places("a", 5) + places("b", 5)
    section = gm.places_section(
        gm.PlaceLists(crowd=crowd, plain=plain, by_group={0: g0, 1: g1, 2: g2}), three, label="x"
    )
    # mean pairwise overlap is (0 + 5/15 + 5/15) / 3 = 0.22, under the limit
    assert section["told_apart"] is True
    assert gm.gaps_from(section) == [{"group_index": 2, "group": "Loud lovers"}]
    gap = next(g for g in section["by_group"] if g["group_index"] == 2)
    assert gap["own"] is False
    assert len(gap["items"]) == gm.SHOW_N  # shown, with the sentence that none is its own


def test_lists_too_short_to_compare_are_never_told_apart() -> None:
    plain = places("p", 10)
    crowd = places("c", 10)
    section = gm.places_section(
        gm.PlaceLists(crowd=crowd, plain=plain, by_group={0: places("a", 4), 1: places("b", 4)}),
        GROUPS,
        label="x",
    )
    assert section["told_apart"] is False
    assert section["similarity"] is None


def test_no_plain_list_means_no_claim_of_a_match() -> None:
    section = gm.places_section(gm.PlaceLists(crowd=places("c", 8), plain=[]), GROUPS, label="x")
    assert section["mode"] == "near"
    assert section["seed_effect"] is None
    assert "no plain list" in gm.nearby_note(section)


def test_an_empty_answer_is_stated_as_empty() -> None:
    section = gm.places_section(gm.PlaceLists(crowd=[], plain=[]), GROUPS, label="x")
    assert section["status"] == "empty"
    assert section["items"] == []
    assert "no open places" in gm.nearby_note(section)
    assert "no open places" in gm.elsewhere_note(section)


def test_lookalikes_leave_out_everything_inside_the_venues_own_radius() -> None:
    wide = [
        gm.Place("in", "Inside", 300),
        gm.Place("out1", "Outside one", 2500),
        gm.Place("out2", "Outside two", 3100),
        gm.Place("unknown", "No distance", None),
    ]
    section = gm.places_section(
        gm.PlaceLists(crowd=wide, plain=places("p", 4, base=3000)),
        GROUPS,
        label="x",
        outside_only_m=800,
    )
    assert [p["entity_id"] for p in section["items"]] == ["out1", "out2", "unknown"]
    assert section["crowd_size"] == 3
    assert section["mode"] == "taste"
    assert "ties to your crowd's taste" in gm.elsewhere_note(section)
    near = gm.places_section(
        gm.PlaceLists(crowd=wide, plain=wide), GROUPS, label="x", outside_only_m=800
    )
    assert "not lookalikes" in gm.elsewhere_note(near)
