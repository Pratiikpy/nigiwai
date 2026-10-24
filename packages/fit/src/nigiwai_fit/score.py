"""The Fit Verdict, computed in code from visible components (see the README for the definition)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import asdict
from typing import Any, NamedTuple

import numpy as np
from numpy.typing import NDArray

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

TIE_PLACES = 9


class _Row(NamedTuple):
    group: Group
    fit: float
    refs: tuple[float, ...]
    candidate: float


def percentile_rank(candidate: float, references: Sequence[float]) -> float:
    """Share of the references the candidate beats; a tie counts half. Raises on an empty reference set."""
    if not references:
        raise ValueError("a percentile rank needs at least one reference")
    c = round(candidate, TIE_PLACES)
    below = sum(1 for r in references if round(r, TIE_PLACES) < c)
    ties = sum(1 for r in references if round(r, TIE_PLACES) == c)
    return (below + 0.5 * ties) / len(references)


def _risk(shares: NDArray[np.float64], fits: NDArray[np.float64], w: Weights) -> float:
    """Weight of the crowd the candidate ranks below the floor for; 0 to 1."""
    return float(np.sum(shares * np.maximum(0.0, w.risk_floor - fits)) / w.risk_floor)


def raw_score(
    shares: NDArray[np.float64], fits: NDArray[np.float64], peer: float | None, w: Weights
) -> float:
    """The unrounded score. Without peer evidence its weight moves to the group fit."""
    group = float(np.sum(shares * fits))
    base = w.group_fit * group + w.peer * peer if peer is not None else group
    return 100.0 * base * (1.0 - w.risk * _risk(shares, fits, w))


def formula(w: Weights, peer_used: bool) -> str:
    if peer_used:
        return (
            f"Score = 100 x ({w.group_fit:g} x group fit + {w.peer:g} x peer evidence) x (1 - {w.risk:g} x risk). "
            "Group fit is the share-weighted rank of the act among the references Qloo returned for each group; "
            f"risk is the share of the crowd ranking the act below {w.risk_floor:g}, scaled to 0 to 1."
        )
    return (
        f"Score = 100 x group fit x (1 - {w.risk:g} x risk). Peer evidence is not available here, so it carries no weight. "
        "Group fit is the share-weighted rank of the act among the references Qloo returned for each group; "
        f"risk is the share of the crowd ranking the act below {w.risk_floor:g}, scaled to 0 to 1."
    )


def _hash(payload: dict[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=list)
    return hashlib.sha256(blob.encode()).hexdigest()


def input_hash(
    candidate_id: str,
    groups: Sequence[Group],
    observations: Sequence[Observation],
    crowd: Crowd,
    constraints: Sequence[Constraint],
    peer: float | None,
    weights: Weights,
    venue_weekday: Sequence[float] | None = None,
) -> str:
    return _hash(
        {
            "candidate": candidate_id,
            # Names and labels are for display; what the score depends on is who was asked about and with what weight.
            "groups": [
                {k: v for k, v in asdict(g).items() if k not in ("label", "seed_names")}
                for g in groups
            ],
            "observations": [asdict(o) for o in observations],
            "crowd": {
                "kind": crowd.kind,
                "n": crowd.n,
                "provisional": crowd.provisional,
                "sufficient": crowd.sufficient,
                "memberships": crowd.memberships,
            },
            "constraints": [asdict(c) for c in constraints],
            "peer": peer,
            "weights": asdict(weights),
            "venue_weekday": list(venue_weekday) if venue_weekday is not None else None,
        }
    )


def _pct(x: float) -> int:
    return round(100 * x)


def _empty(
    status: Status,
    reason: str,
    *,
    crowd: Crowd,
    weights: Weights,
    constraints: Sequence[Constraint],
    digest: str,
    peer_used: bool,
    notes: Sequence[str] = (),
) -> FitResult:
    return FitResult(
        status=status,
        reason=reason,
        provisional=crowd.provisional,
        score=None,
        band=None,
        groups=(),
        components={"group_fit": None, "peer": None, "risk": None},
        weights=weights,
        peer_used=peer_used,
        formula=formula(weights, peer_used),
        constraints=tuple(constraints),
        why=(),
        watch=(),
        nights=None,
        suits=(),
        notes=tuple(notes),
        input_hash=digest,
        crowd={"kind": crowd.kind, "n": crowd.n},
    )


def compute_fit(
    candidate_id: str,
    groups: Sequence[Group],
    observations: Sequence[Observation],
    crowd: Crowd,
    constraints: Sequence[Constraint] = (),
    peer: float | None = None,
    weights: Weights | None = None,
    venue_weekday: Sequence[float] | None = None,
) -> FitResult:
    w = weights or Weights()
    peer_used = peer is not None
    digest = input_hash(
        candidate_id, groups, observations, crowd, constraints, peer, w, venue_weekday
    )

    def empty(status: Status, reason: str) -> FitResult:
        return _empty(
            status,
            reason,
            crowd=crowd,
            weights=w,
            constraints=constraints,
            digest=digest,
            peer_used=peer_used,
        )

    failed = [c for c in constraints if c.status == "fail"]
    if failed:
        return empty("fails_constraint", "Fails: " + "; ".join(c.detail for c in failed) + ".")
    if not crowd.sufficient:
        return empty("insufficient", crowd.reason or "Not enough data yet.")

    seen = {o.index: o for o in observations}
    fits: list[GroupFit] = []
    scored_rows: list[_Row] = []
    for g in groups:
        o = seen.get(g.index)
        if o is None or o.candidate is None:
            fits.append(GroupFit(g.index, g.label, 0.0, g.size, "no_affinity", None, 0, None, None))
        elif len(o.references) < w.min_references:
            fits.append(
                GroupFit(
                    g.index,
                    g.label,
                    0.0,
                    g.size,
                    "too_few_references",
                    None,
                    len(o.references),
                    o.candidate,
                    None,
                )
            )
        else:
            f = percentile_rank(o.candidate, o.references)
            scored_rows.append(_Row(g, f, o.references, o.candidate))
            fits.append(
                GroupFit(
                    g.index,
                    g.label,
                    g.share,
                    g.size,
                    "scored",
                    f,
                    len(o.references),
                    o.candidate,
                    None,
                )
            )

    total = sum(g.share for g in groups)
    scored_total = sum(r.group.share for r in scored_rows)
    if not scored_rows or total <= 0:
        return empty(
            "unscored",
            "Qloo returned no taste link between this act and any of your groups, so there is nothing to score.",
        )
    if scored_total / total < w.min_scored_share:
        return empty(
            "insufficient",
            f"Qloo could score this act for groups making up only {_pct(scored_total / total)}% of your crowd; "
            f"at least {_pct(w.min_scored_share)}% is needed.",
        )

    shares = np.array([r.group.share / scored_total for r in scored_rows])
    f_arr = np.array([r.fit for r in scored_rows])
    point = raw_score(shares, f_arr, peer, w)
    score = round(point)
    group_fit = float(np.sum(shares * f_arr))
    risk = _risk(shares, f_arr, w)

    band = _band(scored_rows, groups, crowd, peer, w, digest, score)

    resolved: list[GroupFit] = []
    scored = {r.group.index: (r.fit, float(s)) for r, s in zip(scored_rows, shares, strict=True)}
    for gf in fits:
        if gf.index in scored:
            f, share = scored[gf.index]
            alone = round(raw_score(np.array([1.0]), np.array([f]), peer, w))
            resolved.append(
                GroupFit(
                    gf.index,
                    gf.label,
                    share,
                    gf.size,
                    gf.status,
                    f,
                    gf.references,
                    gf.candidate_affinity,
                    alone,
                )
            )
        else:
            resolved.append(gf)

    why, watch = _reasons(groups, resolved, w, crowd)
    notes: list[str] = []
    if crowd.provisional:
        notes.append(
            "Provisional: built from public lineups or a small crowd, so it will move as more is known."
        )
    if not peer_used:
        notes.append("Peer evidence is omitted: no data on what similar venues nearby book.")
    if band[1] - band[0] >= 25:
        notes.append("The range is wide, so treat the score as a rough guide.")
    nights = _nights(groups, resolved, venue_weekday)

    return FitResult(
        status="ok",
        reason="",
        provisional=crowd.provisional,
        score=score,
        band=band,
        groups=tuple(resolved),
        components={"group_fit": round(group_fit, 4), "peer": peer, "risk": round(risk, 4)},
        weights=w,
        peer_used=peer_used,
        formula=formula(w, peer_used),
        constraints=tuple(constraints),
        why=tuple(why),
        watch=tuple(watch),
        nights=nights[0],
        suits=nights[1],
        notes=tuple(notes),
        input_hash=digest,
        crowd={"kind": crowd.kind, "n": crowd.n},
    )


def _band(
    rows: Sequence[_Row],
    groups: Sequence[Group],
    crowd: Crowd,
    peer: float | None,
    w: Weights,
    digest: str,
    score: int,
) -> tuple[int, int]:
    """10th to 90th percentile over bootstrap draws: references resampled within each group, and crowd members resampled
    when their memberships are known. Seeded from the input hash, so the same input gives the same band."""
    rng = np.random.default_rng(int(digest[:16], 16))
    position = {g.index: k for k, g in enumerate(groups)}
    mem: NDArray[np.float64] | None = None
    if crowd.memberships:
        m = np.array(crowd.memberships, dtype=float)
        if m.ndim == 2 and m.shape[1] == len(groups) and m.shape[0] > 0:
            mem = m[:, [position[r.group.index] for r in rows]]
    base = np.array([r.group.share for r in rows])
    draws = np.empty(w.bootstrap)
    for b in range(w.bootstrap):
        f_star = np.empty(len(rows))
        for k, r in enumerate(rows):
            sample = rng.choice(np.array(r.refs), size=len(r.refs), replace=True)
            f_star[k] = percentile_rank(r.candidate, sample.tolist())
        if mem is not None:
            s = mem[rng.integers(0, mem.shape[0], size=mem.shape[0])].mean(axis=0)
        else:
            s = base
        total = float(s.sum())
        s = s / total if total > 0 else base / base.sum()
        draws[b] = raw_score(s, f_star, peer, w)
    lo, hi = np.percentile(draws, [100 * w.interval[0], 100 * w.interval[1]])
    return min(round(float(lo)), score), max(round(float(hi)), score)


def _reasons(
    groups: Sequence[Group], fits: Sequence[GroupFit], w: Weights, crowd: Crowd
) -> tuple[list[str], list[str]]:
    seeds = {g.index: g for g in groups}
    unit = "guests" if crowd.kind == "guests" else "acts"
    why: list[str] = []
    watch: list[str] = []
    for gf in sorted(
        (x for x in fits if x.status == "scored"), key=lambda x: -(x.share * (x.fit or 0))
    ):
        names = seeds[gf.index].seed_names[:2]
        if gf.fit is not None and gf.fit >= w.strong:
            tail = f", such as {' and '.join(names)}" if names else ""
            why.append(
                f"Close to what {gf.label} pick{tail} ({_pct(gf.share)}% of your crowd, about {round(gf.size)} {unit})."
            )
    for gf in sorted((x for x in fits if x.status == "scored"), key=lambda x: -x.share):
        if gf.fit is not None and gf.fit < w.weak and gf.share >= 0.10:
            watch.append(
                f"{gf.label} ({_pct(gf.share)}% of your crowd) share few picks with this act."
            )
    for gf in fits:
        if gf.status != "scored":
            watch.append(
                f"Qloo has no taste link between this act and {gf.label}, so that group is left out of the score."
            )
    return why, watch


def _nights(
    groups: Sequence[Group],
    fits: Sequence[GroupFit],
    venue_weekday: Sequence[float] | None = None,
) -> tuple[tuple[float, ...] | None, tuple[int, ...]]:
    """Which weekdays the act suits: each scored group's weekday pattern, weighted by its share and its fit. A group
    with no pattern of its own uses the venue's (for example the weekdays of its public lineup)."""
    weight = np.zeros(7)
    have = False
    by_index = {g.index: g for g in groups}
    for gf in fits:
        g = by_index[gf.index]
        pattern = g.weekday if g.weekday is not None else venue_weekday
        if (
            gf.status == "scored"
            and pattern is not None
            and len(pattern) == 7
            and gf.fit is not None
        ):
            weight += gf.share * gf.fit * np.array(pattern)
            have = True
    if not have or weight.max() <= 0:
        return None, ()
    norm = weight / weight.max()
    order = [int(d) for d in np.argsort(-norm, kind="stable") if norm[d] >= 0.6][:3]
    return tuple(round(float(x), 3) for x in norm), tuple(sorted(order))


def to_dict(result: FitResult) -> dict[str, Any]:
    out: dict[str, Any] = json.loads(json.dumps(asdict(result), default=list))
    return out
