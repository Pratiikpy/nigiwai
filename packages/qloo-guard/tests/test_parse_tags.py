"""How many of an entity's tags the Guard keeps, and which: an artist keeps the first ten as before; a place keeps only the tags that
say what it is, serves and feels like, up to twenty, and never the facilities or the descriptions of other people."""

from __future__ import annotations

from qloo_guard.parse import MAX_PLACE_TAGS, MAX_TAGS, PLACE_TASTE_NAMESPACES, parse_entity


def tag(namespace: str, value: str, name: str | None = None) -> dict[str, str]:
    return {
        "tag_id": f"urn:tag:{namespace}:qloo:{value}",
        "name": name or value.title(),
        "type": f"urn:tag:{namespace}:qloo",
    }


def place(tags: list[dict[str, str]]) -> dict[str, object]:
    return {
        "entity_id": "11111111-1111-4111-8111-111111111111",
        "name": "Corner Tap",
        "types": ["urn:entity:place"],
        "location": {"lat": 51.5, "lon": -0.12},
        "tags": tags,
    }


def test_a_place_keeps_its_taste_tags_and_never_a_facility_or_a_description_of_other_people() -> (
    None
):
    raw = place(
        [
            tag("payments", "visa"),
            tag("accessibility", "ramp"),
            tag("customer_identity", "lgbtq"),
            tag("inclusivity", "women_owned"),
            tag("dietary_option", "halal"),
            tag("age_range", "25_29"),
            tag("interests", "social_justice"),
            tag("neighborhood_characteristic", "walkable"),
            tag("ambience", "lively"),
            tag("decor", "industrial"),
            tag("category", "bar", "Bar"),
            tag("cuisine", "bar_food"),
        ]
    )
    entity = parse_entity(raw)
    assert entity is not None
    assert [t.tag_id.split(":")[2] for t in entity.tags] == [
        "ambience",
        "decor",
        "category",
        "cuisine",
    ]


def test_taste_tags_are_kept_in_order_even_when_facilities_come_first() -> None:
    """Qloo does not sort a place's tags by use: the first ten of a real place were facilities and context."""
    noise = [tag("amenity", f"a{i}") for i in range(30)]
    raw = place([*noise, tag("ambience", "cozy"), tag("menu_highlight", "ramen")])
    entity = parse_entity(raw)
    assert entity is not None and [t.name for t in entity.tags] == ["Cozy", "Ramen"]


def test_a_place_keeps_at_most_twenty_and_an_artist_ten_of_whatever_namespace() -> None:
    entity = parse_entity(place([tag("ambience", f"a{i}") for i in range(40)]))
    assert entity is not None and len(entity.tags) == MAX_PLACE_TAGS == 20
    artist = {
        "entity_id": "22222222-2222-4222-8222-222222222222",
        "name": "Lantern Hollow",
        "types": ["urn:entity:artist"],
        "tags": [
            tag("payments", f"p{i}") for i in range(15)
        ],  # an artist is not read through the place rule
    }
    got = parse_entity(artist)
    assert got is not None and len(got.tags) == MAX_TAGS == 10


def test_a_place_from_insights_is_recognised_by_its_subtype_and_filtered_the_same_way() -> None:
    raw = {
        "entity_id": "33333333-3333-4333-8333-333333333333",
        "name": "Corner Tap",
        "type": "urn:entity",
        "subtype": "urn:entity:place",
        "tags": [
            {"id": "urn:tag:payments:place:visa", "name": "Visa"},
            {"id": "urn:tag:genre:place:bar", "name": "Bar"},
        ],
    }
    entity = parse_entity(raw)
    assert entity is not None and [t.name for t in entity.tags] == ["Bar"]


def test_the_namespaces_are_the_ones_the_groups_engine_reads_a_place_through() -> None:
    assert {"genre", "category", "ambience", "decor"} <= PLACE_TASTE_NAMESPACES
    assert not PLACE_TASTE_NAMESPACES & {
        "payments",
        "customer_identity",
        "dietary_option",
        "inclusivity",
        "age_range",
        "interests",
        "setting",
    }


def test_a_cached_answer_holds_a_places_taste_tags_only_and_everything_else_exactly_as_qloo_sent_it() -> (
    None
):
    from qloo_guard.parse import minimise_places

    with_place = {
        "results": [
            place(
                [
                    tag("payments", "visa"),
                    tag("ambience", "lively"),
                    tag("customer_identity", "students"),
                ]
            ),
            {
                "entity_id": "x",
                "name": "Act",
                "types": ["urn:entity:artist"],
                "tags": [tag("payments", "p")],
            },
        ],
        "warnings": ["kept"],
    }
    out = minimise_places(with_place)
    assert [t["tag_id"].split(":")[2] for t in out["results"][0]["tags"]] == ["ambience"]
    assert out["results"][1] == with_place["results"][1] and out["warnings"] == ["kept"]
    assert len(with_place["results"][0]["tags"]) == 3  # the caller's copy is not edited in place
    # an insights answer: entities sit under results.entities, a place is told by its subtype, and its tags use `id`
    insights = {
        "success": True,
        "results": {
            "entities": [
                {
                    "entity_id": "y",
                    "name": "Bar",
                    "type": "urn:entity",
                    "subtype": "urn:entity:place",
                    "tags": [
                        {"id": "urn:tag:payments:place:visa", "name": "Visa"},
                        {"id": "urn:tag:genre:place:bar", "name": "Bar"},
                    ],
                }
            ]
        },
    }
    assert [t["name"] for t in minimise_places(insights)["results"]["entities"][0]["tags"]] == [
        "Bar"
    ]
    # a body that holds no place, or is not a body at all, comes back as it was
    plain = {
        "results": [
            {
                "entity_id": "z",
                "name": "Film",
                "types": ["urn:entity:movie"],
                "tags": [tag("payments", "p")],
            }
        ]
    }
    assert minimise_places(plain) is plain
    assert (
        minimise_places(None) is None
        and minimise_places([1, 2]) == [1, 2]
        and minimise_places({"results": "no"}) == {"results": "no"}
    )
