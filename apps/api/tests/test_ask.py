"""Ask Nigiwai: a scripted model calls the real tools against a scripted Qloo, and the answer that reaches the owner is
checked: only items a tool returned, names from Qloo's records, labels the evidence earns, nothing invented. The model is
an in-process stand-in for the Anthropic API; every name is invented."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from typing import Any

import httpx2
import psycopg
from fakeqloo import artist
from harness import World, make_venue, sign_up
from nigiwai_api.services import ask as service
from nigiwai_api.services.llm import LlmClient
from test_soundcheck import add_artist, base, crowd

Blocks = list[dict[str, Any]]
Step = Blocks | Callable[[list[dict[str, Any]]], Blocks]


def act_id(name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"nigiwai-test-act/{name}"))


def tool(tool_name: str, /, **args: Any) -> dict[str, Any]:
    return {
        "type": "tool_use",
        "id": f"toolu_{uuid.uuid4().hex[:12]}",
        "name": tool_name,
        "input": args,
    }


def said(words: str) -> dict[str, Any]:
    return {"type": "text", "text": words}


def results_of(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The JSON of the tool results in the last message the model was sent, in order."""
    last = messages[-1]["content"]
    assert isinstance(last, list)
    return [
        json.loads(b["content"]) if b["content"].startswith(("{", "[")) else {"text": b["content"]}
        for b in last
        if b.get("type") == "tool_result"
    ]


class ScriptedModel:
    """Stands in for api.anthropic.com. Each step is the content of one assistant turn, or a function of the conversation
    so far that returns it (so a step can use an id an earlier tool returned). A step of None answers 500."""

    def __init__(self, *script: Step | None) -> None:
        self.script = list(script)
        self.requests: list[dict[str, Any]] = []

    def client(self) -> LlmClient:
        def handler(request: httpx2.Request) -> httpx2.Response:
            body = json.loads(request.content)
            self.requests.append(body)
            if not self.script:  # the script ran out: the model just talks, never calling a tool
                return reply([said("I have nothing more to add.")], stop="end_turn")
            step = self.script.pop(0)
            if step is None:
                return httpx2.Response(
                    500, json={"type": "error", "error": {"type": "api_error", "message": "down"}}
                )
            blocks = step(body["messages"]) if callable(step) else step
            return reply(
                blocks, stop="end_turn" if all(b["type"] == "text" for b in blocks) else "tool_use"
            )

        return LlmClient(
            "sk-test-key-not-real",
            "claude-test-1",
            base_url="http://model.test",
            http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
        )


def reply(blocks: Blocks, stop: str = "tool_use") -> httpx2.Response:
    return httpx2.Response(
        200,
        json={
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "model": "claude-test-1",
            "content": blocks,
            "stop_reason": stop,
            "stop_sequence": None,
            "usage": {"input_tokens": 100, "output_tokens": 50},
        },
    )


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


async def ask(
    world: World, owner: Any, venue: Any, model: ScriptedModel, question: str, mode: str = "culture"
) -> tuple[list[tuple[str, Any]], Any]:
    world.app.state.nigiwai.llm = model.client()
    res = await owner.client.post(
        f"/v1/tenants/{owner.tenant_id}{base(owner, venue)}/ask",
        json={"question": question, "mode": mode},
        headers=owner.headers,
    )
    assert res.status_code == 200, res.text
    assert res.headers["content-type"].startswith("text/event-stream")
    return events(res.text), res


def answer_of(evs: list[tuple[str, Any]]) -> dict[str, Any]:
    found = [d for n, d in evs if n == "answer"]
    assert len(found) == 1, evs
    return found[0]  # type: ignore[no-any-return]


def known_world(world: World, admin: psycopg.Connection[Any]) -> str:
    """Qloo knows 'Quiet Act' and, in the same group, nine neighbours. Returns Quiet Act's id."""
    quiet = artist(
        "Quiet Act", entity_id=act_id("Quiet Act"), tags=[("urn:tag:genre:qloo:folk", "Folk")]
    )
    world.qloo.catalogue = [quiet]
    add_artist(admin, world, "Quiet Act", 0)
    for i in range(9):
        add_artist(admin, world, f"Gentle Neighbour {i}", 0, popularity=0.1 + 0.05 * i)
    return act_id("Quiet Act")


def first_id(messages: list[dict[str, Any]]) -> str:
    return str(results_of(messages)[0]["items"][0]["id"])


async def test_a_question_is_answered_from_what_the_tools_returned_and_the_answer_is_stored(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    known_world(world, admin)
    neighbour = act_id("Gentle Neighbour 3")
    model = ScriptedModel(
        [said("Let me look that up."), tool("resolve_entity", text="Quiet Act", type="artist")],
        lambda m: [tool("related", type="artist", seeds=[first_id(m)], take=9)],
        lambda m: [
            tool(
                "answer",
                verdict="Gentle Neighbour 3 is the closest match Qloo found to Quiet Act.",
                items=[{"entity_id": neighbour, "reason": "Qloo links it to Quiet Act."}],
                evidence=[
                    {"label": "observed", "text": "Qloo returned nine acts linked to Quiet Act."}
                ],
                what_would_change=["Naming a second act would narrow the list."],
                not_enough_data=None,
            )
        ],
    )
    evs, _ = await ask(world, owner, venue, model, "Who is like Quiet Act?")
    names = [n for n, _ in evs]
    assert names[0] == "start" and names[-1] == "done"
    assert names.count("step") == 2 and names.count("qloo_call") == 2 and names.count("answer") == 1
    steps = [d["text"] for n, d in evs if n == "step"]
    assert steps == ["Looking the item up in Qloo", "Asking Qloo what is linked to it"]

    doc = answer_of(evs)
    assert (
        doc["kind"] == "model"
        and doc["mode"] == "culture"
        and doc["question"] == "Who is like Quiet Act?"
    )
    (item,) = doc["items"]
    assert item["name"] == "Gentle Neighbour 3" and item["type"] == "artist" and item["rank"] == 1
    assert (
        item["provenance"] == "surfaced" and item["label"] == "observed"
    )  # Qloo surfaced it, not the model
    assert doc["evidence"] == [
        {"label": "observed", "text": "Qloo returned nine acts linked to Quiet Act."}
    ]
    assert doc["stats"]["model_turns"] == 3 and doc["stats"]["tools"] == [
        "resolve_entity",
        "related",
    ]
    assert doc["rejected"] == [] and doc["notes"] == []

    # stored, listed, reopened, and the Qloo calls behind it can be read
    root = f"/v1/tenants/{owner.tenant_id}{base(owner, venue)}/ask"
    listed = (await owner.client.get(root)).json()
    assert [(a["id"], a["question"], a["kind"]) for a in listed] == [
        (doc["id"], "Who is like Quiet Act?", "model")
    ]
    again = (await owner.client.get(f"{root}/{doc['id']}")).json()
    assert again["items"] == doc["items"] and again["verdict"] == doc["verdict"]
    trace = (await owner.client.get(f"{root}/{doc['id']}/trace")).json()
    assert [c["endpoint"] for c in trace if c["purpose"] == "ask"].count("/search") == 1
    assert any(c["endpoint"] == "/v2/insights" for c in trace)
    row = admin.execute(
        "SELECT model, input_tokens, output_tokens, prompt_hash FROM ask_answer"
    ).fetchone()
    assert (
        row is not None
        and row[0] == "claude-test-1"
        and row[1] == 300
        and row[2] == 150
        and len(row[3]) == 16
    )


async def test_an_item_no_tool_returned_is_never_listed_and_its_name_never_reaches_the_owner(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    known_world(world, admin)
    invented = str(uuid.uuid4())
    model = ScriptedModel(
        [tool("resolve_entity", text="Quiet Act", type="artist")],
        lambda m: [
            tool(
                "answer",
                verdict="Try Midnight Zebra Collective, then Quiet Act.",
                items=[
                    {
                        "entity_id": invented,
                        "reason": "Midnight Zebra Collective is a perfect fit.",
                    },
                    {"entity_id": first_id(m), "reason": "Qloo knows this act."},
                    {"entity_id": first_id(m), "reason": "listed twice"},
                ],
                evidence=[
                    {"label": "modelled", "text": "Midnight Zebra Collective would suit Fridays."}
                ],
                what_would_change=[],
            )
        ],
    )
    evs, res = await ask(world, owner, venue, model, "Who should I book?")
    doc = answer_of(evs)
    assert [i["name"] for i in doc["items"]] == [
        "Quiet Act"
    ]  # the invented id is gone, the repeat is dropped
    assert (
        doc["items"][0]["provenance"] == "confirmed"
    )  # the model proposed it and a lookup confirmed it
    assert doc["rejected"][0]["entity_id"] == invented
    assert "Midnight Zebra" not in res.text  # the name the model invented never reaches the owner
    assert "[a name Qloo did not return]" in doc["verdict"]
    assert any("removed because no Qloo call returned" in n for n in doc["notes"])
    assert any("left out because Qloo never returned" in n for n in doc["notes"])
    assert "Quiet Act" in doc["verdict"]  # a name a tool did return stays


async def test_plain_words_dates_and_the_venue_are_not_mistaken_for_invented_names(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    known_world(world, admin)
    model = ScriptedModel(
        [tool("resolve_entity", text="Quiet Act", type="artist")],
        lambda m: [
            tool(
                "answer",
                verdict="Quiet Act could suit The Lantern on Friday evening, but Qloo has no event listings.",
                items=[{"entity_id": first_id(m), "reason": "Your Wednesday crowd likes folk."}],
                evidence=[
                    {"label": "observed", "text": 'Qloo knows "Quiet Act" as a folk artist.'}
                ],
                what_would_change=["Fridays in October are busy."],
            )
        ],
    )
    evs, _ = await ask(world, owner, venue, model, "What suits my Friday?")
    doc = answer_of(evs)
    assert doc["notes"] == []
    assert (
        doc["verdict"]
        == "Quiet Act could suit The Lantern on Friday evening, but Qloo has no event listings."
    )
    assert doc["items"][0]["reason"] == "Your Wednesday crowd likes folk."


async def test_an_evidence_label_has_to_be_earned(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    model = ScriptedModel(
        [
            tool(
                "answer",
                verdict="Not much to say yet.",
                items=[],
                evidence=[
                    {"label": "measured", "text": "Guests love folk."},
                    {"label": "observed", "text": "Qloo says folk is popular."},
                    {"label": "modelled", "text": "Folk would probably work."},
                    {"label": "certain", "text": "An unknown label."},
                ],
                what_would_change=[],
            )
        ]
    )
    evs, _ = await ask(world, owner, venue, model, "Is folk good?")
    labels = [e["label"] for e in answer_of(evs)["evidence"]]
    assert (
        labels == ["modelled"] * 4
    )  # nothing was read from the owner or from Qloo, so nothing is measured or observed


async def test_the_modes_decide_which_tools_the_model_has_and_what_it_is_told(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    done = [tool("answer", verdict="Done.", items=[], evidence=[], what_would_change=[])]
    culture = ScriptedModel(done)
    await ask(world, owner, venue, culture, "Anything?", "culture")
    crowd_model = ScriptedModel(done)
    await ask(world, owner, venue, crowd_model, "Anything?", "crowd")

    def names(model: ScriptedModel) -> set[str]:
        return {t["name"] for t in model.requests[0]["tools"]}

    assert names(culture) == {
        "resolve_entity",
        "related",
        "places_nearby",
        "verify_place",
        "answer",
    }
    assert names(crowd_model) == names(culture) | {
        "fit_verdict",
        "my_groups",
        "my_hours",
        "my_moves",
    }
    system = culture.requests[0]["system"]
    assert "The Lantern" in system and "live music venue" in system and "ask the culture" in system
    assert "no access to this venue's own data" in system
    assert "ask about my crowd" in crowd_model.requests[0]["system"]
    # the question is data in the user's message, never part of the instructions
    assert (
        "Anything?" in culture.requests[0]["messages"][0]["content"] and "Anything?" not in system
    )


async def test_a_tool_the_mode_does_not_allow_is_refused_even_if_the_model_asks_for_it(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    seen: list[dict[str, Any]] = []

    def second(messages: list[dict[str, Any]]) -> Blocks:
        seen.extend(results_of(messages))
        return [
            tool(
                "answer",
                verdict="I could not read your crowd here.",
                items=[],
                evidence=[],
                what_would_change=[],
            )
        ]

    model = ScriptedModel([tool("my_groups"), tool("delete_everything")], second)
    evs, _ = await ask(world, owner, venue, model, "Who are my guests?", "culture")
    assert seen == [{"error": "unknown tool"}, {"error": "unknown tool"}]
    assert answer_of(evs)["stats"]["tools"] == []  # neither ran


async def test_a_seed_that_no_tool_returned_is_refused_before_qloo_is_asked(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    known_world(world, admin)
    seen: list[dict[str, Any]] = []

    def after(messages: list[dict[str, Any]]) -> Blocks:
        seen.extend(results_of(messages))
        return [
            tool("answer", verdict="Nothing found.", items=[], evidence=[], what_would_change=[])
        ]

    model = ScriptedModel(
        [tool("related", type="artist", seeds=[str(uuid.uuid4())], take=5)], after
    )
    before = len(world.qloo.calls)
    evs, _ = await ask(world, owner, venue, model, "Who is like somebody?")
    assert "was not returned by any tool" in seen[0]["error"]
    assert len(world.qloo.calls) == before  # not one call reached Qloo
    assert answer_of(evs)["stats"]["qloo_calls"] == 0


async def test_the_qloo_budget_for_a_question_is_enforced_and_the_model_is_told(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    known_world(world, admin)
    lookups = [[tool("resolve_entity", text=f"Quiet Act {i}", type="artist")] for i in range(11)]
    told: list[dict[str, Any]] = []

    def last(messages: list[dict[str, Any]]) -> Blocks:
        told.extend(results_of(messages))
        return [
            tool("answer", verdict="Out of budget.", items=[], evidence=[], what_would_change=[])
        ]

    model = ScriptedModel(*lookups, last)
    evs, _ = await ask(world, owner, venue, model, "Look up lots.")
    doc = answer_of(evs)
    assert doc["stats"]["qloo_calls"] == 10  # the tenth is the last one allowed
    assert "budget for this question is used up" in told[0]["error"]
    searches = [c for c in world.qloo.calls if c[0] == "/search"]
    assert len(searches) == 10


async def test_a_model_that_never_calls_the_answer_tool_is_asked_once_then_replaced_by_a_plain_list(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    known_world(world, admin)
    model = ScriptedModel(
        [tool("resolve_entity", text="Quiet Act", type="artist")],
        [said("Quiet Act is lovely, you should book it.")],
        [said("As I said.")],
    )
    evs, _ = await ask(world, owner, venue, model, "Who should I book?")
    doc = answer_of(evs)
    assert doc["kind"] == "template"
    assert doc["verdict"].startswith("Here is what Qloo returned for your question, unranked.")
    assert [i["name"] for i in doc["items"]] == [
        "Quiet Act"
    ]  # what a tool did return, and nothing the model said
    assert len(model.requests) == 3
    repair = model.requests[2]["messages"][-1]
    assert repair == {
        "role": "user",
        "content": "Finish by calling the answer tool with what you have.",
    }
    assert admin.execute("SELECT kind FROM ask_answer").fetchone() == ("template",)


async def test_one_missed_answer_call_is_forgiven(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    model = ScriptedModel(
        [said("Thinking out loud.")],
        [tool("answer", verdict="Short answer.", items=[], evidence=[], what_would_change=[])],
    )
    evs, _ = await ask(world, owner, venue, model, "Quick one?")
    doc = answer_of(evs)
    assert (
        doc["kind"] == "model"
        and doc["verdict"] == "Short answer."
        and doc["stats"]["model_turns"] == 2
    )


async def test_when_the_model_service_fails_part_way_the_owner_still_gets_what_qloo_returned(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    known_world(world, admin)
    model = ScriptedModel([tool("resolve_entity", text="Quiet Act", type="artist")], None, None)
    evs, _ = await ask(world, owner, venue, model, "Who is Quiet Act?")
    doc = answer_of(evs)
    assert doc["kind"] == "template" and [i["name"] for i in doc["items"]] == ["Quiet Act"]
    assert "AI service" in doc["verdict"]


async def test_with_nothing_found_and_no_answer_the_owner_is_told_so_plainly(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    model = ScriptedModel(None, None)
    evs, _ = await ask(world, owner, venue, model, "Anything at all?")
    doc = answer_of(evs)
    assert doc["kind"] == "template" and doc["items"] == []
    assert doc["verdict"].startswith("Nothing could be found for that question.")
    assert doc["not_enough_data"]["unlock"] == ["Try a more specific question."]


async def test_places_come_only_from_the_venues_own_area_and_a_named_place_must_be_confirmed(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    local = {
        "name": "Corner Tap",
        "entity_id": str(uuid.uuid4()),
        "types": ["urn:entity:place"],
        "popularity": 0.2,
        "tags": [],
        "location": {"lat": 51.5004, "lon": -0.12},
        "properties": {"address": "1 Local Road", "is_closed": False},
    }
    far = {
        **local,
        "name": "Corner Tap",
        "entity_id": str(uuid.uuid4()),
        "location": {"lat": 40.7, "lon": -74.0},
    }
    world.qloo.catalogue = [far, local]
    got: list[dict[str, Any]] = []

    def after(messages: list[dict[str, Any]]) -> Blocks:
        got.extend(results_of(messages))
        return [
            tool(
                "answer",
                verdict="Corner Tap is open nearby.",
                items=[{"entity_id": got[0]["items"][0]["id"], "reason": "Inside your area."}],
                evidence=[{"label": "observed", "text": "Qloo returned three bars within 800 m."}],
                what_would_change=[],
            )
        ]

    model = ScriptedModel(
        [
            tool("places_nearby", category="bar", take=5),
            tool("verify_place", name="Corner Tap"),
            tool("verify_place", name="Nowhere Cellar"),
        ],
        after,
    )
    evs, _ = await ask(world, owner, venue, model, "What bars are near me?")
    places, found, not_found = got
    assert len(places["items"]) == 3 and places["area"] == "within 800 m of the venue"
    assert all(p["distance_m"] <= 816 for p in places["items"])
    assert (
        found["found"] is True and found["place"]["id"] == local["entity_id"]
    )  # the New York one is not in the area
    assert not_found["found"] is False
    doc = answer_of(evs)
    assert [(i["name"], i["provenance"]) for i in doc["items"]] == [("Invented Bar 0", "surfaced")]
    assert doc["warnings"] == [
        "Place data outside the United States is thinner: check each place is open before acting."
    ]
    assert doc["stats"]["qloo_calls"] == 3


async def test_a_venue_with_no_position_cannot_search_places(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    b = (await owner.post("/businesses", json={"name": "No Map", "type": "bar"})).json()["id"]
    await owner.post(f"/businesses/{b}/locations", json={"name": "Door"})
    got: list[dict[str, Any]] = []

    def after(messages: list[dict[str, Any]]) -> Blocks:
        got.extend(results_of(messages))
        return [
            tool(
                "answer",
                verdict="I could not look for places.",
                items=[],
                evidence=[],
                what_would_change=[],
            )
        ]

    model = ScriptedModel([tool("places_nearby", category="bar")], after)
    world.app.state.nigiwai.llm = model.client()
    res = await owner.client.post(
        f"/v1/tenants/{owner.tenant_id}/businesses/{b}/ask",
        json={"question": "Bars near me?", "mode": "culture"},
        headers=owner.headers,
    )
    assert res.status_code == 200 and "has no position yet" in got[0]["error"]


async def test_a_book_search_carries_the_coverage_warning_and_music_seeded_brands_carry_theirs(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    known_world(world, admin)
    model = ScriptedModel(
        [tool("resolve_entity", text="Quiet Act", type="artist")],
        lambda m: [
            tool("related", type="brand", seeds=[first_id(m)], take=3),
            tool("related", type="book", seeds=[first_id(m)], take=3),
        ],
        [
            tool(
                "answer",
                verdict="Some brands and books.",
                items=[],
                evidence=[],
                what_would_change=[],
            )
        ],
    )
    evs, _ = await ask(world, owner, venue, model, "Brands and books for fans of Quiet Act?")
    warnings = answer_of(evs)["warnings"]
    assert any("Brand suggestions seeded from music" in w for w in warnings)
    assert any("coverage of books is thin" in w for w in warnings)


async def test_when_qloo_is_down_the_tools_say_so_and_the_answer_carries_the_note(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    world.qloo.down = True
    told: list[dict[str, Any]] = []

    def after(messages: list[dict[str, Any]]) -> Blocks:
        told.extend(results_of(messages))
        return [
            tool(
                "answer",
                verdict="Qloo is not answering.",
                items=[],
                evidence=[],
                what_would_change=[],
            )
        ]

    model = ScriptedModel([tool("resolve_entity", text="Quiet Act", type="artist")], after)
    evs, _ = await ask(world, owner, venue, model, "Who is Quiet Act?")
    assert "could not answer this just now" in told[0]["error"]
    assert any("Qloo was slow or unavailable" in n for n in answer_of(evs)["notes"])


async def test_in_crowd_mode_the_model_reads_the_owners_own_groups_and_scores_an_act_against_them(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    await crowd(world, admin, owner, venue)
    quiet = known_world(world, admin)
    got: list[dict[str, Any]] = []

    def after_reads(messages: list[dict[str, Any]]) -> Blocks:
        got.extend(results_of(messages))
        return [tool("fit_verdict", entity_id=quiet)]

    def final(messages: list[dict[str, Any]]) -> Blocks:
        got.extend(results_of(messages))
        return [
            tool(
                "answer",
                verdict="Quiet Act suits your crowd well.",
                items=[{"entity_id": quiet, "reason": "It scored well for your groups."}],
                evidence=[
                    {"label": "measured", "text": "Your crowd has three groups."},
                    {"label": "modelled", "text": "The Soundcheck score is a fit, not a forecast."},
                ],
                what_would_change=["More scans would firm up the groups."],
            )
        ]

    model = ScriptedModel(
        [
            tool("resolve_entity", text="Quiet Act", type="artist"),
            tool("my_groups"),
            tool("my_hours"),
            tool("my_moves"),
        ],
        after_reads,
        final,
    )
    evs, _ = await ask(world, owner, venue, model, "Would Quiet Act suit my crowd?", "crowd")
    resolved, groups, hours, moves, fit = got
    assert resolved["items"][0]["name"] == "Quiet Act"
    assert (
        groups["label"] == "measured"
        and len(groups["groups"]) == 3
        and groups["groups"][0]["favourites"]
    )
    assert (
        hours["scans"] == 90
        and hours["label"] == "measured"
        and hours["opening_hours_set"] is False
    )
    assert moves == {"moves": [], "label": "measured"}
    assert fit["status"] == "ok" and 0 <= fit["score"] <= 100 and len(fit["groups"]) == 3
    doc = answer_of(evs)
    assert doc["kind"] == "model" and doc["stats"]["qloo_calls"] == 1 + tools_fit_cost()
    assert [e["label"] for e in doc["evidence"]] == [
        "measured",
        "modelled",
    ]  # earned: the owner's data was read
    assert doc["items"][0]["name"] == "Quiet Act"
    # the Soundcheck's own Qloo calls are in the trace the owner can reopen
    trace = (
        await owner.client.get(
            f"/v1/tenants/{owner.tenant_id}{base(owner, venue)}/ask/{doc['id']}/trace"
        )
    ).json()
    assert {c["purpose"] for c in trace} >= {"ask", "fit"}


def tools_fit_cost() -> int:
    from nigiwai_api.services import ask_tools

    return ask_tools.FIT_COST


async def test_asking_without_an_ai_service_is_refused_up_front_with_a_plain_reason(
    world: World,
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    assert world.app.state.nigiwai.llm is None
    res = await owner.client.post(
        f"/v1/tenants/{owner.tenant_id}{base(owner, venue)}/ask",
        json={"question": "Hello?", "mode": "culture"},
        headers=owner.headers,
    )
    assert res.status_code == 503 and "needs an AI service" in res.json()["detail"]


async def test_junk_questions_are_refused_before_the_model_is_called(world: World) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    model = ScriptedModel()
    world.app.state.nigiwai.llm = model.client()
    root = f"/v1/tenants/{owner.tenant_id}{base(owner, venue)}/ask"
    for body in (
        {"question": "", "mode": "culture"},
        {"question": "   ", "mode": "culture"},
        {"question": "x" * 601, "mode": "culture"},
        {"question": "ok", "mode": "chat"},
        {"question": "ok"},
        {"mode": "crowd"},
        {"question": "ok", "mode": "crowd", "extra": 1},
        {"question": 7, "mode": "crowd"},
    ):
        res = await owner.client.post(root, json=body, headers=owner.headers)
        assert res.status_code == 422, body
    assert (
        await owner.client.post(
            f"/v1/tenants/{owner.tenant_id}/businesses/{uuid.uuid4()}/ask",
            json={"question": "ok", "mode": "crowd"},
            headers=owner.headers,
        )
    ).status_code == 404
    assert model.requests == []


def test_control_characters_and_long_runs_are_cleaned_from_a_question() -> None:
    assert service.clean_question("  who\x00 is\n\n  like   X\x07? ") == "who is like X ?".replace(
        " ?", "?"
    )
    assert len(service.clean_question("a" * 5000)) == service.QUESTION_MAX


async def test_each_account_has_a_daily_allowance_of_questions(
    make_world: Any, admin: psycopg.Connection[Any]
) -> None:
    async with make_world(ask_daily_limit=2) as world:
        owner = await sign_up(world)
        venue = await make_venue(owner)
        done = [tool("answer", verdict="Done.", items=[], evidence=[], what_would_change=[])]
        for _ in range(2):
            await ask(world, owner, venue, ScriptedModel(done), "A question?")
        world.app.state.nigiwai.llm = ScriptedModel(done).client()
        res = await owner.client.post(
            f"/v1/tenants/{owner.tenant_id}{base(owner, venue)}/ask",
            json={"question": "One more?", "mode": "culture"},
            headers=owner.headers,
        )
        assert res.status_code == 429 and "daily limit" in res.json()["detail"]
        assert admin.execute("SELECT count(*) FROM ask_answer").fetchone() == (2,)


async def test_the_owners_answers_are_private_to_their_account(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    other = await sign_up(world)
    venue = await make_venue(owner)
    model = ScriptedModel(
        [tool("answer", verdict="Private.", items=[], evidence=[], what_would_change=[])]
    )
    evs, _ = await ask(world, owner, venue, model, "A private question?")
    answer_id = answer_of(evs)["id"]
    root = f"/v1/tenants/{owner.tenant_id}{base(owner, venue)}/ask"
    for path in ("", f"/{answer_id}", f"/{answer_id}/trace"):
        assert (await other.client.get(root + path)).status_code == 404
        assert (await world.client().get(root + path)).status_code == 401
    assert (
        await other.client.post(
            root, json={"question": "hi", "mode": "culture"}, headers=other.headers
        )
    ).status_code == 404
    assert (
        await world.client().post(root, json={"question": "hi", "mode": "culture"})
    ).status_code == 401
    # a business that is not yours is not found even through your own account
    mine = await sign_up(world)
    assert (await mine.get(f"{base(owner, venue)}/ask/{answer_id}")).status_code == 404
    assert (await mine.get(f"/businesses/{uuid.uuid4()}/ask/{uuid.uuid4()}")).status_code == 404


async def test_the_groups_favourites_come_with_ids_to_seed_a_search_and_may_be_listed_as_the_owners_own_measured_data(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    await crowd(world, admin, owner, venue)
    known_world(world, admin)
    got: list[dict[str, Any]] = []
    favourite: list[str] = []

    def seed_a_search(messages: list[dict[str, Any]]) -> Blocks:
        groups = results_of(messages)[0]
        got.append(groups)
        favourite.append(groups["groups"][0]["favourites"][0]["id"])
        return [tool("related", type="artist", seeds=[favourite[0]], take=4)]

    def finish(messages: list[dict[str, Any]]) -> Blocks:
        got.append(results_of(messages)[0])
        surfaced = got[-1]["items"][0]["id"]
        return [
            tool(
                "answer",
                verdict="Try these.",
                items=[
                    {"entity_id": favourite[0], "reason": "They already love it."},
                    {"entity_id": surfaced, "reason": "Qloo links it to their favourites."},
                ],
                evidence=[{"label": "observed", "text": "Qloo returned neighbours."}],
                what_would_change=[],
            )
        ]

    model = ScriptedModel([tool("my_groups")], seed_a_search, finish)
    evs, _ = await ask(world, owner, venue, model, "Who is like my crowd?", "crowd")
    groups = got[0]
    assert all(
        isinstance(f["id"], str) and f["name"] for g in groups["groups"] for f in g["favourites"]
    )
    # no name lookup was needed: the seed came straight from the group
    assert not [c for c in world.qloo.calls if c[0] == "/search"]
    assert got[1]["items"], "the related call answered for a favourite used as a seed"
    doc = answer_of(evs)
    by_id = {i["entity_id"]: i for i in doc["items"]}
    assert set(by_id) == {favourite[0], got[1]["items"][0]["id"]}
    mine = by_id[favourite[0]]
    assert (mine["provenance"], mine["label"]) == (
        "yours",
        "measured",
    )  # the owner's own survey, counted
    assert mine["detail"].startswith("a favourite of ")
    assert by_id[got[1]["items"][0]["id"]]["provenance"] == "surfaced"
    assert doc["rejected"] == [] and doc["kind"] == "model"


async def test_a_model_running_out_of_turns_is_told_so_before_it_is_stopped(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    known_world(world, admin)
    seen_nudges: list[int] = []

    def looking(messages: list[dict[str, Any]]) -> Blocks:
        last = messages[-1]["content"]
        texts = [b["text"] for b in last if isinstance(b, dict) and b.get("type") == "text"]
        seen_nudges.append(len([t for t in texts if "turns left" in t]))
        return [tool("resolve_entity", text="Quiet Act", type="artist")]

    from nigiwai_api.services import ask as ask_service

    model = ScriptedModel(
        *([[tool("resolve_entity", text="Quiet Act", type="artist")]] + [looking] * 11)
    )
    evs, _ = await ask(world, owner, venue, model, "Keep looking.")
    assert answer_of(evs)["kind"] == "template"  # it never answered, so it got the plain list
    cut = ask_service.MAX_TURNS - 4  # the hint is added after the turn that leaves three
    assert not any(seen_nudges[:cut])  # no hint while there is plenty of room
    assert all(seen_nudges[cut:])  # and one on every turn near the end


async def test_an_answer_that_lists_nothing_after_qloo_returned_things_is_sent_back_once_for_its_items(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    quiet = known_world(world, admin)
    told: list[dict[str, Any]] = []

    def empty_first(messages: list[dict[str, Any]]) -> Blocks:
        found = results_of(messages)[0]
        told.append(found)
        return [
            tool("answer", verdict="Plenty to try.", items=[], evidence=[], what_would_change=[])
        ]

    def then_list(messages: list[dict[str, Any]]) -> Blocks:
        told.append(results_of(messages)[0])
        first = told[0]["items"][0]["id"]
        return [
            tool(
                "answer",
                verdict="Try these.",
                items=[{"entity_id": first, "reason": "Qloo links it."}],
                evidence=[{"label": "observed", "text": "Qloo returned neighbours."}],
                what_would_change=[],
            )
        ]

    model = ScriptedModel(
        [tool("resolve_entity", text="Quiet Act", type="artist")],
        lambda m: [tool("related", type="artist", seeds=[first_id(m)], take=4)],
        empty_first,
        then_list,
    )
    evs, _ = await ask(world, owner, venue, model, "Who is like Quiet Act?")
    doc = answer_of(evs)
    assert "listed no items" in told[1]["error"]  # the model was told what was missing
    assert doc["kind"] == "model" and len(doc["items"]) == 1 and doc["verdict"] == "Try these."
    assert quiet  # (the known world was built)


async def test_a_second_empty_answer_is_accepted_not_asked_for_again_and_an_honest_nothing_is_not_pushed(
    world: World, admin: psycopg.Connection[Any]
) -> None:
    owner = await sign_up(world)
    venue = await make_venue(owner)
    known_world(world, admin)
    empty = tool(
        "answer", verdict="Nothing I would recommend.", items=[], evidence=[], what_would_change=[]
    )
    stated = tool(
        "answer",
        verdict="Not enough to go on.",
        items=[],
        evidence=[],
        what_would_change=[],
        not_enough_data={
            "reason": "Qloo has little on this.",
            "unlock": ["Ask about a bigger act."],
        },
    )
    seeded = [
        [tool("resolve_entity", text="Quiet Act", type="artist")],
        lambda m: [tool("related", type="artist", seeds=[first_id(m)], take=4)],
    ]
    twice = ScriptedModel(*seeded, [empty], [empty])
    evs, _ = await ask(world, owner, venue, twice, "Anything?")
    assert answer_of(evs)["kind"] == "model" and answer_of(evs)["items"] == []
    assert len(twice.requests) == 4  # one repair request, then it was accepted
    honest = ScriptedModel(*seeded, [stated])
    evs, _ = await ask(world, owner, venue, honest, "Anything else?")
    doc = answer_of(evs)
    assert (
        doc["not_enough_data"]["reason"] and len(honest.requests) == 3
    )  # said plainly, so not sent back
