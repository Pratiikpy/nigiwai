"""Places as picks: which of a place's tags may count as taste, and which places are never offered. Every name is invented; the tag
namespaces and the kinds of word are the real ones Qloo uses (a survey of its place tags, 2026-10-25)."""

from __future__ import annotations

import pytest
from nigiwai_tribes import Pick, Tag, TribesConfig, sensitive_kind, sensitive_place
from nigiwai_tribes.build import usable_tags
from nigiwai_tribes.places import PLACE_TASTE_NAMESPACES, keeps_for_taste, namespace_of

PLACE = "urn:entity:place"
CFG = TribesConfig()


def tag(namespace: str, name: str, source: str = "qloo") -> Tag:
    return Tag(
        f"urn:tag:{namespace}:{source}:{name.lower().replace(' ', '_')}",
        name,
        f"urn:tag:{namespace}:{source}",
    )


def test_the_namespace_is_the_third_part_of_a_tag_id() -> None:
    assert namespace_of("urn:tag:ambience:qloo:lively") == "ambience"
    assert namespace_of("urn:tag:genre:place:restaurant") == "genre"
    assert namespace_of("urn:tag:resy:keyword:place:book") == "resy"
    assert namespace_of("not-a-tag") == "" and namespace_of("urn:tag:x") == ""


@pytest.mark.parametrize(
    ("namespace", "name"),
    [
        ("ambience", "Lively"),
        ("decor", "Industrial chic"),
        ("cuisine", "Moroccan"),
        ("culinary_style", "Gastropub"),
        ("menu_highlight", "Spicy miso ramen"),
        ("beverage_offering", "Craft beer"),
        ("specialty_dish", "Kebab"),
        ("genre", "Cocktail bar"),
        ("category", "Wine bar"),
        ("activity_type", "Live music"),
    ],
)
def test_what_a_place_is_serves_and_feels_like_counts_as_taste(namespace: str, name: str) -> None:
    assert keeps_for_taste(tag(namespace, name).tag_id, name)


@pytest.mark.parametrize(
    ("namespace", "name", "why"),
    [
        ("payments", "Visa", "how to pay"),
        ("credit_card", "Mastercard", "how to pay"),
        ("amenity", "Wifi", "a facility"),
        ("amenities", "Parking", "a facility"),
        ("accessibility", "Wheelchair accessible entrance", "a facility"),
        ("parking", "Street parking", "a facility"),
        ("offerings", "Delivery", "a service"),
        ("service_options", "Takeout", "a service"),
        ("dining_options", "Dine in", "a service"),
        ("planning", "Reservations required", "a service"),
        ("cost_description", "Moderately expensive", "a price, not a taste"),
        ("neighborhood_characteristic", "Walkable", "the area, not the place"),
        ("setting", "Midtown manhattan", "where it is, which would group guests by geography"),
        ("nearby_attraction", "Near the park", "the area"),
        ("time_of_day_fit", "Afternoon", "a time"),
        ("visit_intent", "Special occasion", "a reason for a visit"),
        ("event", "Anniversary", "a moment in someone's life"),
        ("resy", "Book tonight", "a booking service"),
        ("customer_identity", "Students", "describes other people"),
        ("customer_identity", "Lgbtq+", "describes other people and a protected category"),
        ("age_range", "25 29", "describes other people"),
        ("inclusivity", "Identifies as women owned", "describes the owners"),
        ("children", "Good for kids", "describes other people"),
        ("pets", "Dogs allowed", "describes other people"),
        ("dietary_option", "Halal", "a claim about diet or belief"),
        ("dietary_option", "Celiac friendly", "a claim about health"),
        ("interests", "Social justice", "a claim about politics"),
        ("not_for_display", "Anything", "Qloo says not to show it"),
    ],
)
def test_facilities_contexts_and_descriptions_of_other_people_never_count_as_taste(
    namespace: str, name: str, why: str
) -> None:
    assert not keeps_for_taste(tag(namespace, name).tag_id, name), why


@pytest.mark.parametrize(
    ("namespace", "name"),
    [
        ("cuisine", "Halal"),
        ("cuisine", "Kosher"),
        ("genre", "Halal restaurant"),
        ("category", "Gay bar"),
        ("ambience", "Lgbtq+ friendly"),
        ("menu_highlight", "Sexual health clinic special"),
    ],
)
def test_a_word_that_marks_a_protected_category_is_dropped_even_in_an_allowed_namespace(
    namespace: str, name: str
) -> None:
    assert namespace in PLACE_TASTE_NAMESPACES
    assert not keeps_for_taste(tag(namespace, name).tag_id, name)


def test_a_place_pick_keeps_only_its_taste_tags_and_an_artist_pick_is_read_as_before() -> None:
    place = Pick(
        "p1",
        PLACE,
        "Corner Tap",
        (
            tag("ambience", "Lively"),
            tag("decor", "Industrial"),
            tag("cuisine", "Bar food"),
            tag("payments", "Visa"),
            tag("amenity", "Wifi"),
            tag("customer_identity", "Students"),
            tag("dietary_option", "Halal"),
            tag("neighborhood_characteristic", "Walkable"),
        ),
    )
    assert {name for name, _ in usable_tags(place, CFG).values()} == {
        "Lively",
        "Industrial",
        "Bar food",
    }
    # the same namespace names mean something else on an artist, and the artist rule is untouched
    artist = Pick(
        "a1",
        "urn:entity:artist",
        "Lantern Hollow",
        (tag("genre", "Shoegaze"), tag("audience", "Young adults"), tag("amenity", "x")),
    )
    assert {name for name, _ in usable_tags(artist, CFG).values()} == {"Shoegaze", "Young adults"}


def test_a_place_with_only_facility_tags_carries_no_signal() -> None:
    bare = Pick("p2", PLACE, "Anywhere", (tag("payments", "Visa"), tag("accessibility", "Ramp")))
    assert usable_tags(bare, CFG) == {}


def test_a_place_type_with_a_subtype_is_still_a_place() -> None:
    sub = Pick(
        "p3",
        "urn:entity:place:restaurant",
        "Noodle Shop",
        (tag("cuisine", "Ramen"), tag("payments", "Visa")),
    )
    assert {name for name, _ in usable_tags(sub, CFG).values()} == {"Ramen"}


@pytest.mark.parametrize(
    ("kind", "word"),
    [
        ("Religious organization", "religio"),
        ("Church", "church"),
        ("Mosque", "mosque"),
        ("Synagogue", "synagogue"),
        ("Hindu temple", "hindu"),
        ("Medical clinic", "medical"),
        ("Pharmacy", "pharmac"),
        ("Mental health service", "mental health"),
        ("Gay bar", "gay"),
        ("Lgbtq+ bar", "lgbt"),
        ("Political party office", "political"),
        ("Government office", "government"),
        ("Adult entertainment club", "adult entertainment"),
        ("Casino", "casino"),
        ("Halal restaurant", "halal"),
        ("Kosher restaurant", "kosher"),
    ],
)
def test_a_place_that_is_a_proxy_for_something_never_collected_is_recognised_by_its_kind(
    kind: str, word: str
) -> None:
    found = sensitive_kind(
        [("urn:tag:genre:place:x", "Place"), (tag("category", kind).tag_id, kind)]
    )
    assert found is not None and found.startswith(word)


@pytest.mark.parametrize(
    "kind",
    [
        "Bar",
        "Cafe",
        "Restaurant",
        "Jazz club",
        "Live music venue",
        "Book store",
        "Hotel",
        "Wine bar",
        "Brewery",
        "Cinema",
        "Bakery",
        "Museum",
        "Yoga studio",
        "Ramen restaurant",
        "Vegan restaurant",
        "Sports bar",
    ],
)
def test_ordinary_places_are_not_flagged(kind: str) -> None:
    assert (
        sensitive_kind([(tag("category", kind).tag_id, kind), (tag("genre", kind).tag_id, kind)])
        is None
    )


def test_only_the_kind_of_place_counts_so_a_bar_called_temple_bar_is_a_bar() -> None:
    # the name is not a tag; and a tag that is not about the kind of place is not read for this
    assert (
        sensitive_kind(
            [
                (tag("category", "Bar").tag_id, "Bar"),
                (tag("ambience", "Historic").tag_id, "Historic"),
            ]
        )
        is None
    )
    assert (
        sensitive_kind([(tag("interests", "Religious studies").tag_id, "Religious studies")])
        is None
    )  # dropped as taste, not a kind
    assert sensitive_kind([]) is None


@pytest.mark.parametrize(
    "kind",
    [
        "Pharmacy",
        "Drug store",
        "Chemist",
        "Apothecary",
        "Homeopathic pharmacy",
        "Blood testing service",
        "Travel clinic",
    ],
)
def test_places_that_dispense_or_test_for_health_are_recognised_by_their_kind(kind: str) -> None:
    assert sensitive_kind([(tag("category", kind).tag_id, kind)]) is not None


@pytest.mark.parametrize(
    "name",
    [
        "Karwoo Halal",
        "halalo.co.uk",
        "KosherMart",
        "Kosher Deli Golders Green",
        "Masjid Al Noor Cafe",
        "Gentlemen's Club Soho",
        "Mosque Street Kitchen",
    ],
)
def test_a_word_that_is_a_claim_in_a_places_own_name_is_read_there_too(name: str) -> None:
    assert sensitive_place(name, [(tag("category", "Restaurant").tag_id, "Restaurant")]) is not None


@pytest.mark.parametrize(
    "name",
    [
        "Churchill Theatre",
        "Temple Bar",
        "Church Street Hotel",
        "Pharmacy 2 Cafe",
        "The Hospital Club",
        "Clinic",
        "Cathedral Quarter Bar",
        "Party Hall",
    ],
)
def test_an_ordinary_place_with_a_borrowed_word_in_its_name_is_not_refused(name: str) -> None:
    assert sensitive_place(name, [(tag("category", "Bar").tag_id, "Bar")]) is None
