"""Post-rules (ARCHITECTURE 3.2 and 3.3): clean a parsed result and say what was done and why."""

from __future__ import annotations

from dataclasses import dataclass, field

from .encoding import looks_like_mojibake
from .models import Entity, EntityType, GeoPoint, GuardStatus, QlooWarning, RuleEvent, norm_name
from .requests import LEAKAGE_TAG_FRAGMENTS, PlaceInsights, _InsightsBase

FLAT_EPSILON = 1e-6
RADIUS_SLACK = 1.02  # Qloo rounds distances; allow 2% before calling a place outside the area
DUPLICATE_PLACE_M = 150.0  # same-named places closer than this are one place


@dataclass
class PostResult:
    items: list[Entity]
    events: list[RuleEvent] = field(default_factory=list)
    status: GuardStatus = "ok"
    dropped_seed_ids: tuple[str, ...] = ()


def _event(rule: str, effect: str, detail: str, count: int = 1) -> RuleEvent:
    return RuleEvent(rule=rule, stage="post", effect=effect, detail=detail, count=count)  # type: ignore[arg-type]


def _same_item(a: GeoPoint | None, b: GeoPoint | None) -> bool:
    """Two entities with one name are one item unless both have a position and the positions are far apart."""
    if a is None or b is None:
        return True
    return a.distance_m(b) <= DUPLICATE_PLACE_M


def dedupe(items: list[Entity], exclude_ids: set[str]) -> tuple[list[Entity], list[RuleEvent]]:
    """Trap 18: dedupe by id, then by NFC-casefolded name plus subtype; seeds never appear in their own results."""
    seen_ids: set[str] = set()
    seen_names: dict[tuple[str, str], list[GeoPoint | None]] = {}
    out: list[Entity] = []
    removed_seed = removed_id = removed_name = 0
    for e in items:
        if e.entity_id in exclude_ids:
            removed_seed += 1
            continue
        if e.entity_id in seen_ids:
            removed_id += 1
            continue
        key = (norm_name(e.name), e.subtype or e.primary_type)
        earlier = seen_names.get(key, [])
        # The same name is the same item, except for a place: two bars called the same in different cities are two
        # places, and only ones within DUPLICATE_PLACE_M of each other are one.
        if any(_same_item(e.location, other) for other in earlier):
            removed_name += 1
            continue
        seen_ids.add(e.entity_id)
        seen_names.setdefault(key, []).append(e.location)
        out.append(e)
    events: list[RuleEvent] = []
    if removed_seed:
        events.append(
            _event(
                "T18-seed",
                "dropped",
                "seed or excluded entity removed from its own results",
                removed_seed,
            )
        )
    if removed_id:
        events.append(_event("T18-id", "dropped", "duplicate entity id", removed_id))
    if removed_name:
        events.append(_event("T18-name", "dropped", "duplicate name and subtype", removed_name))
    return out, events


def keep_requested_type(
    items: list[Entity], wanted: EntityType
) -> tuple[list[Entity], list[RuleEvent]]:
    """Subtype must equal the requested type (trap 18: entity conflation)."""
    out = [
        e for e in items if not e.types or e.primary_type == wanted.value or wanted.value in e.types
    ]
    removed = len(items) - len(out)
    return out, (
        [_event("T18-type", "dropped", f"not a {wanted.value}", removed)] if removed else []
    )


def in_area(items: list[Entity], req: PlaceInsights) -> tuple[list[Entity], list[RuleEvent]]:
    """Trap 9 and 17: every place must lie inside the requested area. Containment is computed, not trusted."""
    out: list[Entity] = []
    removed = unverifiable = 0
    limit = req.area.radius_m * RADIUS_SLACK
    for e in items:
        if e.distance_m is not None:
            dist = e.distance_m
        elif e.location is not None:
            dist = req.area.center.distance_m(e.location)
        else:
            unverifiable += 1
            continue
        if dist <= limit:
            out.append(e)
        else:
            removed += 1
    events: list[RuleEvent] = []
    if removed:
        events.append(_event("T17-area", "dropped", "outside the requested area", removed))
    if unverifiable:
        events.append(
            _event(
                "T17-unverifiable", "dropped", "no coordinates or distance to check", unverifiable
            )
        )
    return out, events


def drop_category_leakage(
    items: list[Entity], req: PlaceInsights
) -> tuple[list[Entity], list[RuleEvent]]:
    """Rule G26: hotels, malls and arenas leak into bar lists; drop them by tag."""
    if req.category is None:
        return items, []
    fragments = LEAKAGE_TAG_FRAGMENTS.get(req.category, ())
    if not fragments:
        return items, []
    out: list[Entity] = []
    removed = 0
    for e in items:
        blob = " ".join(t.tag_id.lower() for t in e.tags)
        if any(f in blob for f in fragments):
            removed += 1
        else:
            out.append(e)
    return out, (
        [_event("G26", "dropped", f"wrong category for {req.category.name.lower()}", removed)]
        if removed
        else []
    )


def flag_mojibake(items: list[Entity]) -> list[RuleEvent]:
    bad = sum(1 for e in items if looks_like_mojibake(e.name))
    return (
        [_event("G-encoding", "flagged", "name looks like mis-decoded UTF-8", bad)] if bad else []
    )


def flat_affinity(items: list[Entity]) -> bool:
    """Trap 7: a wrong-namespace tag gives a flat affinity (0.765 on every item)."""
    scores = [e.affinity for e in items if e.affinity is not None]
    return len(scores) >= 3 and (max(scores) - min(scores)) < FLAT_EPSILON


def apply_insights_post(
    req: _InsightsBase,
    items: list[Entity],
    warnings: list[QlooWarning],
) -> PostResult:
    exclude = set(req.signal_entities) | set(req.exclude_entities)
    events: list[RuleEvent] = []
    status: GuardStatus = "ok"

    items, ev = keep_requested_type(items, req.entity_type)
    events += ev
    items, ev = dedupe(items, exclude)
    events += ev
    if isinstance(req, PlaceInsights):
        items, ev = in_area(items, req)
        events += ev
        items, ev = drop_category_leakage(items, req)
        events += ev
    events += flag_mojibake(items)

    dropped: tuple[str, ...] = ()
    seeds = set(req.signal_entities)
    for w in warnings:
        if w.type == "not_found":
            ids = tuple(i for i in w.entity_ids() if i in seeds)
            if ids:
                dropped += ids
                events.append(
                    _event(
                        "T12-dropped-seed",
                        "flagged",
                        "Qloo dropped a seed; explainability is not trustworthy",
                        len(ids),
                    )
                )
                status = "degraded"
        else:
            events.append(_event("G25-warning", "info", f"warning type {w.type}"))

    if flat_affinity(items):
        events.append(
            _event("T7-flat-affinity", "flagged", "all affinities equal: the signal is ineffective")
        )
        status = "degraded"

    items = items[: req.take]
    if not items:
        status = "empty" if status == "ok" else status
        if req.filter_tags:
            events.append(
                _event(
                    "T7-zero-with-tags", "flagged", "tag filter returned nothing: wrong namespace?"
                )
            )
    return PostResult(items=items, events=events, status=status, dropped_seed_ids=dropped)
