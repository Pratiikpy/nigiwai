"""Settings with the numbers that come from proof tests D and G. Each carries its source, so nobody has to guess."""

from __future__ import annotations

from dataclasses import dataclass

# Rule G27 (ARCHITECTURE section 4): tag namespaces that describe a place's facilities, not anyone's taste.
DROPPED_NAMESPACES: tuple[str, ...] = (
    "wikipedia_category",
    "nearby_attraction",
    "offerings",
    "credit_card",
    "service_options",
    "amenity",
    "payment",
    "parking",
    "accessibility",
    "country",
)


@dataclass(frozen=True)
class TribesConfig:
    seed: int = 20261016  # proof D's seed
    k: int = 3  # PRD M4: K = 3 by default
    k5_min_respondents: int = 200  # K = 5 is not offered below this (proof G: 0.581 at 200)
    min_respondents: int = (
        60  # below this: not enough data (proof G: raw stability 0.508 at 60, about 0.41 at 30)
    )
    named_respondents: int = (
        200  # from here tribes are named (raw stability 0.649 at 200 on Qloo tags)
    )
    bootstrap: int = 50  # ARCHITECTURE 5.1 (the proofs used 200)
    null_runs: int = (
        19  # independent draws of each null model: the crowd must beat all 19 (one-sided p = 0.05)
    )
    alpha: float = 0.05  # largest null-model p-value at which the groups count as real
    min_group: int = 10  # smallest group any displayed aggregate may describe
    min_df: int = 3  # a tag must be carried by this many distinct picked items (proof G)
    min_usable_picks: int = 3  # a respondent needs this many picks with tags (proof G)
    min_tags_per_pick: int = 1  # a pick with no usable tags carries no signal
    top_tags: int = 10  # tags compared for tribe overlap (proof D TOPT)
    lift_min_support: int = 3  # distinct items behind a tag before its lift is shown
    lift_bootstrap: int = 200
    signature_min_respondents: int = 30  # category-pair signatures (proof D)
    odd_pair_min_tribe: int = 200  # genuine odd pairs only for a tribe this large
    nmf_max_iter: int = 500
    dropped_namespaces: tuple[str, ...] = DROPPED_NAMESPACES
