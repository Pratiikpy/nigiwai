"""Drafts through the backend: made only from an accepted Today action or a real group, filled only from stored facts, never
approvable with a gap left, and every step in the audit log. Nothing is sent. Qloo is scripted; every name is invented."""

from __future__ import annotations

from typing import Any

import psycopg
from harness import World, make_venue, sign_up
from nigiwai_api.services import drafts_model as dm
from test_soundcheck import base
from test_today import full_board


async def accept_first(owner: Any, venue: Any, doc: dict[str, Any]) -> dict[str, Any]:
    fill = doc["actions"][0]
    res = await owner.client.put(
        owner.url(f"{base(owner, venue)}/today/actions/{fill['key']}"),
        json={"state": "accepted"},
        headers=owner.headers,
    )
    assert res.status_code == 200, res.text
    out: dict[str, Any] = fill
    return out


async def listing(owner: Any, venue: Any) -> dict[str, Any]:
    res = await owner.get(f"{base(owner, venue)}/drafts")
    assert res.status_code == 200, res.text
    out: dict[str, Any] = res.json()
    return out


def fill_in(body: str) -> str:
    for gap in dm.placeholders(body):
        body = body.replace(gap, "filled")
    return body


async def test_drafts_come_only_from_an_accepted_action_and_say_only_what_is_stored(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    doc = await full_board(world, admin, owner, venue)
    fill = doc["actions"][0]
    url = f"{base(owner, venue)}/drafts"

    before = await listing(owner, venue)
    assert before["drafts"] == []
    assert before["sources"]["actions"] == []  # nothing is accepted yet
    assert len(before["sources"]["groups"]) >= 2
    early = await owner.post(url, json={"from_action": fill["key"]})
    assert early.status_code == 409
    assert "Accept the action on Today first" in early.json()["detail"]

    await accept_first(owner, venue, doc)
    sources = (await listing(owner, venue))["sources"]
    assert [a["key"] for a in sources["actions"]] == [fill["key"]]
    made = await owner.post(url, json={"from_action": fill["key"]})
    assert made.status_code == 201, made.text
    assert len(made.json()["ids"]) == 3

    drafts = (await listing(owner, venue))["drafts"]
    assert sorted(d["kind"] for d in drafts) == ["event_page", "outreach", "social_post"]
    by_kind = {d["kind"]: d for d in drafts}
    act = fill["act"]["name"]
    outreach = by_kind["outreach"]
    assert outreach["status"] == "draft"
    assert act in outreach["subject"] and "The Lantern" in outreach["subject"]
    assert "Wednesday 14:00 to 17:00" in outreach["body"]  # the slot the action was about
    assert outreach["facts"]["act"] == act
    assert outreach["facts"]["venue"] == "The Lantern"
    assert outreach["facts"]["slot"] == "Wednesday 14:00 to 17:00"
    assert outreach["gaps"] == [
        "[the booker's name]",
        "[Anything else you want to ask]",
        "[Your name]",
    ]
    assert outreach["can_approve"] is False
    assert outreach["why_not"].startswith("Fill in [the booker's name]")
    assert outreach["mailto"] is None  # only an approved draft can be opened in a mail program
    assert outreach["source_key"] == fill["key"]
    # nothing was drafted that the venue's records do not support: no invented capacity, no fee
    assert "The room holds" not in outreach["body"]
    assert "€" not in outreach["body"] and "$" not in outreach["body"]


async def test_a_draft_is_approved_only_when_no_gap_is_left_and_editing_takes_the_approval_back(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    doc = await full_board(world, admin, owner, venue)
    fill = await accept_first(owner, venue, doc)
    await owner.post(f"{base(owner, venue)}/drafts", json={"from_action": fill["key"]})
    outreach = next(d for d in (await listing(owner, venue))["drafts"] if d["kind"] == "outreach")
    root = f"{base(owner, venue)}/drafts/{outreach['id']}"

    refused = await owner.post(f"{root}/approve")
    assert refused.status_code == 409
    assert "Fill in" in refused.json()["detail"]

    edited = await owner.put(
        root, json={"subject": outreach["subject"], "body": fill_in(outreach["body"])}
    )
    assert edited.status_code == 200
    assert edited.json()["gaps"] == []
    assert edited.json()["can_approve"] is True
    approved = await owner.post(f"{root}/approve")
    assert approved.status_code == 200, approved.text
    doc2 = approved.json()
    assert doc2["status"] == "approved"
    assert doc2["decided_at"]
    assert doc2["mailto"].startswith("mailto:?subject=")
    assert "filled" in doc2["mailto"]
    assert (await owner.post(f"{root}/approve")).status_code == 409  # already decided

    # changing the words takes the approval back: it was an approval of the old words
    again = await owner.put(
        root, json={"subject": doc2["subject"], "body": doc2["body"] + "\nP.S. Soon?"}
    )
    assert again.json()["status"] == "draft"
    assert again.json()["decided_at"] is None
    assert again.json()["mailto"] is None
    # saving the same words again changes nothing and does not log an edit
    same = await owner.put(
        root, json={"subject": again.json()["subject"], "body": again.json()["body"]}
    )
    assert same.json()["status"] == "draft"

    withdrawn = await owner.post(f"{root}/withdraw")
    assert withdrawn.json()["status"] == "withdrawn"
    assert (await owner.put(root, json={"subject": "x", "body": "y"})).status_code == 409
    assert (await owner.post(f"{root}/approve")).status_code == 409

    actions = [
        r[0]
        for r in admin.execute(
            "SELECT action FROM audit_log WHERE action LIKE 'draft.%' ORDER BY at, id"
        ).fetchall()
    ]
    for expected in ("draft.edit", "draft.approve", "draft.withdraw"):
        assert expected in actions
    assert actions.count("draft.create") == 3
    assert actions.count("draft.edit") == 2  # the fill-in and the P.S., not the unchanged save

    gone = await owner.client.delete(owner.url(root), headers=owner.headers)
    assert gone.status_code == 204
    assert (await owner.get(root)).status_code == 404
    assert "draft.delete" in [
        r[0]
        for r in admin.execute(
            "SELECT action FROM audit_log WHERE action = 'draft.delete'"
        ).fetchall()
    ]


async def test_an_ad_angle_is_written_from_what_one_group_picks_and_stays_within_the_limits(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner, reward={"title": "A free coffee"})
    await full_board(world, admin, owner, venue)
    groups = (await listing(owner, venue))["sources"]["groups"]
    group = next(g for g in groups if g["loves"])
    made = await owner.post(f"{base(owner, venue)}/drafts", json={"group_index": group["index"]})
    assert made.status_code == 201, made.text
    (ad,) = [d for d in (await listing(owner, venue))["drafts"] if d["kind"] == "ad_copy"]
    assert ad["subject"] == f"Ad angle: {group['label']}"
    assert group["loves"][0] in ad["body"]
    headline = ad["body"].split("Headline (")[1].split("\n")[1]
    primary = ad["body"].split("Primary text (")[1].split("\n")[1]
    assert len(headline) <= dm.HEADLINE_MAX
    assert len(primary) <= dm.PRIMARY_MAX
    assert ad["facts"]["group"] == group["label"]
    assert ad["gaps"] == [
        "[What you want people to do, and the link]",
        "[The channel you choose; this draft is written for a short feed ad]",
    ]
    # the ad names no person and describes no audience: only what the group picks
    assert "aged" not in ad["body"] and "women" not in ad["body"] and "men " not in ad["body"]


async def test_a_request_that_names_neither_or_both_or_something_unknown_is_refused(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    await full_board(world, admin, owner, venue)
    url = f"{base(owner, venue)}/drafts"
    assert (await owner.post(url, json={})).status_code == 422
    assert (
        await owner.post(url, json={"from_action": "fill:1:1:x", "group_index": 0})
    ).status_code == 422
    unknown = await owner.post(url, json={"from_action": "fill:9:9:nothing"})
    assert unknown.status_code == 404
    no_group = await owner.post(url, json={"group_index": 42})
    assert no_group.status_code == 404
    assert (await owner.post(url, json={"from_action": "x", "extra": 1})).status_code == 422
    assert (await listing(owner, venue))["drafts"] == []


async def test_drafts_belong_to_their_account_and_only_writers_decide(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    doc = await full_board(world, admin, owner, venue)
    fill = await accept_first(owner, venue, doc)
    await owner.post(f"{base(owner, venue)}/drafts", json={"from_action": fill["key"]})
    mine = (await listing(owner, venue))["drafts"][0]

    viewer = await sign_up(world)
    admin.execute(
        "INSERT INTO membership (tenant_id, user_id, role) VALUES (%s, %s, 'viewer')",
        (owner.tenant_id, viewer.me["user_id"]),
    )
    root = f"/v1/tenants/{owner.tenant_id}{base(owner, venue)}/drafts"
    assert (await viewer.client.get(root)).status_code == 200
    assert (
        await viewer.client.post(root, json={"group_index": 0}, headers=viewer.headers)
    ).status_code == 403
    for verb in ("approve", "withdraw"):
        assert (
            await viewer.client.post(f"{root}/{mine['id']}/{verb}", headers=viewer.headers)
        ).status_code == 403
    assert (
        await viewer.client.put(
            f"{root}/{mine['id']}", json={"subject": "s", "body": "b"}, headers=viewer.headers
        )
    ).status_code == 403
    assert (
        await viewer.client.delete(f"{root}/{mine['id']}", headers=viewer.headers)
    ).status_code == 403

    stranger = await sign_up(world)
    theirs = f"/v1/tenants/{stranger.tenant_id}{base(owner, venue)}/drafts"
    assert (await stranger.client.get(theirs)).status_code == 404
    assert (await stranger.client.get(f"{theirs}/{mine['id']}")).status_code == 404
    assert (
        await stranger.client.post(f"{theirs}/{mine['id']}/approve", headers=stranger.headers)
    ).status_code == 404
    assert (await world.client().get(root)).status_code == 401
