"""What a place can say about taste, and which places are never offered as a favourite.

A guest may name a favourite place (PRD M3). Qloo describes a place with up to two hundred tags, and most of them are not taste: how to
pay, whether the entrance is level, which neighbourhood it sits in, who its owners are, how old its customers are. Some are worse than
not taste. Qloo tags a place with who its crowd is (`customer_identity`: "Lgbtq+", "Students", "Children"), who owns it, which diet it
serves (`dietary_option`: "Halal", "Kosher", "Celiac friendly") and the causes its crowd cares about (`interests`: "Social justice").
Counted as a guest's taste and grouped, those become claims about a person's religion, health, orientation or politics, which this product
never collects (the privacy page says so). So a place is read through an allowlist, not a blocklist: only what the place *is*, *serves* and
*feels like* counts, and a word that marks a protected category is dropped even from those. A place that is itself a proxy (a place of
worship, a clinic, a venue for one orientation, a party office, an adult venue) is not offered in the picker at all.

The lists were written from a real survey of Qloo's place tags (75 places across 15 kinds of place and 26 queries, 2026-10-25), by
namespace and by value, not from imagination. They are judgement, and they are narrow on purpose: a missed word leaves a tag in a group that
is only ever shown at ten guests or more, and the owner never sees one guest's picks.
"""

from __future__ import annotations

import re

PLACE_TYPE = "urn:entity:place"

# Namespaces (the third part of `urn:tag:<namespace>:...`) whose tags describe the place itself. Everything else is a facility
# (amenity, payments, accessibility, parking, offerings, service_options, dining_options), a context (neighborhood_characteristic,
# setting, nearby_attraction, planning, cost_description, time_of_day_fit, visit_intent, event, resy), a description of other people
# (customer_identity, age_range, inclusivity, children, pets) or a claim about diet or belief (dietary_option, interests).
PLACE_TASTE_NAMESPACES: frozenset[str] = frozenset(
    {
        "genre",  # the kind of place: Restaurant, Bar, Cafe, Jazz club
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

# Namespaces that name the kind of place, which is where a protected proxy shows ("Religious organization", "Medical clinic").
KIND_NAMESPACES: frozenset[str] = frozenset({"genre", "category"})

SENSITIVE = re.compile(
    r"\b(?:"
    r"religio\w*|church\w*|mosque\w*|masjid\w*|synagogue\w*|temple\w*|cathedral\w*|chapel\w*|monaster\w*|worship\w*|"
    r"christian\w*|muslim\w*|islam\w*|jewish|hindu\w*|buddhist\w*|sikh\w*|halal|kosher|"
    r"medical|clinic\w*|hospital\w*|doctor\w*|physician\w*|dentist\w*|dental|therap\w*|psychiatr\w*|psycholog\w*|counsel\w*|rehab\w*|"
    r"pharmac\w*|drug ?store|chemist|apothecar\w*|blood testing|health ?care|urgent care|mental health|abortion\w*|fertility|"
    r"lgbt\w*|gay|lesbian|queer|transgender|"
    r"political|politic\w*|party headquarters|campaign|government|courthouse|police|prison|jail|"
    r"adult entertainment|adult store|adult|erotic|strip club|escort\w*|sex\w*|"
    r"casino\w*|gambl\w*|betting|bail bonds?|payday|pawn\w*"
    r")\b",
    re.IGNORECASE,
)


# A few words are unambiguous in a place's own name and are read there too: a place that calls itself halal or kosher says so, and the
# word is a claim about religion whatever the place's listed kind is. Nothing wider is read in a name (the Churchill Theatre, Temple Bar
# and Pharmacy 2 Cafe are what their kinds say), because a name is not a kind and a match would refuse ordinary places.
NAME_SENSITIVE = re.compile(
    r"\b(?:halal\w*|kosher\w*|mosque\w*|masjid\w*|synagogue\w*|strip club|gentlemen'?s club|adult entertainment|abortion\w*)\b",
    re.IGNORECASE,
)


def namespace_of(tag_id: str) -> str:
    """`urn:tag:ambience:qloo:lively` -> `ambience`. A tag id in another shape has no namespace and is never kept for a place."""
    parts = tag_id.split(":")
    return parts[2] if len(parts) > 3 and parts[0] == "urn" and parts[1] == "tag" else ""


def is_place(entity_type: str) -> bool:
    return entity_type == PLACE_TYPE or entity_type.startswith(PLACE_TYPE + ":")


def keeps_for_taste(tag_id: str, name: str) -> bool:
    """Whether one tag of a place may count as taste: an allowed namespace, and no word that marks a protected category."""
    return namespace_of(tag_id) in PLACE_TASTE_NAMESPACES and not SENSITIVE.search(name)


def sensitive_place(name: str, tags: list[tuple[str, str]]) -> str | None:
    """The word that makes a place a proxy for something never collected, from its kind (see `sensitive_kind`) or, for a few words that
    are unambiguous there, from its name; None for an ordinary place."""
    found = sensitive_kind(tags)
    if found:
        return found
    named = NAME_SENSITIVE.search(name)
    return named.group(0).lower() if named else None


def sensitive_kind(tags: list[tuple[str, str]]) -> str | None:
    """For a place's (tag id, tag name) pairs: the word that makes the place a proxy for something never collected, or None.
    Only the kind of place counts (its category and genre) and what it serves (cuisine): a bar called Temple Bar is a bar."""
    for tag_id, name in tags:
        if namespace_of(tag_id) in KIND_NAMESPACES | {"cuisine"}:
            found = SENSITIVE.search(name)
            if found:
                return found.group(0).lower()
    return None
