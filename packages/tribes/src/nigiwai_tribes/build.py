"""Picks to matrix. Weighting and preprocessing follow proof D and proof G: each usable pick adds mass 1 spread
evenly over its tags, tags are weighted by inverse document frequency over the distinct picked items, and each
respondent's row is length-normalised."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from .config import TribesConfig
from .places import is_place, keeps_for_taste
from .types import Matrix, Pick, Respondent, TagRef


def l2_rows(m: NDArray[np.float64]) -> NDArray[np.float64]:
    norm = np.linalg.norm(m, axis=-1, keepdims=True)
    return np.divide(m, norm, out=np.zeros_like(m), where=norm > 0)


def keep_tag(tag_id: str, tag_type: str, cfg: TribesConfig) -> bool:
    """Drop tags from namespaces that are about a place's facilities, never taste (rule G27)."""
    parts = set(tag_id.split(":")) | set(tag_type.split(":"))
    return not any(ns in parts for ns in cfg.dropped_namespaces)


def usable_tags(pick: Pick, cfg: TribesConfig) -> dict[str, tuple[str, str]]:
    """The tags of a pick that may count as taste. A place is read through an allowlist (see `places`): its tags also carry facilities
    and descriptions of other people, and some of those would read as a claim about a person's religion, health or orientation."""
    place = is_place(pick.type)
    out: dict[str, tuple[str, str]] = {}
    for tag in pick.tags:
        if not tag.tag_id or tag.tag_id in out:
            continue
        kept = (
            keeps_for_taste(tag.tag_id, tag.name) if place else keep_tag(tag.tag_id, tag.type, cfg)
        )
        if kept:
            out[tag.tag_id] = (tag.name, tag.type)
    return out


def idf_from_df(df: NDArray[np.float64], n_items: int) -> NDArray[np.float64]:
    return np.log((1.0 + n_items) / (1.0 + df)) + 1.0


def build_matrix(respondents: list[Respondent], cfg: TribesConfig) -> Matrix:
    """Keep respondents with enough usable picks; build the matrix from what they picked."""
    dropped: dict[str, int] = {"respondents_too_few_picks": 0, "picks_without_tags": 0}
    kept: list[Respondent] = []
    for r in respondents:
        good = [p for p in r.picks if len(usable_tags(p, cfg)) >= cfg.min_tags_per_pick]
        dropped["picks_without_tags"] += len(r.picks) - len(good)
        if len(good) >= cfg.min_usable_picks:
            kept.append(r)
        else:
            dropped["respondents_too_few_picks"] += 1

    # Distinct items, in a fixed order, with the tags we keep for each.
    entity_ids: list[str] = []
    entity_pos: dict[str, int] = {}
    entity_tags: list[dict[str, tuple[str, str]]] = []
    entity_names: list[str] = []
    entity_types: list[str] = []
    for r in kept:
        for p in r.picks:
            tags = usable_tags(p, cfg)
            if len(tags) < cfg.min_tags_per_pick or p.entity_id in entity_pos:
                continue
            entity_pos[p.entity_id] = len(entity_ids)
            entity_ids.append(p.entity_id)
            entity_tags.append(tags)
            entity_names.append(p.name)
            entity_types.append(p.type)

    # Vocabulary: tags carried by at least min_df distinct items, in a stable order.
    df_counts: dict[str, int] = {}
    meta: dict[str, tuple[str, str]] = {}
    for tags in entity_tags:
        for tag_id, nm in tags.items():
            df_counts[tag_id] = df_counts.get(tag_id, 0) + 1
            meta.setdefault(tag_id, nm)
    vocab_ids = sorted(t for t, c in df_counts.items() if c >= cfg.min_df)
    vix = {t: i for i, t in enumerate(vocab_ids)}
    n_items = len(entity_ids)
    df = np.array([df_counts[t] for t in vocab_ids], dtype=float)
    idf = idf_from_df(df, n_items) if len(vocab_ids) else np.zeros(0)

    rows = np.zeros((n_items, len(vocab_ids)))
    for i, tags in enumerate(entity_tags):
        for tag_id in tags:
            j = vix.get(tag_id)
            if j is not None:
                rows[i, j] = 1.0

    X = np.zeros((len(kept), len(vocab_ids)))
    pick_index: list[list[int]] = []
    for ri, r in enumerate(kept):
        picked: list[int] = []
        for p in r.picks:
            found = entity_pos.get(p.entity_id)
            if found is None or found in picked:
                continue
            i = found
            picked.append(i)
            s = rows[i].sum()
            if s > 0:  # a pick whose tags all fell below min_df adds nothing
                X[ri] += rows[i] / s
        pick_index.append(picked)

    # A respondent whose usable picks all fell outside the vocabulary has an empty row: drop them too.
    nonempty = X.sum(axis=1) > 0
    if not nonempty.all():
        dropped["respondents_too_few_picks"] += int((~nonempty).sum())
        kept = [r for r, ok in zip(kept, nonempty, strict=True) if ok]
        pick_index = [p for p, ok in zip(pick_index, nonempty, strict=True) if ok]
        X = X[nonempty]

    counts = np.zeros(n_items)
    for picked in pick_index:
        for i in picked:
            counts[i] += 1

    vocab = [
        TagRef(tag_id=t, name=meta[t][0], type=meta[t][1], df=int(df_counts[t]), idf=float(idf[j]))
        for j, t in enumerate(vocab_ids)
    ]
    return Matrix(
        respondent_ids=[r.id for r in kept],
        X=X,
        features=l2_rows(X * idf) if len(vocab_ids) else X,
        vocab=vocab,
        entity_rows=rows,
        entity_ids=entity_ids,
        entity_names=entity_names,
        entity_types=entity_types,
        entity_counts=counts,
        pick_index=pick_index,
        dropped=dropped,
    )
