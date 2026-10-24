"""Inputs and outputs of the Fit Verdict. Plain frozen dataclasses: everything here is JSON-serialisable and hashable."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Status = Literal["ok", "insufficient", "fails_constraint", "unscored"]


@dataclass(frozen=True)
class Weights:
    """The v0 weights are a starting design, stored versioned and shown in the inspector. NOT VERIFIED."""

    version: str = "v0"
    group_fit: float = 0.8  # with peer evidence present
    peer: float = 0.2
    risk: float = 0.5  # how much of the score a fully poor-fit crowd removes
    risk_floor: float = 0.5  # a group the candidate ranks below this adds risk
    min_references: int = 8  # fewer returned references and the group is left out
    min_scored_share: float = 0.6  # groups scored must make up at least this share of the crowd
    bootstrap: int = 200
    interval: tuple[float, float] = (0.10, 0.90)
    strong: float = 0.75  # a group ranking at or above this is a reason
    weak: float = 0.35  # a group ranking below this is a watch-out


@dataclass(frozen=True)
class Group:
    """One group of the crowd the candidate is scored against."""

    index: int
    label: str
    share: float  # its share of the crowd (soft), before renormalising over the scored groups
    size: float  # guests, or acts for a lineup
    seed_ids: tuple[str, ...]
    seed_names: tuple[str, ...]
    weekday: tuple[float, ...] | None = (
        None  # 7 values, Monday first: share of the group's scans on each weekday
    )


@dataclass(frozen=True)
class Observation:
    """What Qloo returned for one group's call: the candidate's affinity (None when Qloo dropped it) and the references'."""

    index: int
    candidate: float | None
    references: tuple[float, ...]


@dataclass(frozen=True)
class Constraint:
    name: str
    status: Literal["pass", "fail", "not_scored"]
    detail: str


@dataclass(frozen=True)
class Crowd:
    """What the groups were drawn from. `memberships` (member x group, aligned with the groups) lets the band reflect who
    happened to be in the crowd; a lineup crowd has none."""

    kind: Literal["guests", "lineup"]
    n: int  # guests, or events
    provisional: bool
    sufficient: bool
    reason: str = ""
    memberships: tuple[tuple[float, ...], ...] | None = None


@dataclass(frozen=True)
class GroupFit:
    index: int
    label: str
    share: float  # renormalised over the scored groups; 0 for a group left out
    size: float
    status: Literal["scored", "no_affinity", "too_few_references"]
    fit: float | None  # percentile rank, 0 to 1
    references: int
    candidate_affinity: float | None
    alone: int | None  # the score if the whole crowd were this group


@dataclass(frozen=True)
class FitResult:
    status: Status
    reason: str
    provisional: bool
    score: int | None
    band: tuple[int, int] | None
    groups: tuple[GroupFit, ...]
    components: dict[str, float | None]
    weights: Weights
    peer_used: bool
    formula: str
    constraints: tuple[Constraint, ...]
    why: tuple[str, ...]
    watch: tuple[str, ...]
    nights: tuple[float, ...] | None
    suits: tuple[int, ...]
    notes: tuple[str, ...]
    input_hash: str
    crowd: dict[str, object] = field(default_factory=dict)
