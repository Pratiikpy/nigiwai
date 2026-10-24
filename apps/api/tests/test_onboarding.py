"""Onboarding through the real API: the fixed interview for five invented owners, the rules that refuse a bad answer, the
model-led interview with a scripted model (what it may and may not do), the fallbacks when it fails, and what is written
when the owner confirms. Every name is invented; the model is an in-process stand-in for the Anthropic API."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import psycopg
import pytest
from harness import World, WorldFactory, make_venue, sign_up
from nigiwai_api.services import onboarding as service
from nigiwai_api.services import onboarding_model as om
from nigiwai_api.services.geocode import Geocoder
from test_ask import ScriptedModel, results_of, said, tool
from test_onboarding_model import PERSONAS

ZONE = "Europe/London"
WEEK5: list[dict[str, str] | None] = [{"open": "08:00", "close": "17:00"}] * 5 + [None, None]


async def begin(owner: Any, mode: str = "auto", restart: bool = False) -> dict[str, Any]:
    res = await owner.post("/onboarding", json={"mode": mode, "restart": restart})
    assert res.status_code == 200, res.text
    out: dict[str, Any] = res.json()
    return out


async def reply(owner: Any, session: dict[str, Any], verb: str, body: dict[str, Any]) -> Any:
    return await owner.post(f"/onboarding/{session['id']}/{verb}", json=body)


async def run_form(
    owner: Any, answers: dict[str, Any], *, skip: set[str] | None = None
) -> tuple[dict[str, Any], list[str]]:
    """Answer the fixed questions the way a persona would. Returns the final state and the fields asked, in order."""
    state = await begin(owner, "form")
    asked: list[str] = []
    while state["question"]:
        field = state["question"]["field"]
        asked.append(field)
        if field in answers and field not in (skip or set()):
            res = await reply(owner, state, "answer", {"field": field, "value": answers[field]})
        else:
            res = await reply(owner, state, "skip", {"field": field})
        assert res.status_code == 200, res.text
        state = res.json()
        assert len(asked) <= 12, asked
    return state, asked


async def confirm(owner: Any, state: dict[str, Any], name: str, **extra: Any) -> dict[str, Any]:
    res = await reply(owner, state, "confirm", {"name": name, "timezone": ZONE, **extra})
    assert res.status_code == 200, res.text
    out: dict[str, Any] = res.json()
    return out


def modules_on(plan: dict[str, Any]) -> set[str]:
    return {m["id"] for m in plan["modules"] if m["on"]}


def rows(admin: psycopg.Connection[Any], sql: str, *args: Any) -> list[tuple[Any, ...]]:
    return admin.execute(sql, args).fetchall()


# ------------------------------------------------------------------------------------------------ the fixed interview
@pytest.mark.parametrize("name", list(PERSONAS))
async def test_each_persona_is_interviewed_in_eight_questions_or_fewer_and_the_right_things_are_saved(
    world: World, admin: psycopg.Connection[Any], name: str
) -> None:
    persona = PERSONAS[name]
    owner = await sign_up(world, business="Account name")
    state, asked = await run_form(owner, persona["answers"])
    assert asked == persona["asked"]
    assert state["asked"] == len(asked) <= om.MAX_QUESTIONS
    assert state["ready"]
    assert state["question"] is None
    assert state["messages"][-1]["text"] == service.UNDERSTOOD
    assert state["agent_available"] is False
    assert state["mode"] == "form"
    assert (
        state["profile"]["type"] == persona["answers"]["type"]
    )  # shown back before anything is saved
    assert (
        rows(admin, "SELECT count(*) FROM business")[0][0] == 0
    )  # and nothing is written until confirmed

    done = await confirm(owner, state, persona["name"])
    assert done["profile_version"] == 1
    assert done["plan_version"] == 1
    on = modules_on(done["plan"])
    assert persona["modules_on"] <= on
    assert not persona["modules_off"] & on
    assert {"today", "people", "ask"} <= on
    biz = rows(admin, "SELECT name, type, currency FROM business")
    assert biz == [(persona["name"], persona["answers"]["type"], persona["answers"]["currency"])]
    (address, tz, hours, capacity, nights) = rows(
        admin, "SELECT address, timezone, hours, capacity, show_nights FROM location"
    )[0]
    assert address == persona["answers"]["area"]
    assert tz == ZONE
    assert hours == [
        h and {"open": h["open"], "close": h["close"]} for h in persona["answers"]["hours"]
    ]
    assert (
        capacity == persona["answers"].get("capacity")
        if "capacity" in persona["asked"]
        else capacity is None
    )
    assert (
        list(nights) == persona["answers"].get("show_nights", [])
        if "show_nights" in persona["asked"]
        else True
    )
    assert rows(admin, "SELECT count(*) FROM business_profile")[0][0] == 1
    assert rows(admin, "SELECT count(*) FROM dashboard_plan")[0][0] == 1
    assert rows(admin, "SELECT status FROM onboarding_session") == [("confirmed",)]
    assert (
        rows(admin, "SELECT count(*) FROM audit_log WHERE action = 'onboarding.confirm'")[0][0] == 1
    )
    after = (await owner.get("/onboarding")).json()
    assert after["session"] is None
    assert after["plan"]["version"] == 1


async def test_a_bad_answer_is_refused_with_a_reason_and_the_question_stays_where_it_was(
    world: World,
) -> None:
    owner = await sign_up(world)
    state = await begin(owner, "form")
    assert state["question"]["field"] == "type"
    assert state["question"]["choices"][0] == {"value": "bar", "label": "Bar"}
    assert state["messages"][0]["role"] == "assistant"
    for field, value, fragment in (
        ("type", "spaceship", "Choose one of the kinds"),
        ("currency", "XYZ", "currency code"),
        ("goals", [], "between one and three"),
        ("hours", "9 to 5", "seven days"),
        ("capacity", "lots", "whole number"),
        ("colour", "blue", "not something I asked about"),
    ):
        res = await reply(owner, state, "answer", {"field": field, "value": value})
        assert res.status_code == 422, (field, res.text)
        assert fragment in res.json()["detail"], res.json()
    again = (await owner.get("/onboarding")).json()["session"]
    assert again["question"]["field"] == "type"
    assert again["known"] == {}
    assert again["asked"] == 1
    # a required question cannot be skipped; an optional one can
    res = await reply(owner, state, "skip", {"field": "type"})
    assert res.status_code == 422
    assert "cannot be skipped" in res.json()["detail"]
    ok = await reply(owner, state, "answer", {"field": "type", "value": "bar"})
    assert ok.json()["question"]["field"] == "area"
    # an answer to another question is kept, and the pending question does not move
    out = await reply(owner, state, "answer", {"field": "currency", "value": "gbp"})
    assert out.json()["known"]["currency"] == "GBP"
    assert out.json()["question"]["field"] == "area"
    # a known field cannot be "skipped": it is changed
    res = await reply(owner, state, "skip", {"field": "capacity"})
    assert res.status_code == 200
    res = await reply(owner, state, "skip", {"field": "currency"})
    assert res.status_code == 422


async def test_the_eight_question_cap_leaves_room_for_the_required_ones_and_extras_are_added_at_the_end(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    persona = PERSONAS["bar"]
    state, asked = await run_form(owner, persona["answers"])
    assert len(asked) == 8
    assert "capacity" not in asked
    assert "capacity" not in state["known"]
    # the owner can still say it while checking what was understood; adding a fact is not another question
    res = await reply(owner, state, "answer", {"field": "capacity", "value": 140})
    assert res.status_code == 200
    assert res.json()["asked"] == 8
    assert res.json()["question"] is None
    await confirm(owner, res.json(), persona["name"])
    assert rows(admin, "SELECT capacity FROM location") == [(140,)]


async def test_a_picked_place_is_saved_on_the_map_and_a_new_address_forgets_the_old_position(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    state = await begin(owner, "form")
    for field, value in (("type", "cafe"), ("area", "12 Quill Street, Manchester")):
        extra = (
            {"place": {"lat": 53.48, "lon": -2.24, "label": "12 Quill Street, Manchester"}}
            if field == "area"
            else {}
        )
        res = await reply(owner, state, "answer", {"field": field, "value": value, **extra})
        assert res.status_code == 200, res.text
        state = res.json()
    assert state["known"]["place"]["lat"] == 53.48
    assert {line["field"]: line["text"] for line in state["understood"]}["place"].startswith(
        "12 Quill"
    )
    # bad positions are refused
    bad = await reply(
        owner,
        state,
        "answer",
        {"field": "area", "value": "x y z", "place": {"lat": 95, "lon": 0, "label": "x"}},
    )
    assert bad.status_code == 422
    # typing a different address without picking a match drops the old position
    moved = await reply(owner, state, "answer", {"field": "area", "value": "9 Other Road, Leeds"})
    assert "place" not in moved.json()["known"]
    again = await reply(
        owner,
        state,
        "answer",
        {
            "field": "area",
            "value": "9 Other Road, Leeds",
            "place": {"lat": 53.8, "lon": -1.55, "label": "9 Other Road"},
        },
    )
    state = again.json()
    for field, value in (("goals", ["grow"]), ("currency", "GBP")):
        state = (await reply(owner, state, "answer", {"field": field, "value": value})).json()
    await confirm(owner, state, "Quill")
    lat, lon = rows(admin, "SELECT ST_Y(geom::geometry), ST_X(geom::geometry) FROM location")[0]
    assert (round(lat, 2), round(lon, 2)) == (53.8, -1.55)


async def test_a_venue_with_no_picked_place_is_saved_without_a_position_and_says_so(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    state, _ = await run_form(owner, PERSONAS["cafe"]["answers"])
    by_field = {line["field"]: line["text"] for line in state["understood"]}
    assert by_field["place"] == "Not placed yet"
    await confirm(owner, state, "Quill")
    assert rows(admin, "SELECT geom IS NULL FROM location") == [(True,)]


# ------------------------------------------------------------------------------------------------ who may do what
async def test_only_someone_who_can_change_the_account_can_answer_and_other_accounts_see_nothing(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    state = await begin(owner, "form")
    viewer = await sign_up(world)
    admin.execute(
        "INSERT INTO membership (tenant_id, user_id, role) VALUES (%s, %s, 'viewer')",
        (owner.tenant_id, viewer.me["user_id"]),
    )
    base = f"/v1/tenants/{owner.tenant_id}"
    seen = await viewer.client.get(f"{base}/onboarding")
    assert seen.status_code == 200
    assert seen.json()["session"]["id"] == state["id"]
    for verb, body in (
        ("answer", {"field": "type", "value": "bar"}),
        ("skip", {"field": "capacity"}),
        ("say", {"text": "hello"}),
        ("confirm", {"name": "X", "timezone": ZONE}),
        ("abandon", {}),
    ):
        res = await viewer.client.post(
            f"{base}/onboarding/{state['id']}/{verb}", json=body, headers=viewer.headers
        )
        assert res.status_code == 403, (verb, res.text)
    assert (
        await viewer.client.post(f"{base}/onboarding", json={}, headers=viewer.headers)
    ).status_code == 403
    assert (
        await viewer.client.put(f"{base}/plan", json={"overrides": {}}, headers=viewer.headers)
    ).status_code == 403

    stranger = await sign_up(world)
    other = await stranger.client.get(f"/v1/tenants/{owner.tenant_id}/onboarding")
    assert other.status_code in (403, 404)
    mine = (await stranger.get("/onboarding")).json()
    assert mine["session"] is None  # their own account has no interview
    crossed = await stranger.post(
        f"/onboarding/{state['id']}/answer", json={"field": "type", "value": "bar"}
    )
    assert crossed.status_code == 404
    anonymous = await world.client().get(f"{base}/onboarding")
    assert anonymous.status_code == 401


async def test_starting_again_returns_the_open_interview_and_restart_abandons_it(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    first = await begin(owner, "form")
    await reply(owner, first, "answer", {"field": "type", "value": "bar"})
    same = await begin(owner, "form")
    assert same["id"] == first["id"]
    assert same["known"] == {"type": "bar"}
    fresh = await begin(owner, "form", restart=True)
    assert fresh["id"] != first["id"]
    assert fresh["known"] == {}
    assert sorted(r[0] for r in rows(admin, "SELECT status FROM onboarding_session")) == [
        "abandoned",
        "open",
    ]
    gone = await reply(owner, first, "answer", {"field": "area", "value": "Leeds"})
    assert gone.status_code == 404  # an abandoned interview takes no answers
    res = await reply(owner, fresh, "abandon", {})
    assert res.status_code == 204
    assert (await owner.get("/onboarding")).json()["session"] is None
    assert (await reply(owner, fresh, "abandon", {})).status_code == 404
    # nothing was written to the business by any of it
    assert rows(admin, "SELECT count(*) FROM business")[0][0] == 0


async def test_writing_in_your_own_words_needs_the_assistant(world: World) -> None:
    owner = await sign_up(world)
    state = await begin(owner, "form")
    res = await reply(owner, state, "say", {"text": "We are a cafe in Leeds"})
    assert res.status_code == 409
    assert "needs the assistant" in res.json()["detail"]


# ------------------------------------------------------------------------------------------------ the model-led interview
async def agent(world: World, *steps: Any) -> ScriptedModel:
    model = ScriptedModel(*steps)
    world.app.state.nigiwai.llm = model.client()
    return model


async def test_the_assistant_records_what_the_owner_said_asks_what_is_missing_and_finishes(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    model = await agent(
        world,
        [
            tool("record_answer", field="type", value="cafe", quote="coffee shop"),
            tool(
                "record_answer",
                field="area",
                value="12 Quill Street, Manchester",
                quote="12 Quill Street, Manchester",
            ),
            tool("record_answer", field="currency", value="GBP", quote="pounds"),
            tool("record_answer", field="hours", value=WEEK5, quote="8 to 5 weekdays"),
            tool("ask_owner", field="goals", text="What would you most like help with?"),
        ],
        [tool("finish")],
    )
    owner = await sign_up(world)
    state = await begin(owner)
    assert state["mode"] == "agent"
    assert state["agent_available"] is True
    assert state["question"]["field"] == "type"
    assert "own words" in state["messages"][0]["text"]
    words = "We are a small coffee shop at 12 Quill Street, Manchester. Open 8 to 5 weekdays. We charge in pounds."
    res = await reply(owner, state, "say", {"text": words})
    assert res.status_code == 200, res.text
    state = res.json()
    assert state["known"]["type"] == "cafe"
    assert state["known"]["area"] == "12 Quill Street, Manchester"
    assert state["known"]["currency"] == "GBP"
    assert state["known"]["hours"][0] == {"open": "08:00", "close": "17:00"}
    assert state["known"]["hours"][5] is None
    assert state["question"]["field"] == "goals"
    assert state["question"]["text"] == "What would you most like help with?"
    assert state["messages"][-1] == {
        "role": "assistant",
        "text": "What would you most like help with?",
        "field": "goals",
    }
    assert (
        state["asked"] == 2
    )  # the first question the page opened with, and the one the assistant chose
    assert state["ready"] is False

    # the first thing the model saw: the instructions, the checklist, what was known and the owner's words
    first = model.requests[0]
    assert "Never fill in a fact the owner did not give" in first["system"]
    assert "hosts_live_music (optional)" in first["system"]
    assert {t["name"] for t in first["tools"]} == {"record_answer", "ask_owner", "finish"}
    shown = first["messages"][0]["content"]
    assert words in shown
    assert "Questions asked so far: 1 of 8" in shown

    # a click on a choice is recorded by the code itself; the model then decides what is next
    state = (
        await reply(owner, state, "answer", {"field": "goals", "value": ["fill_quiet_hours"]})
    ).json()
    assert state["ready"]
    assert state["question"] is None
    assert state["messages"][-1]["text"] == service.UNDERSTOOD
    assert state["mode"] == "agent"
    assert state["notice"] is None
    done = await confirm(owner, state, "Quill Street Café")
    assert "map" in modules_on(done["plan"])
    assert rows(admin, "SELECT input_tokens, output_tokens, model FROM onboarding_session") == [
        (200, 100, "claude-test-1")
    ]
    assert rows(admin, "SELECT name FROM business") == [("Quill Street Café",)]


async def test_the_assistant_cannot_record_a_quote_the_owner_never_wrote_or_a_value_the_form_would_refuse(
    world: World,
) -> None:
    def check(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        got = results_of(messages)
        assert "not in the owner's own words" in got[0]["error"]
        assert "currency code" in got[1]["error"]
        assert "not relevant" in got[2]["error"]
        assert got[3]["error"] == "required fields are still missing"
        assert got[3]["missing"] == ["type", "area", "goals", "currency"]
        assert got[4]["error"] == "unknown field"
        assert got[5]["error"] == "unknown tool"
        return [tool("ask_owner", field="type", text="Is it a bar, a café, or something else?")]

    model = await agent(
        world,
        [
            tool("record_answer", field="type", value="bar", quote="nightclub"),
            tool("record_answer", field="currency", value="XYZ", quote="bar"),
            tool("ask_owner", field="capacity", text="How many does it hold?"),
            tool("finish"),
            tool("record_answer", field="place", value={}, quote="bar"),
            tool("delete_everything"),
        ],
        check,
    )
    owner = await sign_up(world)
    state = await begin(owner)
    res = await reply(owner, state, "say", {"text": "I run a bar in Leeds"})
    assert res.status_code == 200, res.text
    state = res.json()
    assert state["known"] == {}  # nothing the model got wrong was kept
    assert state["question"]["field"] == "type"
    assert state["question"]["text"] == "Is it a bar, a café, or something else?"
    assert len(model.requests) == 2


def test_a_quote_may_differ_in_case_and_spacing_but_not_in_substance() -> None:
    assert service.grounded("COFFEE   shop", "We run a coffee shop.")
    assert service.grounded('"coffee shop."', "We run a coffee shop.")
    assert not service.grounded("tea room", "We run a coffee shop.")
    assert not service.grounded("a", "a b c")  # too short to prove anything
    assert not service.grounded(None, "x")
    assert not service.grounded(["coffee"], "coffee")


def test_the_assistant_is_held_to_the_question_cap_and_cannot_re_ask_what_is_known() -> None:
    s = service.Session(
        id=uuid.uuid4(),
        mode="agent",
        status="open",
        known={"type": "bar", "area": "Leeds city", "goals": ["grow"], "currency": "GBP"},
        skipped=[],
        asked=[
            {"field": f, "text": f}
            for f in (
                "type",
                "area",
                "goals",
                "currency",
                "hours",
                "hosts_live_music",
                "show_nights",
                "excluded_genres",
            )
        ],
        pending=None,
        messages=[],
        notice=None,
        model=None,
        input_tokens=0,
        output_tokens=0,
        updated_at=datetime.now(UTC),
    )
    out, over = service._handle(s, "ask_owner", {"field": "capacity", "text": "How many?"})
    assert out == {"error": "the question limit is reached; call finish"}
    assert not over
    assert s.pending is None
    out, over = service._handle(s, "ask_owner", {"field": "type", "text": "Again?"})
    assert "known" in out["error"]
    out, over = service._handle(s, "finish", {})
    assert out == {"finished": True}
    assert over
    assert s.messages[-1]["text"] == service.UNDERSTOOD
    assert len(s.asked) == 8


async def test_a_model_that_is_down_hands_over_to_the_fixed_questions_with_a_notice(
    world: World,
) -> None:
    await agent(world, None, None)  # the call and its one retry both fail
    owner = await sign_up(world)
    state = await begin(owner)
    first = state
    res = await reply(owner, first, "answer", {"field": "type", "value": "bar"})
    assert res.status_code == 200, res.text
    state = res.json()
    assert state["mode"] == "form"
    assert "unavailable" in state["notice"]
    assert state["question"]["field"] == "area"  # the next fixed question
    assert state["question"]["text"] == om.CHECKLIST["area"].text
    # from here it is the plain form
    res = await reply(owner, state, "say", {"text": "more words"})
    assert res.status_code == 409


async def test_a_model_that_never_uses_its_tools_falls_back_for_that_step_only(
    world: World,
) -> None:
    await agent(world, [said("Sure, tell me more.")], [said("Anything else?")])
    owner = await sign_up(world)
    state = await begin(owner)
    state = (await reply(owner, state, "answer", {"field": "type", "value": "bar"})).json()
    assert state["mode"] == "agent"  # one bad turn does not end the assistant's part
    assert state["question"]["field"] == "area"
    assert state["notice"] is None


async def test_the_assistant_has_a_daily_allowance_and_the_form_takes_over_when_it_is_spent(
    make_world: WorldFactory,
) -> None:
    async with make_world(onboarding_daily_limit=1) as world:
        await agent(world, [tool("ask_owner", field="area", text="Where is it?")])
        owner = await sign_up(world)
        state = await begin(owner)
        state = (await reply(owner, state, "answer", {"field": "type", "value": "cafe"})).json()
        assert state["mode"] == "agent"
        assert state["question"]["text"] == "Where is it?"
        state = (
            await reply(owner, state, "answer", {"field": "area", "value": "12 Quill Street"})
        ).json()
        assert state["mode"] == "form"
        assert "limit" in state["notice"]
        assert state["question"]["field"] == "goals"


async def test_with_no_model_connected_the_interview_is_the_form_from_the_start(
    world: World,
) -> None:
    owner = await sign_up(world)
    state = await begin(owner, "auto")
    assert state["mode"] == "form"
    assert state["agent_available"] is False
    assert state["notice"] is None


# ------------------------------------------------------------------------------------------------ doing it again
async def test_a_second_interview_starts_from_what_is_on_record_and_never_erases_it(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    state, _ = await run_form(owner, PERSONAS["bar"]["answers"])
    await confirm(owner, state, "The Lamplighter")
    admin.execute("UPDATE location SET excluded_genres = ARRAY['metal'], capacity = 90")

    again = await begin(owner, "form")
    assert again["known"]["type"] == "bar"
    assert again["known"]["hosts_live_music"] is True
    assert again["known"]["goals"] == ["book_acts", "know_crowd"]
    assert again["known"]["capacity"] == 90
    assert again["known"]["excluded_genres"] == ["metal"]
    assert again["known"]["hours"][0] == {"open": "17:00", "close": "01:00"}
    assert again["question"] is None  # nothing left to ask
    assert again["ready"]

    # an empty answer is "none given", not "delete": the genres on record stay
    cleared = await reply(owner, again, "answer", {"field": "excluded_genres", "value": ""})
    done = await confirm(owner, cleared.json(), "The Lamplighter", overrides={"soundcheck": False})
    assert done["profile_version"] == 2
    assert done["plan_version"] == 2
    assert rows(admin, "SELECT excluded_genres FROM location") == [(["metal"],)]
    assert rows(admin, "SELECT count(*) FROM business")[0][0] == 1  # the same business, updated
    assert rows(admin, "SELECT count(*) FROM location")[0][0] == 1
    plan = {m["id"]: m for m in done["plan"]["modules"]}
    assert plan["soundcheck"]["on"] is False
    assert plan["soundcheck"]["changed"] is True
    assert plan["soundcheck"]["reason"].startswith("Switched off by you.")
    assert done["plan"]["overrides"] == {"soundcheck": False}


async def test_a_business_made_on_the_venue_page_is_picked_up_and_only_the_missing_things_are_asked(
    world: World,
) -> None:
    owner = await sign_up(world)
    await make_venue(owner)
    state = await begin(owner, "form")
    assert state["known"]["type"] == "live_music_venue"
    assert state["known"]["currency"] == "GBP"
    assert state["known"]["place"]["lat"] == pytest.approx(51.5)
    assert "area" not in state["known"]  # that venue was saved with a position but no address
    assert state["question"]["field"] == "area"
    assert state["business_name"] == "The Lantern"


# ------------------------------------------------------------------------------------------------ the plan
async def test_the_plan_can_be_switched_by_the_owner_and_core_modules_cannot(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    assert (await owner.get("/plan")).json() is None
    nothing = await owner.put("/plan", json={"overrides": {"soundcheck": True}})
    assert nothing.status_code == 409
    state, _ = await run_form(owner, PERSONAS["cafe"]["answers"])
    await confirm(owner, state, "Quill")
    plan = (await owner.get("/plan")).json()
    assert plan["version"] == 1
    assert "soundcheck" not in modules_on(plan)
    assert plan["profile"]["type"] == "cafe"

    res = await owner.put("/plan", json={"overrides": {"soundcheck": True, "map": False}})
    assert res.status_code == 200, res.text
    switched = res.json()
    assert switched["version"] == 2
    assert switched["profile_version"] == 1
    assert {"soundcheck"} <= modules_on(switched)
    assert "map" not in modules_on(switched)
    assert switched["overrides"] == {"soundcheck": True, "map": False}
    # switching back to what the planner chose leaves no override
    back = (await owner.put("/plan", json={"overrides": {"soundcheck": False}})).json()
    assert back["overrides"] == {}
    assert back["version"] == 3

    for module_id in ("today", "ask", "grow", "nonsense"):
        res = await owner.put("/plan", json={"overrides": {module_id: False}})
        assert res.status_code == 422, (module_id, res.text)
        assert "cannot be switched" in res.json()["detail"]
    assert rows(admin, "SELECT max(version) FROM dashboard_plan")[0][0] == 3
    assert (
        rows(admin, "SELECT count(*) FROM business_profile")[0][0] == 1
    )  # the profile did not change


# ------------------------------------------------------------------------------------------------ address search
class Nominatim:
    def __init__(self) -> None:
        self.asked: list[dict[str, str]] = []

    def install(self, world: World, *, down: bool = False) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.asked.append(dict(request.url.params))
            if down:
                return httpx.Response(503, text="busy")
            if "nowhere" in request.url.params["q"]:
                return httpx.Response(200, json=[])
            return httpx.Response(
                200,
                json=[
                    {
                        "lat": "53.48",
                        "lon": "-2.24",
                        "display_name": "12, Quill Street, Manchester, England",
                    },
                    {
                        "lat": "53.50",
                        "lon": "-457",
                        "display_name": "Quill Street, Austin",
                    },  # impossible position
                    {"lat": "x", "lon": "1", "display_name": "garbled"},
                    {"lat": "53.9", "lon": "-1.6", "display_name": "  Quill   Street, Leeds "},
                ],
            )

        state = world.app.state.nigiwai
        state.geocoder = Geocoder(
            state.engine,
            "http://nominatim.test",
            "tests",
            httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )


async def test_the_address_search_returns_clean_matches_caches_them_and_survives_the_service_being_down(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Geocoder, "INTERVAL", 0.0)
    nominatim = Nominatim()
    nominatim.install(world)
    owner = await sign_up(world)
    res = await owner.get("/places/search", params={"q": "12 Quill Street Manchester"})
    assert res.status_code == 200, res.text
    assert res.json()["places"] == [
        {"label": "12, Quill Street, Manchester, England", "lat": 53.48, "lon": -2.24},
        {"label": "Quill Street, Leeds", "lat": 53.9, "lon": -1.6},
    ]
    again = await owner.get("/places/search", params={"q": "12  quill street, manchester"})
    assert again.json() == res.json()
    assert len(nominatim.asked) == 1  # the same address is never asked twice
    assert nominatim.asked[0]["limit"] == "5"
    empty = await owner.get("/places/search", params={"q": "nowhere at all"})
    assert empty.json() == {"places": []}
    short = await owner.get("/places/search", params={"q": "ab"})
    assert short.status_code == 422
    down = Nominatim()
    down.install(world, down=True)
    res = await owner.get("/places/search", params={"q": "7 Other Road Leeds"})
    assert res.status_code == 503
    assert "not answering" in res.json()["detail"]
    anonymous = await world.client().get(
        f"/v1/tenants/{owner.tenant_id}/places/search", params={"q": "abc def"}
    )
    assert anonymous.status_code == 401


async def test_the_interview_state_is_json_the_page_can_rely_on(world: World) -> None:
    owner = await sign_up(world)
    state = await begin(owner, "form")
    assert set(state) == {
        "id", "mode", "status", "agent_available", "messages", "question", "asked", "max_questions",
        "known", "understood", "ready", "business_name", "profile", "plan", "notice",
    }  # fmt: skip
    assert state["max_questions"] == 8
    assert state["business_name"] == "The Lantern"
    assert state["profile"] is None  # not shown until the required answers are in
    assert set(state["question"]) == {"field", "kind", "text", "why", "optional", "choices"}
    json.dumps(state)
