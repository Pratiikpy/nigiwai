"""Respondents in, one immutable tribe result out. Pure and deterministic: the same picks and settings give the same JSON."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import linear_sum_assignment

from .build import build_matrix, usable_tags
from .config import TribesConfig
from .model import fit_nmf, memberships, project
from .naming import name_tribe, tribe_items, tribe_tag_lifts
from .rhythm import weekday_hour
from .signature import category_pairs
from .stability import measure
from .types import Pick, Respondent, Unlock

RESULT_VERSION = 1
NAME_CARRY_COSINE = (
    0.7  # ARCHITECTURE 5.2: a tribe keeps its previous name at or above this similarity
)


@dataclass
class TribeCard:
    index: int
    name: str | None  # only from the named stage; provisional groups are labelled by position
    label: str  # what a screen calls it: the name, or "Group A"
    line: str
    soft_size: float
    share: float
    shown: bool  # False when the group is smaller than the minimum group size: its details are withheld
    top_tags: list[dict[str, Any]] = field(default_factory=list)
    top_items: list[dict[str, Any]] = field(default_factory=list)
    used_tags: list[str] = field(default_factory=list)
    signatures: list[dict[str, Any]] = field(default_factory=list)
    rhythm: list[list[float]] = field(default_factory=list)
    tag_overlap: float | None = (
        None  # top-tag Jaccard across bootstrap refits: how reproducible this tribe is
    )


@dataclass
class TribeResult:
    version: int
    state: Unlock
    reason: str
    n: int
    k: int
    input_hash: str
    stability: dict[str, Any] | None
    vocab: list[dict[str, Any]]  # {tag_id, name, type, df, idf}
    h: list[
        list[float]
    ]  # (K, V) fitted tribe profiles, kept so a new guest can be placed without refitting
    tribes: list[TribeCard]
    crowd_rhythm: list[list[float]]
    timed: int
    dropped: dict[str, int]
    config: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def input_hash(respondents: list[Respondent], cfg: TribesConfig) -> str:
    """A fingerprint of what the model saw, so an unchanged crowd is recognised and not recomputed."""
    payload = [
        [
            r.id,
            sorted([p.entity_id, sorted(t.tag_id for t in p.tags)] for p in r.picks),
            r.weekday,
            r.hour,
        ]
        for r in sorted(respondents, key=lambda r: r.id)
    ]
    blob = json.dumps(
        {"r": payload, "cfg": asdict(cfg), "v": RESULT_VERSION},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _empty(
    state: Unlock, reason: str, n: int, cfg: TribesConfig, digest: str, dropped: dict[str, int]
) -> TribeResult:
    return TribeResult(
        version=RESULT_VERSION,
        state=state,
        reason=reason,
        n=n,
        k=cfg.k,
        input_hash=digest,
        stability=None,
        vocab=[],
        h=[],
        tribes=[],
        crowd_rhythm=[],
        timed=0,
        dropped=dropped,
        config=asdict(cfg),
    )


def compute(respondents: list[Respondent], cfg: TribesConfig | None = None) -> TribeResult:
    cfg = cfg or TribesConfig()
    # NMF is not convex, so row order could pick a different optimum: always fit in one canonical order.
    respondents = sorted(respondents, key=lambda r: r.id)
    digest = input_hash(respondents, cfg)
    matrix = build_matrix(respondents, cfg)
    n = len(matrix.respondent_ids)
    v = len(matrix.vocab)
    if n < cfg.min_respondents:
        return _empty(
            "none",
            f"{n} guests with usable picks so far; groups appear from {cfg.min_respondents}.",
            n,
            cfg,
            digest,
            matrix.dropped,
        )
    k = cfg.k
    if v < k * 3:
        return _empty(
            "none",
            "The picks share too few tags to tell groups apart yet.",
            n,
            cfg,
            digest,
            matrix.dropped,
        )

    stability = measure(matrix, k, cfg)
    stab_dict = asdict(stability)
    if not stability.beats_both_nulls:
        res = _empty(
            "unstable",
            "The groups are no more stable than chance would make them, so none are shown.",
            n,
            cfg,
            digest,
            matrix.dropped,
        )
        res.stability = stab_dict
        return res

    state: Unlock = "named" if n >= cfg.named_respondents else "provisional"
    model = fit_nmf(matrix.features, k, cfg.nmf_max_iter)
    m = memberships(model, matrix.features)
    h = model.components_
    rng = np.random.default_rng(np.random.SeedSequence([cfg.seed, n, k, 7]))
    grids, crowd, timed = weekday_hour(respondents, matrix.respondent_ids, m)
    sigs = (
        category_pairs(matrix, m, cfg)
        if n >= cfg.signature_min_respondents
        else [[] for _ in range(k)]
    )

    order = np.argsort(
        -m.sum(axis=0), kind="stable"
    )  # biggest tribe first, so indexes are stable and readable
    tribes: list[TribeCard] = []
    h_sorted = []
    for new_i, t in enumerate(order):
        size = float(m[:, t].sum())
        shown = size >= cfg.min_group
        lifts = tribe_tag_lifts(matrix, m, int(t), cfg, rng) if shown else []
        items = tribe_items(matrix, m, int(t)) if shown else []
        tn = name_tribe(lifts, items, new_i)
        letter = "ABCDEFGH"[new_i % 8]
        tribes.append(
            TribeCard(
                index=new_i,
                name=tn.name if state == "named" and shown else None,
                label=tn.name if state == "named" and shown else f"Group {letter}",
                line=tn.line,
                soft_size=round(size, 3),
                share=round(size / n, 4),
                shown=shown,
                top_tags=[
                    {
                        "tag_id": x.tag_id,
                        "name": x.name,
                        "lift": round(x.lift, 3),
                        "lo": round(x.lo, 3),
                        "hi": round(x.hi, 3),
                        "support": x.support,
                    }
                    for x in lifts
                ],
                top_items=[
                    {
                        "entity_id": i.entity_id,
                        "name": i.name,
                        "type": i.type,
                        "weight": round(i.weight, 3),
                    }
                    for i in items
                ],
                used_tags=tn.used_tags if state == "named" else [],
                signatures=[
                    {
                        "types": list(s.types),
                        "tribe_share": round(s.tribe_share, 3),
                        "crowd_share": round(s.crowd_share, 3),
                        "lift": round(s.lift, 3),
                        "q": round(s.q, 4),
                        "group_size": round(s.group_size, 1),
                        "odd": s.odd,
                    }
                    for s in sigs[int(t)]
                ]
                if shown
                else [],
                rhythm=grids[int(t)] if shown else [],
                tag_overlap=round(stability.tag_overlap[int(t)], 3)
                if int(t) < len(stability.tag_overlap)
                else None,
            )
        )
        h_sorted.append(h[int(t)])

    return TribeResult(
        version=RESULT_VERSION,
        state=state,
        reason="",
        n=n,
        k=k,
        input_hash=digest,
        stability=stab_dict,
        vocab=[
            {"tag_id": t.tag_id, "name": t.name, "type": t.type, "df": t.df, "idf": round(t.idf, 6)}
            for t in matrix.vocab
        ],
        h=[[round(float(x), 6) for x in row] for row in h_sorted],
        tribes=tribes,
        crowd_rhythm=crowd,
        timed=timed,
        dropped=matrix.dropped,
        config=asdict(cfg),
    )


def carry_names(previous: TribeResult | None, new: TribeResult) -> None:
    """Identity across versions: match tribes to the previous version by the cosine of their profiles (Hungarian
    assignment over the shared tags). A match at 0.7 or above keeps its old name; anything else keeps its new one."""
    if (
        previous is None
        or previous.state != "named"
        or new.state != "named"
        or not previous.h
        or not new.h
    ):
        return
    old_ix = {t["tag_id"]: i for i, t in enumerate(previous.vocab)}
    shared = [(old_ix[t["tag_id"]], j) for j, t in enumerate(new.vocab) if t["tag_id"] in old_ix]
    if not shared:
        return
    a = np.array(previous.h)[:, [i for i, _ in shared]]
    b = np.array(new.h)[:, [j for _, j in shared]]
    an = a / np.maximum(np.linalg.norm(a, axis=1, keepdims=True), 1e-12)
    bn = b / np.maximum(np.linalg.norm(b, axis=1, keepdims=True), 1e-12)
    cos = bn @ an.T  # (new, old)
    rows, cols = linear_sum_assignment(-cos)
    for r, c in zip(rows, cols, strict=True):
        if cos[r, c] >= NAME_CARRY_COSINE and previous.tribes[c].name and new.tribes[r].shown:
            new.tribes[r].name = previous.tribes[c].name
            new.tribes[r].label = previous.tribes[c].name


@dataclass
class Placement:
    memberships: list[float]  # per tribe, summing to 1
    best: int
    confidence: float  # the best tribe's share of the mixture


def place(
    result: TribeResult, picks: list[Pick], cfg: TribesConfig | None = None
) -> Placement | None:
    """Where one guest sits among the tribes of this result, from their picks' tags. None when the crowd has no
    groups yet or none of the guest's tags are in this crowd's vocabulary."""
    cfg = cfg or TribesConfig()
    if result.state not in ("provisional", "named") or not result.h:
        return None
    vix = {t["tag_id"]: i for i, t in enumerate(result.vocab)}
    idf: NDArray[np.float64] = np.array([t["idf"] for t in result.vocab])
    rows: list[NDArray[np.float64]] = []
    for p in picks:
        row = np.zeros(len(vix))
        for tag_id in usable_tags(p, cfg):
            j = vix.get(tag_id)
            if j is not None:
                row[j] = 1.0
        if row.sum() > 0:
            rows.append(row)
    w = project(np.array(result.h), idf, rows)
    if w is None:
        return None
    best = int(np.argmax(w))
    return Placement([round(float(x), 4) for x in w], best, float(w[best]))
