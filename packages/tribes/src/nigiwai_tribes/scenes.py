"""Scene groups for a venue with no guests yet: the acts that play there, grouped by what Qloo's tags say about them.

A lineup has no respondents, so the guest model does not apply. Each resolved act becomes one row of tag features
(the same matrix, weighting and normalisation as the guest groups), rows are weighted by how many nights the act has
played, and a soft factor model finds at most three scenes. A scene needs at least three acts; when the data cannot
support that many the count drops, down to one scene that is simply the room's sound. Nothing here is a stability
claim: the result is always labelled provisional.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field, replace

import numpy as np

from .build import build_matrix, l2_rows, usable_tags
from .config import TribesConfig
from .model import fit_nmf
from .types import Pick, Respondent, Tag

LETTERS = "ABC"


@dataclass(frozen=True)
class SceneAct:
    entity_id: str
    name: str
    events: int  # nights the act has played at the venue
    tags: tuple[Tag, ...] = ()


@dataclass
class SceneGroup:
    index: int
    label: str
    share: float  # this scene's share of all nights played by the acts that were grouped
    size: int  # acts
    seed_ids: list[str] = field(
        default_factory=list
    )  # most-booked acts first, a few spare for eligibility checks
    seed_names: list[str] = field(default_factory=list)
    top_tags: list[str] = field(
        default_factory=list
    )  # genre tags that mark this scene out from the rest


def _genre(tag_type: str) -> bool:
    return "genre" in tag_type.split(":")


def _label(top_tags: list[str], index: int) -> str:
    if not top_tags:
        return f"Group {LETTERS[index]}"
    named = [t[:1].upper() + t[1:] for t in top_tags[:2]]
    return " and ".join(named) + " acts"


def scene_groups(
    acts: list[SceneAct],
    cfg: TribesConfig | None = None,
    *,
    max_groups: int = 3,
    min_acts: int = 3,
    seeds: int = 8,
) -> list[SceneGroup]:
    """Group acts into at most `max_groups` scenes. Deterministic for a given input."""
    cfg = replace(cfg or TribesConfig(), min_usable_picks=1, min_df=2)
    ordered = sorted(acts, key=lambda a: (-a.events, a.entity_id))
    respondents = [
        Respondent(a.entity_id, (Pick(a.entity_id, "urn:entity:artist", a.name, a.tags),))
        for a in ordered
    ]
    matrix = build_matrix(respondents, cfg)
    by_id = {a.entity_id: a for a in ordered}
    kept = [by_id[r] for r in matrix.respondent_ids]
    if len(kept) < min_acts:
        return []
    idf = np.array([t.idf for t in matrix.vocab])
    features = l2_rows(matrix.X * idf)
    weights = np.sqrt(np.array([max(a.events, 1) for a in kept], dtype=float))

    k = min(max_groups, len(kept) // (2 * min_acts)) if len(kept) >= 2 * min_acts else 1
    k = max(k, 1)
    labels = np.zeros(len(kept), dtype=int)
    while k > 1:
        model = fit_nmf(features * weights[:, None], k)
        labels = np.asarray(model.transform(features * weights[:, None]).argmax(axis=1))
        sizes = np.bincount(labels, minlength=k)
        if sizes.min() >= min_acts:
            break
        k -= 1
    if k == 1:
        labels = np.zeros(len(kept), dtype=int)

    total_events = float(sum(max(a.events, 1) for a in kept))
    tag_counts_all: Counter[str] = Counter()
    tag_names: dict[str, tuple[str, str]] = {}
    per_act_tags: list[dict[str, tuple[str, str]]] = []
    for a in kept:
        tags = usable_tags(Pick(a.entity_id, "urn:entity:artist", a.name, a.tags), cfg)
        per_act_tags.append(tags)
        for tid, nm in tags.items():
            tag_counts_all[tid] += 1
            tag_names.setdefault(tid, nm)

    groups: list[SceneGroup] = []
    for g in range(k):
        members = [i for i in range(len(kept)) if labels[i] == g]
        if not members:
            continue
        member_events = sum(max(kept[i].events, 1) for i in members)
        counts: Counter[str] = Counter()
        for i in members:
            counts.update(per_act_tags[i].keys())
        lifts: list[tuple[float, str]] = []
        for tid, c in counts.items():
            if c < 2 or not _genre(tag_names[tid][1]):
                continue
            lift = (c / len(members)) / (tag_counts_all[tid] / len(kept))
            lifts.append((lift * np.log1p(c), tid))
        lifts.sort(key=lambda x: (-x[0], x[1]))
        top = [tag_names[tid][0] for _, tid in lifts[:3]]
        lead = sorted(members, key=lambda i: (-kept[i].events, kept[i].entity_id))[:seeds]
        groups.append(
            SceneGroup(
                index=0,
                label="",
                share=member_events / total_events,
                size=len(members),
                seed_ids=[kept[i].entity_id for i in lead],
                seed_names=[kept[i].name for i in lead],
                top_tags=top,
            )
        )
    groups.sort(key=lambda s: (-s.share, s.seed_ids[0]))
    seen: set[str] = set()
    for i, s in enumerate(groups):
        s.index = i
        label = _label(s.top_tags, i)
        s.label = label if label not in seen else f"{label} ({LETTERS[i]})"
        seen.add(s.label)
    return groups
