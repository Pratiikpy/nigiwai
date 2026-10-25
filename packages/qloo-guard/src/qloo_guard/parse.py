"""Turn raw Qloo JSON into the trimmed models (rule G29). Every field access is defensive: Qloo returns
different shapes from /search, /entities and /v2/insights, and a missing field is normal, not an error."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from .models import (
    CompareResult,
    DemographicsItem,
    Entity,
    EntityTag,
    GeoPoint,
    QlooWarning,
    Tag,
    nfc,
)

MAX_TAGS = 10
MAX_PLACE_TAGS = 20
MAX_DESCRIPTION = 160

# Qloo lists a busy place with 85 to 200 tags (probed live, 2026-10-25), and the first ten are mostly not taste: how to pay, whether the
# entrance is level, the neighbourhood. Some describe other people: who the customers are ("Lgbtq+", "Students"), who owns the place,
# which diet it serves ("Halal", "Celiac friendly"), the causes its crowd cares about. A place keeps only the tags that say what it is,
# what it serves and how it feels, up to twenty, and the rest are never stored: nothing reads them, and holding them would be holding
# claims about people for no use. This is the same set the groups engine reads a place through (`nigiwai_tribes.places`); a test in the
# API keeps the two equal.
PLACE_TASTE_NAMESPACES: frozenset[str] = frozenset(
    {
        "genre",
        "category",
        "cuisine",
        "culinary_style",
        "menu_highlight",
        "beverage_offering",
        "specialty_dish",
        "ambience",
        "decor",
        "activity_type",
    }
)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _first(value: Any) -> dict[str, Any]:
    """Outside ids arrive as a dict on /search and as a list of dicts on insights."""
    if isinstance(value, list) and value:
        value = value[0]
    return value if isinstance(value, dict) else {}


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _geo(raw: Any) -> GeoPoint | None:
    if (
        isinstance(raw, dict)
        and isinstance(raw.get("lat"), int | float)
        and isinstance(raw.get("lon"), int | float)
    ):
        try:
            return GeoPoint(lat=round(float(raw["lat"]), 4), lon=round(float(raw["lon"]), 4))
        except ValidationError:
            return None
    return None


def _namespace(tag_id: str) -> str:
    """`urn:tag:ambience:qloo:lively` -> `ambience`; a tag id in any other shape has no namespace."""
    parts = tag_id.split(":")
    return parts[2] if len(parts) > 3 and parts[0] == "urn" and parts[1] == "tag" else ""


def _is_place(entity: dict[str, Any]) -> bool:
    kinds = [*(entity.get("types") or []), entity.get("subtype"), entity.get("type")]
    return any(isinstance(k, str) and k.startswith("urn:entity:place") for k in kinds)


def minimise_places(body: Any) -> Any:
    """The same rule as `_tags`, applied to a whole Qloo answer before it is cached: a place keeps only its taste tags. The private cache
    holds the answer as Qloo sent it, so without this it would hold, for every place searched, the customers, owners and diets Qloo
    lists for it, which the product never reads and never shows. Anything that is not a place is returned untouched."""
    if not isinstance(body, dict):
        return body
    results = body.get("results")
    if isinstance(results, list):
        entities = results
    elif isinstance(results, dict) and isinstance(results.get("entities"), list):
        entities = results["entities"]
    else:
        return body
    changed = False
    cleaned: list[Any] = []
    for entity in entities:
        if isinstance(entity, dict) and _is_place(entity) and isinstance(entity.get("tags"), list):
            kept = [
                t
                for t in entity["tags"]
                if isinstance(t, dict)
                and _namespace(str(t.get("tag_id") or t.get("id") or "")) in PLACE_TASTE_NAMESPACES
            ][:MAX_PLACE_TAGS]
            if len(kept) != len(entity["tags"]):
                entity = {**entity, "tags": kept}
                changed = True
        cleaned.append(entity)
    if not changed:
        return body
    return {
        **body,
        "results": cleaned if isinstance(results, list) else {**results, "entities": cleaned},
    }


def _tags(raw: Any, *, place: bool = False) -> tuple[EntityTag, ...]:
    out: list[EntityTag] = []
    cap = MAX_PLACE_TAGS if place else MAX_TAGS
    if isinstance(raw, list):
        for t in raw:
            if not isinstance(t, dict):
                continue
            tag_id = t.get("tag_id") or t.get("id")  # search uses tag_id, insights uses id
            name = t.get("name")
            if isinstance(tag_id, str) and isinstance(name, str):
                if place and _namespace(tag_id) not in PLACE_TASTE_NAMESPACES:
                    continue
                out.append(
                    EntityTag(
                        tag_id=tag_id,
                        name=nfc(name),
                        type=t.get("type") if isinstance(t.get("type"), str) else None,
                    )
                )
            if len(out) >= cap:
                break
    return tuple(out)


def _explain(query: dict[str, Any]) -> dict[str, float]:
    ex = query.get("explainability")
    items = ex.get("signal.interests.entities") if isinstance(ex, dict) else None
    out: dict[str, float] = {}
    for it in items or []:
        if (
            isinstance(it, dict)
            and isinstance(it.get("entity_id"), str)
            and isinstance(it.get("score"), int | float)
        ):
            out[it["entity_id"]] = float(it["score"])
    return out


def parse_entity(raw: dict[str, Any]) -> Entity | None:
    entity_id = raw.get("entity_id")
    name = raw.get("name")
    if not isinstance(entity_id, str) or not isinstance(name, str):
        return None
    types = tuple(t for t in (raw.get("types") or []) if isinstance(t, str))
    if not types:
        # /v2/insights entities carry type "urn:entity" and the real type in `subtype` (verified live 2026-10-23).
        specific = raw.get("subtype") if isinstance(raw.get("subtype"), str) else raw.get("type")
        if isinstance(specific, str):
            types = (specific,)
    props: dict[str, Any] = _dict(raw.get("properties"))
    query: dict[str, Any] = _dict(raw.get("query"))

    external: dict[str, Any] = {}
    for source in (props.get("external"), raw.get("external")):
        if isinstance(source, dict):
            external.update(source)

    description = props.get("short_description") or props.get("description")
    description = nfc(description)[:MAX_DESCRIPTION] if isinstance(description, str) else None

    image = _first(props.get("image")).get("url") or _first(props.get("images")).get("url")

    year = _int(props.get("release_year")) or _int(props.get("publication_year"))
    lastfm = _first(external.get("lastfm"))
    try:
        return Entity(
            entity_id=entity_id,
            name=nfc(name),
            types=types,
            subtype=raw.get("subtype") if isinstance(raw.get("subtype"), str) else None,
            popularity=float(raw["popularity"])
            if isinstance(raw.get("popularity"), int | float)
            else None,
            tags=_tags(raw.get("tags"), place=any(t.startswith("urn:entity:place") for t in types)),
            description=description,
            image_url=image if isinstance(image, str) else None,
            location=_geo(raw.get("location")),
            address=nfc(props["address"]) if isinstance(props.get("address"), str) else None,
            price_level=_int(props.get("price_level")),
            is_closed=props.get("is_closed") if isinstance(props.get("is_closed"), bool) else None,
            distance_m=float(query["distance"])
            if isinstance(query.get("distance"), int | float)
            else None,
            neighborhood=nfc(props["neighborhood"])
            if isinstance(props.get("neighborhood"), str)
            else None,
            affinity=float(query["affinity"])
            if isinstance(query.get("affinity"), int | float)
            else None,
            explain=_explain(query),
            release_year=year,
            musicbrainz_id=_first(external.get("musicbrainz")).get("id")
            if isinstance(_first(external.get("musicbrainz")).get("id"), str)
            else None,
            spotify_id=_first(external.get("spotify")).get("id")
            if isinstance(_first(external.get("spotify")).get("id"), str)
            else None,
            lastfm_listeners=_int(lastfm.get("listeners")),
        )
    except ValidationError:
        return None


def parse_entities(raw: Any) -> list[Entity]:
    items = raw if isinstance(raw, list) else []
    out: list[Entity] = []
    for item in items:
        if isinstance(item, dict):
            ent = parse_entity(item)
            if ent is not None:
                out.append(ent)
    return out


def entities_from_body(path: str, body: Any) -> list[Entity]:
    """Pull the entity list out of a /search, /entities or /v2/insights body."""
    if not isinstance(body, dict):
        return []
    results = body.get("results")
    if isinstance(results, list):  # /search, /entities
        return parse_entities(results)
    if isinstance(results, dict) and isinstance(results.get("entities"), list):  # /v2/insights
        return parse_entities(results["entities"])
    return []


def parse_warnings(body: Any) -> list[QlooWarning]:
    if not isinstance(body, dict):
        return []
    raw = body.get("warnings")
    if raw is None and isinstance(body.get("results"), dict):
        raw = body["results"].get("warnings")
    out: list[QlooWarning] = []
    if isinstance(raw, list):
        for w in raw:
            if isinstance(w, dict):
                out.append(
                    QlooWarning(
                        type=str(w.get("type", "unknown")),
                        raw={k: v for k, v in w.items() if k != "type"},
                    )
                )
    return out


def parse_tags(body: Any) -> list[Tag]:
    results = body.get("results") if isinstance(body, dict) else None
    raw = results.get("tags") if isinstance(results, dict) else None
    out: list[Tag] = []
    for t in raw or []:
        if not isinstance(t, dict):
            continue
        tag_id = t.get("id") or t.get("tag_id")
        name = t.get("name")
        if isinstance(tag_id, str) and isinstance(name, str):
            pop = t.get("popularity")
            out.append(
                Tag(
                    tag_id=tag_id,
                    name=nfc(name),
                    type=t.get("type") if isinstance(t.get("type"), str) else None,
                    popularity=float(pop) if isinstance(pop, int | float) else None,
                )
            )
    return out


def parse_compare(body: Any) -> CompareResult:
    results = body.get("results") if isinstance(body, dict) else None
    results = results if isinstance(results, dict) else {}

    def tags(key: str) -> tuple[Tag, ...]:
        out: list[Tag] = []
        for t in results.get(key) or []:
            if (
                isinstance(t, dict)
                and isinstance(t.get("tag_id"), str)
                and isinstance(t.get("name"), str)
            ):
                pop = t.get("popularity")
                out.append(
                    Tag(
                        tag_id=t["tag_id"],
                        name=nfc(t["name"]),
                        type=t.get("subtype") if isinstance(t.get("subtype"), str) else None,
                        popularity=float(pop) if isinstance(pop, int | float) else None,
                    )
                )
        return tuple(out)

    return CompareResult(shared_tags=tags("tags"), a_tags=tags("a"), b_tags=tags("b"))


def parse_demographics(body: Any) -> list[DemographicsItem]:
    results = body.get("results") if isinstance(body, dict) else None
    raw = results.get("demographics") if isinstance(results, dict) else None
    out: list[DemographicsItem] = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        q: dict[str, Any] = _dict(item.get("query"))
        age: dict[str, Any] = _dict(q.get("age"))
        gender: dict[str, Any] = _dict(q.get("gender"))
        if isinstance(item.get("entity_id"), str) and age and gender:
            out.append(
                DemographicsItem(
                    entity_id=item["entity_id"],
                    age={k: float(v) for k, v in age.items() if isinstance(v, int | float)},
                    gender={k: float(v) for k, v in gender.items() if isinstance(v, int | float)},
                )
            )
    return out
