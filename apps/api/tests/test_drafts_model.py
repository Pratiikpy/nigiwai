"""Drafts: filled only from stored facts, every unknown a visible placeholder, nothing approvable until none is left. Every
name is invented."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
from nigiwai_api.services import drafts_model as dm

FACTS = dm.Facts(
    venue="The Lantern",
    area="12 Quill Street, Manchester",
    act="The Quiet Engines",
    slot="Friday evening",
    group="Indie rock acts",
    loves=("Velvet Harbour", "Paper Lungs", "Static Orchard", "Low Tide Club"),
    capacity=120,
    reward="a free coffee",
)
BARE = dm.Facts(
    venue="The Lantern", area=None, act="The Quiet Engines", slot=None, group=None, loves=()
)


def test_an_outreach_message_uses_only_what_is_stored_and_leaves_every_unknown_for_the_owner() -> (
    None
):
    d = dm.outreach(FACTS)
    assert d["kind"] == "outreach"
    assert d["subject"] == "Booking enquiry: The Quiet Engines at The Lantern"
    body = d["body"]
    assert "The Lantern (12 Quill Street, Manchester)" in body
    assert "booking The Quiet Engines for Friday evening" in body
    assert (
        "loves Velvet Harbour, Paper Lungs and Static Orchard" in body
    )  # three of the four, no more
    assert "Low Tide Club" not in body
    assert "The room holds about 120 people." in body
    # what the product cannot know is a gap, not a guess
    assert dm.placeholders(body) == [
        "[the booker's name]",
        "[Anything else you want to ask]",
        "[Your name]",
    ]
    assert "fee" in body  # it asks for the fee; it never names one


def test_with_little_known_the_message_says_less_instead_of_inventing() -> None:
    body = dm.outreach(BARE)["body"]
    assert "[the date you have in mind]" in body
    assert "loves" not in body
    assert "The room holds" not in body
    assert (
        "(" not in body.split("I run ")[1].split(".")[0]
    )  # no address, no brackets of an invented one
    assert "good fit" in body


def test_an_event_page_has_the_basics_with_gaps_for_date_tickets_and_the_acts_own_blurb() -> None:
    body = dm.event_page(FACTS)["body"]
    assert body.startswith("The Quiet Engines at The Lantern")
    assert "Where: The Lantern (12 Quill Street, Manchester)" in body
    assert "Scan the code on the table for a free coffee." in body
    assert dm.placeholders(body) == [
        "[Doors time]",
        "[Ticket price and link, or free entry]",
        "[One or two lines about the act, in your own words]",
    ]
    assert "Scan the code" not in dm.event_page(BARE)["body"]


def test_a_social_post_is_short_and_has_a_gap_for_how_to_come() -> None:
    d = dm.social_post(FACTS)
    assert (
        d["body"]
        == "The Quiet Engines at The Lantern, Friday evening. For anyone who loves Velvet Harbour and Paper Lungs. [Tickets or how to come]"
    )
    assert len(d["body"]) < 200


def test_ad_copy_stays_inside_the_usual_limits_even_with_long_names() -> None:
    long = dm.Facts(
        venue="The Extraordinarily Long Named Lantern Room",
        area=None,
        act="The Quiet Engines of Greater Manchester Orchestra",
        slot="Friday evening",
        group="Indie rock acts",
        loves=("An Exceptionally Long Item Name That Goes On", "Another Very Long Item Name Here"),
    )
    body = dm.ad_copy(long)["body"]
    headline = body.split("Headline (")[1].split("\n")[1]
    primary = body.split("Primary text (")[1].split("\n")[1]
    assert len(headline) <= dm.HEADLINE_MAX
    assert len(primary) <= dm.PRIMARY_MAX
    assert headline.endswith("…")
    assert f"({len(headline)} of {dm.HEADLINE_MAX} characters)" in body
    short = dm.ad_copy(FACTS)["body"]
    assert "For fans of Velvet Harbour" in short
    assert "Angle: Indie rock acts" in short
    assert dm.placeholders(short) == [
        "[What you want people to do, and the link]",
        "[The channel you choose; this draft is written for a short feed ad]",
    ]


def test_a_draft_that_needs_a_fact_it_does_not_have_is_refused_not_faked() -> None:
    with pytest.raises(ValueError, match="needs an act"):
        dm.outreach(dm.Facts(venue="V", area=None, act=None, slot=None, group=None, loves=()))
    with pytest.raises(ValueError, match="needs a group"):
        dm.ad_copy(BARE)
    with pytest.raises(ValueError, match="unknown kind"):
        dm.build("sms", FACTS)


def test_nothing_is_approvable_while_a_gap_is_left_and_everything_is_once_filled() -> None:
    body = dm.outreach(FACTS)["body"]
    why = dm.approvable(body)
    assert why is not None
    assert why.startswith("Fill in [the booker's name]")
    filled = (
        body.replace("[the booker's name]", "Sam")
        .replace("[Anything else you want to ask]", "Is a Sunday possible?")
        .replace("[Your name]", "Alex")
    )
    assert dm.approvable(filled) is None
    assert dm.approvable("   ") == "The draft is empty."
    assert dm.placeholders("[a] and [a] and [b]") == ["[a]", "[b]"]
    assert (
        dm.placeholders("a [multi\nline] gap") == []
    )  # a bracket that spans lines is not a placeholder


def test_the_mail_link_carries_the_draft_and_no_address() -> None:
    d = dm.outreach(FACTS)
    url = dm.mailto(d["subject"], d["body"])
    parsed = urlparse(url)
    assert parsed.scheme == "mailto"
    assert parsed.path == ""
    query = parse_qs(parsed.query)
    assert query["subject"] == [d["subject"]]
    assert query["body"] == [d["body"]]
