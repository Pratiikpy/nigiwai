"""Invented crowds with known structure. Nothing here is real data or Qloo output."""

from __future__ import annotations

import numpy as np
from nigiwai_tribes import Pick, Respondent, Tag, TribesConfig

TYPES = ("urn:entity:artist", "urn:entity:brand", "urn:entity:movie")


def catalogue(
    n_tribes: int = 3, per_tribe: int = 24, seed: int = 1, tag_pool: int = 14
) -> tuple[list[list[Pick]], list[Tag]]:
    """Per-tribe items, each carrying tags mostly from its tribe's own pool plus one generic and one noise tag."""
    rng = np.random.default_rng(seed)
    generic = [
        Tag(f"urn:tag:genre:qloo:generic{i}", f"Generic {i}", "urn:tag:genre:qloo")
        for i in range(3)
    ]
    noise = [
        Tag(f"urn:tag:style:qloo:noise{i}", f"Noise {i}", "urn:tag:style:qloo") for i in range(30)
    ]
    items: list[list[Pick]] = []
    for t in range(n_tribes):
        pool = [
            Tag(f"urn:tag:genre:qloo:t{t}_{j}", f"Flavour {t}-{j}", "urn:tag:genre:qloo")
            for j in range(tag_pool)
        ]
        group: list[Pick] = []
        for e in range(per_tribe):
            own = rng.choice(len(pool), size=4, replace=False)
            tags = [pool[int(i)] for i in own]
            tags.append(generic[int(rng.integers(len(generic)))])
            tags.append(noise[int(rng.integers(len(noise)))])
            group.append(Pick(f"e-{t}-{e}", TYPES[e % len(TYPES)], f"Item {t}-{e}", tuple(tags)))
        items.append(group)
    return items, generic + noise


def strict_config(**over: object) -> TribesConfig:
    """The shipped decision rule (19 null draws per null, p <= 0.05) with fewer bootstraps."""
    base = {"bootstrap": 20, "lift_bootstrap": 60}
    base.update(over)
    return TribesConfig(**base)  # type: ignore[arg-type]


def crowd(
    n: int,
    items: list[list[Pick]],
    *,
    structure: float = 0.85,
    picks: int = 5,
    seed: int = 2,
    weights: tuple[float, ...] | None = None,
) -> tuple[list[Respondent], list[int]]:
    """n guests; each belongs to one tribe and takes `structure` of their picks from its items, the rest from anywhere.
    structure = 0 gives a crowd with no taste structure at all (every pick is drawn from the whole catalogue)."""
    rng = np.random.default_rng(seed)
    k = len(items)
    flat = [p for g in items for p in g]
    labels: list[int] = []
    out: list[Respondent] = []
    probs = np.array(weights if weights else [1.0] * k)
    probs = probs / probs.sum()
    for i in range(n):
        t = int(rng.choice(k, p=probs))
        labels.append(t)
        chosen: dict[str, Pick] = {}
        while len(chosen) < picks:
            if rng.random() < structure:
                p = items[t][int(rng.integers(len(items[t])))]
            else:
                p = flat[int(rng.integers(len(flat)))]
            chosen[p.entity_id] = p
        out.append(
            Respondent(
                f"r{i}",
                tuple(chosen.values()),
                weekday=int(rng.integers(7)),
                hour=int(rng.integers(24)),
            )
        )
    return out, labels


def fast_config(**over: object) -> TribesConfig:
    """Cheap settings for tests that are not about the null test itself: two null draws, so alpha must allow p = 1/3."""
    base = {"bootstrap": 20, "null_runs": 2, "alpha": 0.34, "lift_bootstrap": 60}
    base.update(over)
    return TribesConfig(**base)  # type: ignore[arg-type]
