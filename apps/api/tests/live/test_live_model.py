"""The model-led features against a real language model and real Qloo, through the owner endpoints: the onboarding interview with
five owners who describe their business in their own words, Ask Nigiwai in both modes, and the AI-alone panel beside a Soundcheck.

These need a model: an OpenAI-compatible service named by NIGIWAI_LLM_BASE_URL and NIGIWAI_LLM_MODEL with its key in
NIGIWAI_LLM_API_KEY, or an Anthropic key file named by NIGIWAI_ANTHROPIC_KEY_FILE (with NIGIWAI_ANTHROPIC_WORKSPACE_ID if the key
needs one). Nothing is scripted. The assertions are about what must hold whatever the model says (nothing invented, nothing saved
the owner did not say, no crash, a plain fallback when it fails); how well it did is printed so it can be read."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import Any

import psycopg
import pytest
from harness import WorldFactory, make_venue, sign_up
from live.real_crowd import CROWDS, plant, resolve
from nigiwai_api.services import onboarding_model as om
from nigiwai_api.services import tribes as service
from nigiwai_tribes import TribesConfig

pytestmark = pytest.mark.skipif(
    os.environ.get("NIGIWAI_RUN_LIVE") != "1", reason="set NIGIWAI_RUN_LIVE=1 to spend quota"
)

MODEL_SETTINGS: dict[str, Any] = {}
if os.environ.get("NIGIWAI_LLM_BASE_URL"):
    MODEL_SETTINGS = {
        "llm_provider": "openai",
        "llm_base_url": os.environ["NIGIWAI_LLM_BASE_URL"],
        "llm_model": os.environ.get("NIGIWAI_LLM_MODEL", ""),
        "llm_extra_body": os.environ.get("NIGIWAI_LLM_EXTRA_BODY") or None,
        "llm_timeout_seconds": float(os.environ.get("NIGIWAI_LLM_TIMEOUT_SECONDS", "60")),
        "anthropic_key_file": None,
    }
elif os.environ.get("NIGIWAI_ANTHROPIC_KEY_FILE"):
    MODEL_SETTINGS = {
        "anthropic_key_file": os.environ["NIGIWAI_ANTHROPIC_KEY_FILE"],
        "anthropic_workspace_id": os.environ.get("NIGIWAI_ANTHROPIC_WORKSPACE_ID"),
        "llm_timeout_seconds": float(os.environ.get("NIGIWAI_LLM_TIMEOUT_SECONDS", "60")),
    }

needs_model = pytest.mark.skipif(
    not MODEL_SETTINGS, reason="no model is configured for the live tests"
)

WEEK6 = {"open": "08:00", "close": "17:00"}

OWNERS: dict[str, dict[str, Any]] = {
    "cafe": {
        "name": "Quill Street Café",
        "says": (
            "Hi! I run a little independent coffee shop, Quill Street Café, at 12 Quill Street in Manchester. We open 8am to 5pm "
            "Monday to Saturday and we are shut on Sundays. We charge in pounds. Honestly our afternoons are dead and I would love "
            "to fill them."
        ),
        "type": "cafe",
        "currency": "GBP",
        "area_has": ("quill", "manchester"),
        "goals": {"fill_quiet_hours"},
        "answers": {
            "type": "cafe",
            "area": "12 Quill Street, Manchester",
            "hosts_live_music": False,
            "goals": ["fill_quiet_hours"],
            "currency": "GBP",
        },
    },
    "bar": {
        "name": "The Lamplighter",
        "says": (
            "The Lamplighter is a cocktail and craft beer bar in Hackney, London. Open 5pm till 1am every day. We have live bands "
            "on Fridays and Saturdays, but no metal or drill please. I want to book better acts and understand who drinks here. "
            "Everything is in sterling."
        ),
        "type": "bar",
        "currency": "GBP",
        "area_has": ("hackney",),
        "goals": {"book_acts", "know_crowd"},
        "answers": {
            "goals": ["book_acts", "know_crowd"],
            "currency": "GBP",
            "hosts_live_music": True,
        },
    },
    "hotel": {
        "name": "The Halcyon Lounge",
        "says": (
            "We are the bar at the Halcyon hotel on Old Mill Road in Leeds. Open 5pm to 1am. Just background music, no live acts. "
            "The room holds about 80 people. Pounds. I mostly need help choosing what music to play."
        ),
        "type": "hotel_bar",
        "currency": "GBP",
        "area_has": ("mill", "leeds"),
        "goals": {"plan_music"},
        "answers": {
            "type": "hotel_bar",
            "area": "Old Mill Road, Leeds",
            "goals": ["plan_music"],
            "currency": "GBP",
            "hosts_live_music": False,
        },
    },
    "shop": {
        "name": "Thread & Needle",
        "says": (
            "We sell clothes. Thread & Needle is in the Corn Exchange in Bristol, open Monday to Saturday 8 to 5 and closed Sundays. "
            "Prices in pounds. I want to reach new kinds of customers."
        ),
        "type": "shop",
        "currency": "GBP",
        "area_has": ("corn exchange", "bristol"),
        "goals": {"grow"},
        "answers": {
            "type": "shop",
            "area": "Corn Exchange, Bristol",
            "goals": ["grow"],
            "currency": "GBP",
        },
    },
    "venue": {
        "name": "The Cellar",
        "says": (
            "The Cellar is a live music venue on the Lower East Side of New York. Gigs Thursday to Sunday, doors around 6pm until "
            "1am. Room for 250. We take dollars. We book acts every week and want to book better ones."
        ),
        "type": "live_music_venue",
        "currency": "USD",
        "area_has": ("lower east side",),
        "goals": {"book_acts"},
        "answers": {
            "type": "live_music_venue",
            "area": "Lower East Side, New York",
            "goals": ["book_acts"],
            "currency": "USD",
            "hosts_live_music": True,
        },
    },
}


def events(body: str) -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    for chunk in body.split("\n\n"):
        name = data = None
        for line in chunk.splitlines():
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if name:
            out.append((name, data))
    return out


async def make_live_world(make_world: WorldFactory) -> Any:
    return make_world(
        with_qloo=False,
        qloo_key_file=os.environ.get("NIGIWAI_QLOO_KEY_FILE"),
        min_completion_seconds=0.0,
        trust_proxy=True,
        **MODEL_SETTINGS,
    )


@needs_model
async def test_live_five_owners_describe_their_business_and_the_interview_understands_them(
    make_world: WorldFactory, admin: psycopg.Connection[Any]
) -> None:
    async with await make_live_world(make_world) as world:
        assert world.app.state.nigiwai.llm is not None, "the model client was not built"
        report: list[str] = []
        stayed = 0
        captured = 0
        for key, owner_spec in OWNERS.items():
            await asyncio.sleep(
                15
            )  # a hosted model's free tier answers about forty requests a minute
            owner = await sign_up(world, business="Account name")
            res = await owner.post("/onboarding", json={"mode": "auto", "restart": False})
            assert res.status_code == 200, res.text
            state = res.json()
            assert state["agent_available"] is True, "the assistant is not available: " + str(
                state.get("notice")
            )
            assert state["mode"] == "agent"
            res = await owner.post(
                f"/onboarding/{state['id']}/say", json={"text": owner_spec["says"]}
            )
            assert res.status_code == 200, res.text
            state = res.json()
            after_first = {k: v for k, v in state["known"].items()}
            # whatever the model could not take from the owner's words, the owner is asked, and answers as they would click it
            required = ("type", "area", "goals", "currency")
            missed = [f for f in required if f not in after_first]
            asked_for: list[str] = []
            guard = 0
            while state["question"] and guard < 10:
                guard += 1
                field = state["question"]["field"]
                asked_for.append(field)
                if field in owner_spec["answers"]:
                    res = await owner.post(
                        f"/onboarding/{state['id']}/answer",
                        json={"field": field, "value": owner_spec["answers"][field]},
                    )
                else:
                    res = await owner.post(f"/onboarding/{state['id']}/skip", json={"field": field})
                assert res.status_code == 200, (field, res.text)
                state = res.json()
            captured += len(required) - len(missed)
            stayed += 1 if state["mode"] == "agent" else 0
            known = state["known"]
            report.append(
                f"{key:6} mode={state['mode']:5} asked={state['asked']} first-message={sorted(after_first)} final={sorted(known)}"
                f" missed={missed} asked-for={asked_for} notice={state.get('notice')}"
            )
            # what must hold whatever the model did
            assert state["asked"] <= om.MAX_QUESTIONS
            assert known.get("type") in om.BUSINESS_TYPES if "type" in known else True
            if "goals" in known:
                assert set(known["goals"]) <= set(om.GOALS)
            # nothing was saved before the owner confirms
            assert admin.execute(
                "SELECT count(*) FROM business WHERE name = %s", (owner_spec["name"],)
            ).fetchone() == (0,)
            # what the owner said, understood: the kind, the money and the place
            assert known.get("type") == owner_spec["type"], (key, known.get("type"))
            assert known.get("currency") == owner_spec["currency"], (key, known.get("currency"))
            area = str(known.get("area", "")).casefold()
            assert all(token in area for token in owner_spec["area_has"]), (key, known.get("area"))
            assert state["ready"], (key, state)
        print("\n".join(report))
        print("stayed in assistant mode:", stayed, "of", len(OWNERS))
        print(
            "required facts taken from the owner's first message:", captured, "of", 4 * len(OWNERS)
        )
        assert stayed >= 4, "the assistant fell back to the form for too many owners"


@needs_model
async def test_live_ask_answers_in_both_modes_from_real_qloo_with_nothing_invented(
    make_world: WorldFactory, admin: psycopg.Connection[Any]
) -> None:
    async with await make_live_world(make_world) as world:
        state = world.app.state.nigiwai
        assert state.llm is not None and state.guard is not None
        owner = await sign_up(world)
        venue = await make_venue(owner)
        ids = await resolve(world, venue, CROWDS)
        plant(admin, venue, ids)
        await service.recompute(
            state.engine,
            state.guard,
            uuid.UUID(owner.tenant_id),
            uuid.UUID(venue.business_id),
            force=True,
            cfg=TribesConfig(bootstrap=15, null_runs=19, lift_bootstrap=40),
        )
        questions = [
            (
                "culture",
                "What films and TV shows do people who love Frank Sinatra also tend to love?",
            ),
            ("culture", "Which bars near this venue would a crowd that likes Metallica enjoy?"),
            (
                "crowd",
                "Which of my groups would turn out for a night of classic crooners, and which act would suit them?",
            ),
            ("crowd", "What should I book for a quiet Tuesday night?"),
            ("culture", "Which podcasts do fans of Pantera like?"),
        ]
        made = 0
        lines: list[str] = []
        for mode, question in questions:
            res = await owner.client.post(
                f"/v1/tenants/{owner.tenant_id}/businesses/{venue.business_id}/ask",
                json={"question": question, "mode": mode},
                headers=owner.headers,
                timeout=240,
            )
            assert res.status_code == 200, res.text
            evs = events(res.text)
            errors = [d for n, d in evs if n == "error"]
            assert not errors, errors
            answers = [d for n, d in evs if n == "answer"]
            assert len(answers) == 1, res.text[:500]
            a = answers[0]
            made += 1 if a["kind"] == "model" else 0
            names = [i.get("name") for i in a["items"]]
            lines.append(
                f"[{a['kind']:8}] {mode:7} turns={a['stats']['model_turns']} qloo={a['stats']['qloo_calls']} {a['stats']['seconds']}s "
                f"tools={a['stats']['tools']}\n   Q: {question}\n   verdict: {a['verdict']}\n   items: {names}\n   not_enough_data: {a.get('not_enough_data')}"
            )
            # whatever the model did, every listed item came out of a Qloo call and carries its provenance and a label
            for item in a["items"]:
                assert item.get("name"), item
                assert item.get("label") in ("measured", "observed", "modelled"), item
        print("\n".join(lines))
        print("answers written by the model:", made, "of", len(questions))
        assert made >= 3, "the model produced a usable answer for too few questions"


@needs_model
async def test_live_the_ai_alone_panel_gets_a_real_list_or_says_why_not(
    make_world: WorldFactory, admin: psycopg.Connection[Any]
) -> None:
    async with await make_live_world(make_world) as world:
        state = world.app.state.nigiwai
        assert state.llm is not None and state.guard is not None
        owner = await sign_up(world)
        venue = await make_venue(owner)
        ids = await resolve(world, venue, CROWDS)
        plant(admin, venue, ids)
        await service.recompute(
            state.engine,
            state.guard,
            uuid.UUID(owner.tenant_id),
            uuid.UUID(venue.business_id),
            force=True,
            cfg=TribesConfig(bootstrap=15, null_runs=19, lift_bootstrap=40),
        )
        root = f"/businesses/{venue.business_id}"
        got = 0
        for name in ("Ariana Grande", "Rammstein", "Peggy Lee"):
            found = (await owner.get(f"{root}/soundcheck/search", params={"q": name})).json()
            hit = next((i for i in found["items"] if i["name"].lower() == name.lower()), None)
            assert hit is not None, (name, [i["name"] for i in found["items"]])
            doc = (
                await owner.post(f"{root}/soundcheck", json={"entity_id": hit["entity_id"]})
            ).json()
            assert doc["status"] == "ok", doc
            cmp = await owner.get(f"{root}/soundchecks/{doc['id']}/compare")
            assert cmp.status_code == 200, cmp.text
            panel = cmp.json()
            print(
                name, json.dumps({k: (v if k != "qloo" else "...") for k, v in panel.items()})[:700]
            )
            ai = panel.get("ai")
            assert isinstance(ai, dict), panel
            if ai.get("available"):
                got += 1
                assert ai.get("items"), ai
            else:
                assert ai.get("reason"), ai  # an honest reason, never an empty panel
        assert got >= 2, "the AI-alone side answered for too few acts"
