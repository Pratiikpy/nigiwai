"""Drafts the owner reviews before anything leaves the product (PRD M17, M10).

Plain templates filled only from what is stored: the venue's name and address, the act's name, the slot, the group's label
and the items its members picked. Nothing is invented and nothing is promised; every fact the product cannot know (a date, a
fee, a contact, the doors time) is a [bracketed placeholder] the owner must fill in, and a draft with a placeholder left in
it cannot be approved. The product never sends, posts or books anything: approval marks the text as the owner's own, and the
owner takes it from there (copy it, or open it in their own mail program).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

PLACEHOLDER = re.compile(r"\[[^\[\]\n]{1,80}\]")
KINDS = ("outreach", "event_page", "social_post", "ad_copy")
MAX_BODY = 4000
HEADLINE_MAX = 40  # the usual limit for a short ad headline
PRIMARY_MAX = 125  # and for the primary text that stays visible without "see more"


def placeholders(text: str) -> list[str]:
    """The [bracketed] gaps still to fill, in order, each once."""
    return list(dict.fromkeys(PLACEHOLDER.findall(text)))


@dataclass(frozen=True)
class Facts:
    """What a draft may say. Everything here comes from the owner's own records."""

    venue: str
    area: str | None  # the address as the owner gave it
    act: str | None
    slot: str | None  # "Friday evening", "Wednesday 14:00 to 17:00"
    group: str | None  # the label of the group the act fits best
    loves: tuple[str, ...]  # names of items that group's members picked, most picked first
    capacity: int | None = None
    reward: str | None = None  # what the survey gives guests, if the owner set one


def _names(items: tuple[str, ...], n: int) -> str:
    chosen = list(items[:n])
    if not chosen:
        return ""
    if len(chosen) == 1:
        return chosen[0]
    return ", ".join(chosen[:-1]) + " and " + chosen[-1]


def _where(f: Facts) -> str:
    return f"{f.venue}" + (f" ({f.area})" if f.area else "")


def outreach(f: Facts) -> dict[str, str]:
    """A first message to whoever books an act. The owner adds the contact, the date and their name."""
    if not f.act:
        raise ValueError("an outreach draft needs an act")
    when = f.slot or "[the date you have in mind]"
    fit = (
        f"The guests who scan at {f.venue} include a group that loves {_names(f.loves, 3)}, and {f.act} sits close to that taste."
        if f.loves
        else f"We read our guests' favourites to choose acts, and {f.act} came up as a good fit."
    )
    room = f" The room holds about {f.capacity} people." if f.capacity else ""
    body = (
        f"Hello [the booker's name],\n\n"
        f"I run {_where(f)}. We would like to talk about booking {f.act} for {when}.\n\n"
        f"{fit}{room}\n\n"
        f"Could you tell me whether {f.act} is available, and what you would need from us (fee, technical requirements, "
        f"the length of the set)? [Anything else you want to ask]\n\n"
        f"Thank you,\n[Your name]\n{f.venue}"
    )
    return {"kind": "outreach", "subject": f"Booking enquiry: {f.act} at {f.venue}", "body": body}


def event_page(f: Facts) -> dict[str, str]:
    if not f.act:
        raise ValueError("an event page draft needs an act")
    when = f.slot or "[Day and date]"
    loves = f" If you love {_names(f.loves, 3)}, this one is for you." if f.loves else ""
    body = (
        f"{f.act} at {f.venue}\n\n"
        f"When: {when}, doors [Doors time]\n"
        f"Where: {_where(f)}\n"
        f"Tickets: [Ticket price and link, or free entry]\n\n"
        f"{f.act} play {f.venue}.{loves}\n\n"
        f"[One or two lines about the act, in your own words]"
        + (f"\n\nScan the code on the table for {f.reward}." if f.reward else "")
    )
    return {"kind": "event_page", "subject": f"{f.act} at {f.venue}", "body": body}


def social_post(f: Facts) -> dict[str, str]:
    if not f.act:
        raise ValueError("a social post draft needs an act")
    when = f.slot or "[the date]"
    loves = f" For anyone who loves {_names(f.loves, 2)}." if f.loves else ""
    body = f"{f.act} at {f.venue}, {when}.{loves} [Tickets or how to come]"
    return {"kind": "social_post", "subject": f"Post: {f.act}", "body": body}


def _fit(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0].rstrip(",;:- ")
    return cut + "…"


def ad_copy(f: Facts) -> dict[str, str]:
    """An angle for one group: a hook from what its members picked, a headline and primary text within the usual limits,
    and the call to action left for the owner. Draft only; it says nothing about who the people are."""
    if not f.group or not f.loves:
        raise ValueError("an ad angle needs a group and what its members love")
    hook = _names(f.loves, 2)
    headline = _fit(f"For fans of {f.loves[0]}", HEADLINE_MAX)
    lead = f"{f.act} at {f.venue}" if f.act else f.venue
    primary = _fit(f"If you love {hook}, {lead}{', ' + f.slot if f.slot else ''}.", PRIMARY_MAX)
    body = (
        f"Angle: {f.group}\n"
        f"Hook: what this group picks most is {_names(f.loves, 4)}.\n\n"
        f"Headline ({len(headline)} of {HEADLINE_MAX} characters)\n{headline}\n\n"
        f"Primary text ({len(primary)} of {PRIMARY_MAX} characters)\n{primary}\n\n"
        f"Call to action\n[What you want people to do, and the link]\n\n"
        f"Where to run it\n[The channel you choose; this draft is written for a short feed ad]"
    )
    return {"kind": "ad_copy", "subject": f"Ad angle: {f.group}", "body": body}


BUILDERS = {
    "outreach": outreach,
    "event_page": event_page,
    "social_post": social_post,
    "ad_copy": ad_copy,
}


def build(kind: str, f: Facts) -> dict[str, str]:
    if kind not in BUILDERS:
        raise ValueError(f"unknown kind {kind}")
    return BUILDERS[kind](f)


def mailto(subject: str, body: str) -> str:
    """A link that opens the owner's own mail program with the draft in it; no address is filled in."""
    from urllib.parse import quote

    return f"mailto:?subject={quote(subject)}&body={quote(body)}"


def approvable(body: str) -> str | None:
    """None if the text can be approved, else why not."""
    left = placeholders(body)
    if left:
        shown = ", ".join(left[:3]) + ("…" if len(left) > 3 else "")
        return f"Fill in {shown} before approving."
    if not body.strip():
        return "The draft is empty."
    return None


def facts_json(f: Facts) -> dict[str, Any]:
    return {
        "venue": f.venue,
        "area": f.area,
        "act": f.act,
        "slot": f.slot,
        "group": f.group,
        "loves": list(f.loves),
        "capacity": f.capacity,
        "reward": f.reward,
    }
