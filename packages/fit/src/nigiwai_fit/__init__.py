"""The Fit Verdict: a transparent, reproducible 0 to 100 fit of a candidate against a crowd's groups."""

from .score import compute_fit, formula, input_hash, percentile_rank, raw_score, to_dict
from .types import (
    Constraint,
    Crowd,
    FitResult,
    Group,
    GroupFit,
    Observation,
    Status,
    Weights,
)

__all__ = [
    "Constraint",
    "Crowd",
    "FitResult",
    "Group",
    "GroupFit",
    "Observation",
    "Status",
    "Weights",
    "compute_fit",
    "formula",
    "input_hash",
    "percentile_rank",
    "raw_score",
    "to_dict",
]
