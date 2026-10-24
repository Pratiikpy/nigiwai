"""What each tribe loves, and what to call it.

A tribe is not named from its centroid: in proof D 98.5% of centroids read "rock, alternative, electronic". It is named
from the tags it over-indexes on (lift against the venue's whole crowd, with an interval) and from its most-picked items.
The name is built only from those lists, and `used_tags` records exactly which tags it came from.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from .config import TribesConfig
from .types import Matrix


@dataclass
class TagLift:
    tag_id: str
    name: str
    type: str  # Qloo tag type, e.g. urn:tag:genre:qloo
    lift: float
    lo: float  # 5th percentile over respondent bootstraps
    hi: float  # 95th percentile
    support: int  # distinct picked items carrying the tag, among this tribe's members


@dataclass
class TopItem:
    entity_id: str
    name: str
    type: str
    weight: float  # membership-weighted number of respondents who picked it


@dataclass
class TribeName:
    name: str
    line: str
    used_tags: list[str]


def _lift(mass: NDArray[np.float64], base: NDArray[np.float64]) -> NDArray[np.float64]:
    share = mass / max(mass.sum(), 1e-12)
    return np.divide(share, base, out=np.zeros_like(share), where=base > 0)


def tribe_items(matrix: Matrix, m: NDArray[np.float64], t: int, limit: int = 8) -> list[TopItem]:
    weight = np.zeros(len(matrix.entity_ids))
    for r, picked in enumerate(matrix.pick_index):
        for i in picked:
            weight[i] += m[r, t]
    order = np.argsort(-weight, kind="stable")
    return [
        TopItem(
            matrix.entity_ids[i], matrix.entity_names[i], matrix.entity_types[i], float(weight[i])
        )
        for i in order[:limit]
        if weight[i] > 0
    ]


def tribe_tag_lifts(
    matrix: Matrix,
    m: NDArray[np.float64],
    t: int,
    cfg: TribesConfig,
    rng: np.random.Generator,
    limit: int = 8,
) -> list[TagLift]:
    """Tags this tribe over-indexes on, ranked by the lower end of their lift interval so a lucky tag does not lead."""
    x = matrix.X
    n = x.shape[0]
    crowd = x.sum(axis=0)
    base = crowd / max(crowd.sum(), 1e-12)
    mass = (m[:, t][:, None] * x).sum(axis=0)
    lift = _lift(mass, base)

    # Support: distinct items carrying the tag that members picked (a member counts for the weight of their membership).
    weight = np.zeros(len(matrix.entity_ids))
    for r, picked in enumerate(matrix.pick_index):
        for i in picked:
            weight[i] += m[r, t]
    support = ((matrix.entity_rows * (weight >= 0.5)[:, None]) > 0).sum(axis=0)

    candidates = np.where((support >= cfg.lift_min_support) & (lift > 0))[0]
    if len(candidates) == 0:
        return []
    boots = np.zeros((cfg.lift_bootstrap, len(candidates)))
    for b in range(cfg.lift_bootstrap):
        idx = rng.integers(0, n, size=n)
        xb = x[idx]
        mb = m[idx, t][:, None]
        crowd_b = xb.sum(axis=0)
        base_b = crowd_b / max(crowd_b.sum(), 1e-12)
        boots[b] = _lift((mb * xb).sum(axis=0), base_b)[candidates]
    lo = np.percentile(boots, 5, axis=0)
    hi = np.percentile(boots, 95, axis=0)
    order = np.argsort(-lo, kind="stable")
    out: list[TagLift] = []
    for pos in order:
        j = int(candidates[pos])
        ref = matrix.vocab[j]
        out.append(
            TagLift(
                ref.tag_id,
                ref.name,
                ref.type,
                float(lift[j]),
                float(lo[pos]),
                float(hi[pos]),
                int(support[j]),
            )
        )
        if len(out) >= limit:
            break
    return out


def _pretty(tag_name: str) -> str:
    return " ".join(tag_name.replace("_", " ").split()).strip()


def name_tribe(lifts: list[TagLift], items: list[TopItem], index: int) -> TribeName:
    """A name from the top over-indexing tags (those whose lift interval clears 1) and a line from the top items."""
    strong = [t for t in lifts if t.lo > 1.0]
    # A genre says what a crowd listens to; a feeling tag ("Passionate", "Loyal") fits everyone. Name from genres first.
    strong = sorted(strong, key=lambda t: 0 if "genre" in t.type else 1)
    chosen: list[TagLift] = []
    seen: set[str] = set()
    for t in strong:
        key = _pretty(t.name).casefold()
        if key and key not in seen:
            seen.add(key)
            chosen.append(t)
        if len(chosen) == 2:
            break
    letter = "ABCDEFGH"[index % 8]
    if chosen:
        names = [_pretty(t.name) for t in chosen]
        name = " and ".join(names) if len(names) == 2 else names[0]
        name = name[0].upper() + name[1:] + " crowd"
    else:
        name = f"Group {letter}"
    top = ", ".join(i.name for i in items[:3])
    line = f"Most picked: {top}." if top else ""
    return TribeName(name=name, line=line, used_tags=[t.tag_id for t in chosen])
