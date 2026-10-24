"""Category-pair signatures: which kinds of pick a tribe combines more often than the crowd does.

Proof D found that pairs between categories can be read from 30 respondents but mostly mirror a crowd's dominant
category, and that genuinely odd pairs need a group of 200 or more. So every pair is tested with a false-discovery
correction, and only a tribe of at least `odd_pair_min_tribe` soft members may call a pair "odd"; smaller groups get
the same pair labelled descriptive.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from math import erfc, sqrt

import numpy as np
from numpy.typing import NDArray

from .config import TribesConfig
from .types import Matrix


@dataclass
class PairSignature:
    types: tuple[str, str]
    tribe_share: float  # share of the tribe (membership-weighted) that picked both kinds
    crowd_share: float
    lift: float
    q: float  # false-discovery-adjusted p-value
    group_size: float  # effective soft size of the tribe the share describes
    odd: bool  # only for a tribe large enough to support the claim


def _bh(p: list[float]) -> list[float]:
    """Benjamini-Hochberg adjusted p-values."""
    n = len(p)
    order = sorted(range(n), key=lambda i: p[i])
    adj = [0.0] * n
    running = 1.0
    for rank in range(n, 0, -1):
        i = order[rank - 1]
        running = min(running, p[i] * n / rank)
        adj[i] = running
    return adj


def category_pairs(
    matrix: Matrix, m: NDArray[np.float64], cfg: TribesConfig
) -> list[list[PairSignature]]:
    n, k = m.shape
    kinds = sorted(set(matrix.entity_types))
    has = {kind: np.zeros(n, dtype=bool) for kind in kinds}
    for r, picked in enumerate(matrix.pick_index):
        for i in picked:
            has[matrix.entity_types[i]][r] = True
    tests: list[tuple[int, tuple[str, str], float, float, float, float]] = []
    for a, b in combinations(kinds, 2):
        both = (has[a] & has[b]).astype(float)
        base = float(both.mean())
        if base <= 0 or base >= 1:
            continue
        for t in range(k):
            w = m[:, t]
            size = float(w.sum())
            if size <= 0:
                continue
            eff = size**2 / float((w**2).sum())
            share = float((w * both).sum() / size)
            z = (share - base) / sqrt(base * (1 - base) / max(eff, 1.0))
            p = erfc(abs(z) / sqrt(2))
            tests.append((t, (a, b), share, base, p, size))
    q = _bh([x[4] for x in tests])
    out: list[list[PairSignature]] = [[] for _ in range(k)]
    for (t, pair, share, base, _p, size), qv in zip(tests, q, strict=True):
        if qv < 0.05 and share > base:
            out[t].append(
                PairSignature(
                    pair, share, base, share / base, qv, size, odd=size >= cfg.odd_pair_min_tribe
                )
            )
    for lst in out:
        lst.sort(key=lambda s: -s.lift)
    return out
