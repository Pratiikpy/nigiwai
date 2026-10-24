"""Grow (PRD M8): who else might come, who already serves the crowd nearby, and lookalike venues elsewhere.

Pure functions. Qloo is asked elsewhere (services/grow.py); this module decides what the answers are allowed to say.

What was measured before this was built (a probe of three real venues, recorded in docs/DECISIONS.md D25): Qloo's lists of
neighbouring *acts* differ completely between a venue's groups (overlap 0.00 to 0.05), so ghost customers are group-specific.
Its lists of *places*, asked for with each group's acts as the signal, mostly do not: at two venues every group got the very same
places, at the third about half. So places are never presented as a match for one group unless the run itself shows the groups
were told apart, and every list says whether Qloo's answer changed when it was given the crowd's taste at all.

Three checks decide what is shown, each on the owner's own groups, each time:
- acts: the groups' neighbouring acts must overlap by at most ACT_SIMILARITY_MAX, or ghost customers are not shown per group;
- seed effect: the places Qloo gives with the crowd's taste must differ from the places it gives without it by at least
  SEED_EFFECT_MIN, or the list is labelled "near you", not "matched";
- told apart: the groups' place lists must overlap by at most PLACE_SIMILARITY_MAX. Two unrelated top-10 lists drawn from the
  same 20 places overlap by about 0.33 by chance, so below 0.3 means the groups really got different places. Only then are
  places listed per group, and only then can a group be shown to have no place of its own (a gap candidate).
All three limits are choices, not calibrated; they are deliberately strict, and the run prints the numbers it used.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

MIN_GROUP_GUESTS = (
    10  # a group smaller than this is not read, and no count under it is shown (privacy minimum)
)
MIN_GROUP_ACTS = 3  # for scenes made from public lineups: acts, not people
GHOST_MIN_ACTS = 2  # a tag needs this many neighbouring acts carrying it, and as many bridged ones
GHOST_ABSENT_SHARE = (
    0.05  # at most this share of the crowd carries the tag for it to count as absent
)
BRIDGE_SHARE = 0.25  # a tag at least this common in a group is one that group clearly has
GHOSTS_PER_GROUP = 3
ACTS_PER_GHOST = 3
GENRE_NAMESPACES = ("genre", "subgenre")
LIST_N = 10  # lists are compared on their first ten
SHOW_N = 5  # and the first five are shown
MIN_PLACES = 5  # fewer places than this in a list and it cannot be compared
ACT_SIMILARITY_MAX = 0.5
SEED_EFFECT_MIN = 0.5
PLACE_SIMILARITY_MAX = 0.3


# -------------------------------------------------------------------------------------------------- comparing lists
def jaccard(a: list[str], b: list[str]) -> float:
    """Overlap of two lists as sets: shared over combined, 0 to 1. Two empty lists overlap by 0."""
    sa, sb = set(a), set(b)
    union = sa | sb
    return len(sa & sb) / len(union) if union else 0.0


def mean_pairwise(lists: dict[int, list[str]]) -> float | None:
    """Mean overlap over every pair of lists, or None when there are fewer than two."""
    keys = sorted(lists)
    pairs = [
        jaccard(lists[a][:LIST_N], lists[b][:LIST_N])
        for i, a in enumerate(keys)
        for b in keys[i + 1 :]
    ]
    return sum(pairs) / len(pairs) if pairs else None


def seed_effect(with_taste: list[str], without: list[str]) -> float | None:
    """How much the places changed when Qloo was given the crowd's taste: 1 minus their overlap, or None with no baseline."""
    if not with_taste or not without:
        return None
    return 1.0 - jaccard(with_taste[:LIST_N], without[:LIST_N])


# ------------------------------------------------------------------------------------------------ ghost customers
@dataclass(frozen=True)
class GroupInfo:
    index: int
    label: str
    share: float
    size: float


@dataclass(frozen=True)
class Neighbour:
    """An act Qloo lists next to a group's favourites, with its genre tags as (tag id, name)."""

    entity_id: str
    name: str
    affinity: float
    genres: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Presence:
    """What the crowd already carries. `unit` is "guests" (people who scanned) or "acts" (a public lineup, when there are no
    guests yet). `carriers` counts how many of `total` carry each genre tag, all groups together; `group_share` is, per group, the
    membership-weighted share of its members who carry each tag."""

    unit: str
    total: int
    min_group: int
    carriers: dict[str, int]
    group_share: dict[int, dict[str, float]]
    tag_names: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Ghost:
    group_index: int
    tag_id: str
    tag: str
    bridges: tuple[str, ...]
    carrying: (
        int | None
    )  # guests (or acts) already carrying the tag; None when under the privacy minimum
    unit: str
    neighbours_with_tag: int
    acts: tuple[tuple[str, str, tuple[str, ...]], ...]  # (entity id, name, up to three genre names)

    def to_json(self) -> dict[str, Any]:
        return {
            "group_index": self.group_index,
            "tag_id": self.tag_id,
            "tag": self.tag,
            "bridges": list(self.bridges),
            "carrying": self.carrying,
            "unit": self.unit,
            "neighbours_with_tag": self.neighbours_with_tag,
            "acts": [{"entity_id": e, "name": n, "genres": list(g)} for e, n, g in self.acts],
        }


def genre_tags(raw: list[tuple[str, str, str]] | tuple[Any, ...]) -> tuple[tuple[str, str], ...]:
    """(tag id, name) for the tags that name a genre, from (tag id, name, type) rows. A genre is a tag whose namespace
    (the third part of `urn:tag:<namespace>:...`, or of its type) is genre or subgenre."""
    out: dict[str, str] = {}
    for tag_id, name, kind in raw:
        ns_id = tag_id.split(":")[2] if tag_id.count(":") >= 2 else ""
        ns_type = kind.split(":")[2] if kind and kind.count(":") >= 2 else ""
        if (ns_id in GENRE_NAMESPACES or ns_type in GENRE_NAMESPACES) and name.strip():
            out.setdefault(tag_id, name.strip())
    return tuple(out.items())


def _squash(name: str) -> str:
    return "".join(ch for ch in name.casefold() if ch.isalnum())


def variant_of(a: str, b: str) -> bool:
    """True when one genre name is the other with something added or taken away ("Metal" and "Heavy Metal", "Pop" and
    "Electropop"). A ghost must be a different taste next to the group's, not a variant of what it already has."""
    sa, sb = _squash(a), _squash(b)
    short, long_ = sorted((sa, sb), key=len)
    return len(short) >= 3 and short in long_


def act_similarity(neighbours: dict[int, list[Neighbour]]) -> float | None:
    return mean_pairwise({g: [n.entity_id for n in ns] for g, ns in neighbours.items() if ns})


def find_ghosts(
    groups: list[GroupInfo], neighbours: dict[int, list[Neighbour]], presence: Presence
) -> list[Ghost]:
    """For each group, genres its Qloo neighbours share that almost none of the crowd has, in acts that also carry a genre the
    group clearly has. Those acts are what would bring the people who like that genre next to this group's taste."""
    found: list[Ghost] = []
    for g in groups:
        near = neighbours.get(g.index, [])
        if not near or g.size < presence.min_group:
            continue
        mine = presence.group_share.get(g.index, {})
        bridges = {t for t, s in mine.items() if s >= BRIDGE_SHARE}
        if not bridges:
            continue
        carriers: dict[str, list[Neighbour]] = {}
        for n in near:
            for tag_id, _ in n.genres:
                carriers.setdefault(tag_id, []).append(n)
        names = {tid: nm for n in near for tid, nm in n.genres}
        candidates: list[tuple[int, float, str, str, list[Neighbour], list[str]]] = []
        for tag_id, with_tag in carriers.items():
            if tag_id in bridges:
                continue
            if any(
                variant_of(names[tag_id], presence.tag_names.get(b) or names.get(b) or "")
                for b in bridges
            ):
                continue
            if (
                presence.total <= 0
                or presence.carriers.get(tag_id, 0) / presence.total > GHOST_ABSENT_SHARE
            ):
                continue
            if mine.get(tag_id, 0.0) > GHOST_ABSENT_SHARE:
                continue
            bridged = [n for n in with_tag if any(t in bridges for t, _ in n.genres)]
            if len(with_tag) < GHOST_MIN_ACTS or len(bridged) < GHOST_MIN_ACTS:
                continue
            via = sorted(
                {t for n in bridged for t, _ in n.genres if t in bridges},
                key=lambda t: (-mine[t], t),
            )
            candidates.append(
                (
                    len(bridged),
                    sum(n.affinity for n in bridged),
                    names[tag_id],
                    tag_id,
                    bridged,
                    via,
                )
            )
        candidates.sort(key=lambda c: (-c[0], -c[1], c[2], c[3]))
        for _, _, tag_name, tag_id, bridged, via in candidates[:GHOSTS_PER_GROUP]:
            carrying = presence.carriers.get(tag_id, 0)
            best = sorted(bridged, key=lambda n: (-n.affinity, n.name, n.entity_id))[
                :ACTS_PER_GHOST
            ]
            bridge_names = tuple(presence.tag_names.get(t) or names.get(t) or t for t in via[:2])
            found.append(
                Ghost(
                    group_index=g.index,
                    tag_id=tag_id,
                    tag=tag_name,
                    bridges=bridge_names,
                    carrying=None if carrying < presence.min_group else carrying,
                    unit=presence.unit,
                    neighbours_with_tag=len(carriers[tag_id]),
                    acts=tuple(
                        (n.entity_id, n.name, tuple(nm for _, nm in n.genres[:3])) for n in best
                    ),
                )
            )
    return found


def ghost_section(
    groups: list[GroupInfo],
    neighbours: dict[int, list[Neighbour]],
    presence: Presence,
    skipped: dict[int, str],
) -> dict[str, Any]:
    """The ghost-customers part of a run: the findings, or the reason there are none, with the check that was used."""
    similarity = act_similarity(neighbours)
    base: dict[str, Any] = {
        "unit": presence.unit,
        "act_similarity": None if similarity is None else round(similarity, 2),
        "groups_read": sorted(g for g, ns in neighbours.items() if ns),
        "skipped": [{"group_index": k, "reason": v} for k, v in sorted(skipped.items())],
        "limit": {
            "similarity_max": ACT_SIMILARITY_MAX,
            "absent_share": GHOST_ABSENT_SHARE,
            "bridge_share": BRIDGE_SHARE,
            "min_acts": GHOST_MIN_ACTS,
            "min_group": presence.min_group,
        },
    }
    if not any(neighbours.values()):
        return {
            **base,
            "status": "none",
            "items": [],
            "reason": "Qloo returned no neighbouring acts for any group.",
        }
    if similarity is not None and similarity > ACT_SIMILARITY_MAX:
        return {
            **base,
            "status": "not_group_specific",
            "items": [],
            "reason": (
                f"Qloo gave your groups mostly the same neighbouring acts (overlap {similarity:.0%}), so it cannot say "
                "who is missing from one group rather than another."
            ),
        }
    items = find_ghosts(groups, neighbours, presence)
    if not items:
        return {
            **base,
            "status": "none",
            "items": [],
            "reason": "No genre turned up in Qloo's neighbouring acts that your crowd almost never picks, in acts that also share a genre it clearly has.",
        }
    return {**base, "status": "ok", "items": [i.to_json() for i in items], "reason": ""}


# ---------------------------------------------------------------------------------------------------------- places
@dataclass(frozen=True)
class Place:
    entity_id: str
    name: str
    distance_m: int | None
    address: str | None = None
    lat: float | None = None
    lon: float | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "name": self.name,
            "distance_m": self.distance_m,
            "address": self.address,
            "lat": self.lat,
            "lon": self.lon,
        }


def _ids(places: list[Place]) -> list[str]:
    return [p.entity_id for p in places]


@dataclass
class PlaceLists:
    """Everything one part of the places section is decided from. `by_group` is keyed by group index."""

    crowd: list[Place]
    plain: list[Place]
    by_group: dict[int, list[Place]] = field(default_factory=dict)


def places_section(
    lists: PlaceLists, groups: list[GroupInfo], *, label: str, outside_only_m: int | None = None
) -> dict[str, Any]:
    """One list of places and what the checks allow it to say.

    `crowd` is what Qloo gave with the whole crowd's taste; `plain` is the same question without it; `by_group` is what it gave
    with each group's taste. With `outside_only_m`, places inside that distance are left out (the lookalike list)."""

    def trim(ps: list[Place]) -> list[Place]:
        if outside_only_m is None:
            return ps
        return [p for p in ps if p.distance_m is None or p.distance_m > outside_only_m]

    crowd = trim(lists.crowd)
    plain = trim(lists.plain)
    effect = seed_effect(_ids(crowd), _ids(plain))
    shared: dict[str, Any] = {
        "label": label,
        "crowd_size": len(crowd),
        "seed_effect": None if effect is None else round(effect, 2),
        "limit": {"seed_effect_min": SEED_EFFECT_MIN, "similarity_max": PLACE_SIMILARITY_MAX},
    }
    if not crowd:
        return {
            **shared,
            "status": "empty",
            "mode": None,
            "items": [],
            "similarity": None,
            "told_apart": False,
            "by_group": None,
        }
    # "matched" only when asking with the crowd's taste actually changed the answer; with no baseline it cannot be claimed
    mode = "taste" if effect is not None and effect >= SEED_EFFECT_MIN else "near"
    group_lists = {g: trim(ps) for g, ps in lists.by_group.items()}
    enough = {g: ps for g, ps in group_lists.items() if len(ps) >= MIN_PLACES}
    similarity = mean_pairwise({g: _ids(ps) for g, ps in enough.items()})
    told_apart = (
        mode == "taste"
        and similarity is not None
        and len(enough) == len(group_lists)
        and len(enough) >= 2
        and similarity <= PLACE_SIMILARITY_MAX
    )
    by_group: list[dict[str, Any]] | None = None
    if told_apart:
        names = {g.index: g for g in groups}
        by_group = []
        for g, ps in sorted(group_lists.items()):
            others = {pid for h, qs in group_lists.items() if h != g for pid in _ids(qs[:LIST_N])}
            own = [p for p in ps[:LIST_N] if p.entity_id not in others]
            info = names.get(g)
            by_group.append(
                {
                    "group_index": g,
                    "group": info.label if info else f"Group {g + 1}",
                    "items": [p.to_json() for p in (own or ps)[:SHOW_N]],
                    "own": bool(own),
                }
            )
    return {
        **shared,
        "status": "ok",
        "mode": mode,
        "items": [p.to_json() for p in crowd[:SHOW_N]],
        "similarity": None if similarity is None else round(similarity, 2),
        "told_apart": told_apart,
        "by_group": by_group,
    }


def gaps_from(section: dict[str, Any]) -> list[dict[str, Any]]:
    """Groups that, when the places were told apart, have no place of their own among Qloo's first ten. Empty when the groups
    were not told apart: then Qloo gave no group-specific places, which says nothing about whether any exist."""
    if not section.get("told_apart") or not section.get("by_group"):
        return []
    return [
        {"group_index": g["group_index"], "group": g["group"]}
        for g in section["by_group"]
        if not g["own"]
    ]


# ------------------------------------------------------------------------------------------------------ wording
def nearby_note(section: dict[str, Any]) -> str:
    if section["status"] == "empty":
        return "Qloo knows of no open places of this kind inside your radius."
    if section["mode"] == "near":
        eff = section["seed_effect"]
        said = "did not change" if eff is not None and eff < 0.2 else "changed only a little"
        if eff is None:
            return "Qloo gave no plain list to compare with, so these are places near you, not places matched to your crowd."
        return (
            f"Qloo's list {said} when it was given your crowd's taste, so these are places near you, "
            "not places matched to your crowd."
        )
    if section["told_apart"]:
        return "Qloo gave each group different places, so each group is listed on its own."
    return (
        "Qloo changed this list for your crowd's taste, but gave your groups mostly the same places, so they are listed "
        "for the crowd as a whole and no gap is claimed for one group."
    )


def elsewhere_note(section: dict[str, Any]) -> str:
    if section["status"] == "empty":
        return "Qloo knows of no open places of this kind further out."
    if section["mode"] == "near":
        return (
            "Qloo's wider list barely changed with your crowd's taste, so these are places in the wider area, "
            "not lookalikes of your venue."
        )
    return "Places further out that Qloo ties to your crowd's taste. Ideas to look at, not a measure of who goes there."
