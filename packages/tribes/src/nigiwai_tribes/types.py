"""Plain data types shared by the tribes modules. Everything here is JSON-friendly."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from numpy.typing import NDArray

Unlock = Literal["none", "unstable", "provisional", "named"]


@dataclass(frozen=True)
class Tag:
    tag_id: str
    name: str
    type: str = ""


@dataclass(frozen=True)
class Pick:
    """One thing a guest picked, with the Qloo tags stored for it."""

    entity_id: str
    type: str
    name: str
    tags: tuple[Tag, ...] = ()


@dataclass(frozen=True)
class Respondent:
    """A guest's answer. `weekday` is 0 (Monday) to 6 and `hour` 0 to 23, in the venue's local time."""

    id: str
    picks: tuple[Pick, ...]
    weekday: int | None = None
    hour: int | None = None


@dataclass(frozen=True)
class TagRef:
    tag_id: str
    name: str
    type: str
    df: int  # distinct picked items that carry the tag
    idf: float


@dataclass
class Matrix:
    """The respondent-by-tag matrix and everything derived from the same picks."""

    respondent_ids: list[str]
    X: NDArray[
        np.float64
    ]  # (R, V) counts: each usable pick contributes mass 1 spread over its tags
    features: NDArray[np.float64]  # (R, V) l2-normalised tf-idf of X
    vocab: list[TagRef]
    entity_rows: NDArray[np.float64]  # (E, V) binary tag rows of the distinct usable items
    entity_ids: list[str]
    entity_names: list[str]
    entity_types: list[str]
    entity_counts: NDArray[np.float64]  # (E,) how many respondents picked each item
    pick_index: list[list[int]]  # per kept respondent, the entity rows they picked
    dropped: dict[str, int] = field(default_factory=dict)


@dataclass
class StabilityReport:
    raw: float
    null_permuted: float
    null_random_picks: float
    corrected: float  # raw minus the larger null mean
    p_permuted: (
        float  # share of null runs (counting the real one) at least as stable as the real crowd
    )
    p_random_picks: float
    null_runs: int
    ref_ari: float
    tag_overlap: list[
        float
    ]  # per reference tribe: top-tag Jaccard with its best match across bootstrap refits
    ref_sizes: list[int]
    bootstrap: int
    beats_both_nulls: bool
