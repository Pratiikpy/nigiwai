"""Soft NMF over the respondent-by-tag features, and projection of a new guest onto it."""

from __future__ import annotations

import warnings

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import nnls
from sklearn.decomposition import NMF

from .build import l2_rows


def fit_nmf(features: NDArray[np.float64], k: int, max_iter: int = 500) -> NMF:
    """The configuration proof D measured: nndsvda initialisation (deterministic), random_state 0."""
    with warnings.catch_warnings():
        warnings.simplefilter(
            "ignore"
        )  # sklearn warns when it hits max_iter on tiny or degenerate inputs
        return NMF(n_components=k, init="nndsvda", max_iter=max_iter, random_state=0).fit(features)


def memberships(model: NMF, features: NDArray[np.float64]) -> NDArray[np.float64]:
    """Row-normalised W: each person is a mixture of tribes that sums to 1 (uniform when the row is empty)."""
    w = model.transform(features)
    s = w.sum(axis=1, keepdims=True)
    k = w.shape[1]
    return np.asarray(
        np.divide(w, s, out=np.full_like(w, 1.0 / k), where=s > 1e-12), dtype=np.float64
    )


def assign(model: NMF, features: NDArray[np.float64]) -> NDArray[np.int64]:
    return np.asarray(model.transform(features).argmax(axis=1), dtype=np.int64)


def project(
    h: NDArray[np.float64], idf: NDArray[np.float64], tag_rows: list[NDArray[np.float64]]
) -> NDArray[np.float64] | None:
    """Memberships (summing to 1) of one guest, given the binary tag rows of their picks, by non-negative least
    squares against the fitted tribe profiles `h`. None when none of their tags is in the vocabulary."""
    if not tag_rows:
        return None
    x = np.zeros(h.shape[1])
    for row in tag_rows:
        s = row.sum()
        if s > 0:
            x += row / s
    if x.sum() <= 0:
        return None
    f = l2_rows((x * idf)[None, :])[0]
    w, _ = nnls(h.T, f)
    total = w.sum()
    if total <= 1e-12:
        return None
    return np.asarray(w / total, dtype=np.float64)
