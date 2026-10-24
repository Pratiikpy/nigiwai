"""Scene groups from a lineup: acts grouped by their tags, weighted by nights played. All data here is invented."""

from __future__ import annotations

import numpy as np
from nigiwai_tribes import Tag
from nigiwai_tribes.scenes import SceneAct, scene_groups

GENRES = {
    0: ["indie rock", "post-punk", "shoegaze", "garage rock", "lo-fi"],
    1: ["jazz", "bebop", "swing", "big band", "cool jazz"],
    2: ["techno", "house", "ambient", "minimal", "electro"],
}


def acts(per_scene: int = 8, seed: int = 3) -> list[SceneAct]:
    rng = np.random.default_rng(seed)
    out: list[SceneAct] = []
    for s, names in GENRES.items():
        for i in range(per_scene):
            own = rng.choice(len(names), size=3, replace=False)
            tags = tuple(
                Tag(f"urn:tag:genre:qloo:{names[int(j)]}", names[int(j)], "urn:tag:genre:qloo")
                for j in own
            )
            tags += (
                Tag("urn:tag:audience:qloo:loyal", "Loyal", "urn:tag:audience:qloo"),
                Tag(f"urn:tag:style:qloo:n{int(rng.integers(5))}", "Style", "urn:tag:style:qloo"),
            )
            out.append(
                SceneAct(
                    f"e{s}-{i}",
                    f"Act {s}-{i}",
                    int(rng.integers(1, 12)) + (8 if s == 0 else 0),
                    tags,
                )
            )
    return out


def test_three_planted_scenes_are_recovered_and_named_from_their_genre_tags() -> None:
    result = scene_groups(acts())
    assert len(result) == 3
    for g in result:
        planted = {i.removeprefix("e").split("-")[0] for i in g.seed_ids}
        assert len(planted) == 1, f"a scene mixed acts from planted scenes {planted}"
        assert g.size == 8 and g.seed_ids and g.seed_names
    assert abs(sum(g.share for g in result) - 1.0) < 1e-9
    assert result[0].share >= result[1].share >= result[2].share  # biggest first
    assert len({g.label for g in result}) == 3
    joined = " ".join(g.label.lower() for g in result)
    assert "indie rock" in joined or "post-punk" in joined or "garage rock" in joined


def test_the_biggest_scene_is_the_one_with_the_most_nights() -> None:
    result = scene_groups(acts())
    assert result[0].seed_ids[0].startswith("e0-")  # planted scene 0 has 8 extra nights per act


def test_the_result_is_deterministic() -> None:
    a = [(g.label, g.seed_ids, round(g.share, 6)) for g in scene_groups(acts())]
    b = [(g.label, g.seed_ids, round(g.share, 6)) for g in scene_groups(acts())]
    assert a == b


def test_too_few_acts_for_three_scenes_gives_fewer_and_never_a_scene_under_three_acts() -> None:
    result = scene_groups(acts(per_scene=3)[:8])
    assert 1 <= len(result) <= 2
    assert all(g.size >= 3 for g in result)


def test_a_handful_of_acts_is_one_scene_and_two_acts_is_none() -> None:
    few = acts(per_scene=2)[:5]
    assert len(scene_groups(few)) == 1
    assert scene_groups(acts(per_scene=1)[:2]) == []


def test_acts_without_usable_tags_are_left_out() -> None:
    bare = [SceneAct(f"b{i}", f"Bare {i}", 3, ()) for i in range(10)]
    assert scene_groups(bare) == []


def test_seeds_are_the_most_booked_acts_first() -> None:
    result = scene_groups(acts())
    for g in result:
        events = {a.entity_id: a.events for a in acts()}
        booked = [events[i] for i in g.seed_ids]
        assert booked == sorted(booked, reverse=True)
