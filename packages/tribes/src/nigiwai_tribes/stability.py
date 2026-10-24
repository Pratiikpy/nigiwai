"""Bootstrap stability, the same measure proof D and G used, and the two null models it is judged against.

Stability is the mean pairwise adjusted Rand index between the labels that B bootstrap refits give the same
respondents. It rises with sample size even on noise, so it is reported next to two nulls drawn in the same run:
the feature columns permuted (structure destroyed), and respondents made of random popular picks (popularity only).
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import linear_sum_assignment

from .build import l2_rows
from .config import TribesConfig
from .model import assign, fit_nmf
from .types import Matrix, StabilityReport


def ari(a: NDArray[np.int64], b: NDArray[np.int64]) -> float:
    """Adjusted Rand index from the contingency table."""
    n = len(a)
    ka, kb = int(a.max()) + 1, int(b.max()) + 1
    c = np.bincount(a * kb + b, minlength=ka * kb).reshape(ka, kb).astype(np.int64)

    def comb(x: NDArray[np.int64]) -> NDArray[np.int64]:
        return x * (x - 1) // 2

    sij = int(comb(c).sum())
    sa = int(comb(c.sum(1)).sum())
    sb = int(comb(c.sum(0)).sum())
    total = n * (n - 1) // 2
    if total == 0:
        return 1.0
    expected = sa * sb / total
    maximum = 0.5 * (sa + sb)
    if maximum == expected:
        return 1.0
    return (sij - expected) / (maximum - expected)


def top_tags(h: NDArray[np.float64], n: int) -> list[set[int]]:
    return [set(np.argsort(-row, kind="stable")[:n].tolist()) for row in h]


def jaccard_matrix(a: list[set[int]], b: list[set[int]]) -> NDArray[np.float64]:
    m = np.zeros((len(a), len(b)))
    for i, x in enumerate(a):
        for j, y in enumerate(b):
            u = len(x | y)
            m[i, j] = len(x & y) / u if u else 0.0
    return m


def bootstrap_stability(
    features: NDArray[np.float64], k: int, cfg: TribesConfig, rng: np.random.Generator
) -> tuple[float, float, list[float], list[int]]:
    """(stability, mean ARI with the reference fit, per-tribe top-tag overlap, reference tribe sizes)."""
    n = features.shape[0]
    ref = fit_nmf(features, k, cfg.nmf_max_iter)
    ref_labels = assign(ref, features)
    ref_top = top_tags(ref.components_, cfg.top_tags)
    labels = np.zeros((cfg.bootstrap, n), dtype=np.int64)
    ref_ari = np.zeros(cfg.bootstrap)
    overlap = np.zeros((cfg.bootstrap, k))
    for b in range(cfg.bootstrap):
        idx = rng.integers(0, n, size=n)
        model = fit_nmf(features[idx], k, cfg.nmf_max_iter)
        lab = assign(model, features)
        labels[b] = lab
        ref_ari[b] = ari(ref_labels, lab)
        jac = jaccard_matrix(ref_top, top_tags(model.components_, cfg.top_tags))
        rows, cols = linear_sum_assignment(-jac)
        for r, c in zip(rows, cols, strict=True):
            overlap[b, r] = jac[r, c]
    pairs = [
        ari(labels[i], labels[j]) for i in range(cfg.bootstrap) for j in range(i + 1, cfg.bootstrap)
    ]
    sizes = np.bincount(ref_labels, minlength=k).tolist()
    return float(np.mean(pairs)), float(ref_ari.mean()), overlap.mean(axis=0).tolist(), sizes


def permuted_features(
    features: NDArray[np.float64], rng: np.random.Generator
) -> NDArray[np.float64]:
    """Null A: shuffle every tag column independently, which keeps each tag's frequency and destroys co-occurrence."""
    out = features.copy()
    for j in range(out.shape[1]):
        out[:, j] = rng.permutation(out[:, j])
    return l2_rows(out)


def random_pick_features(matrix: Matrix, rng: np.random.Generator) -> NDArray[np.float64]:
    """Null B: respondents who pick as many items as the real ones, but at random, each item drawn in proportion to
    how many real respondents picked it. Popularity survives; taste does not."""
    n_items = matrix.entity_rows.shape[0]
    p = np.maximum(matrix.entity_counts, 1.0)
    p = p / p.sum()
    sizes = np.array([len(x) for x in matrix.pick_index])
    x = np.zeros_like(matrix.X)
    rows = matrix.entity_rows
    for r in range(x.shape[0]):
        m = int(min(rng.choice(sizes), n_items))
        items = rng.choice(n_items, size=m, replace=False, p=p)
        for i in items:
            s = rows[i].sum()
            if s > 0:
                x[r] += rows[i] / s
    idf = np.array([t.idf for t in matrix.vocab])
    return l2_rows(x * idf)


def measure(matrix: Matrix, k: int, cfg: TribesConfig) -> StabilityReport:
    """Stability of the real crowd and of both nulls, from one seeded generator so a run is reproducible."""
    rng = np.random.default_rng(np.random.SeedSequence([cfg.seed, matrix.features.shape[0], k]))
    raw, ref_ari, overlap, sizes = bootstrap_stability(matrix.features, k, cfg, rng)
    nulls_a = []
    nulls_b = []
    for _ in range(cfg.null_runs):
        nulls_a.append(bootstrap_stability(permuted_features(matrix.features, rng), k, cfg, rng)[0])
        nulls_b.append(bootstrap_stability(random_pick_features(matrix, rng), k, cfg, rng)[0])
    na, nb = float(np.mean(nulls_a)), float(np.mean(nulls_b))
    # A permutation test: if the real crowd were just another draw from a null, it would be at least as stable as
    # all m null draws with probability 1 / (m + 1). Passing needs p <= 0.05, which with m = 19 means beating every one.
    pa = (1 + sum(x >= raw for x in nulls_a)) / (1 + len(nulls_a))
    pb = (1 + sum(x >= raw for x in nulls_b)) / (1 + len(nulls_b))
    return StabilityReport(
        raw=raw,
        null_permuted=na,
        null_random_picks=nb,
        corrected=raw - max(na, nb),
        p_permuted=pa,
        p_random_picks=pb,
        null_runs=cfg.null_runs,
        ref_ari=ref_ari,
        tag_overlap=overlap,
        ref_sizes=sizes,
        bootstrap=cfg.bootstrap,
        beats_both_nulls=pa <= cfg.alpha and pb <= cfg.alpha,
    )
