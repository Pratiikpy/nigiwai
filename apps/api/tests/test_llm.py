"""The model client's own behaviour, against a scripted transport: the key file formats it reads, the workspace header a key that is
not scoped to one workspace needs, and how each kind of failure is worded. No network and no real key."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx2
import pytest
from nigiwai_api.services.llm import LlmClient, LlmUnavailable, OpenAiClient, build_llm, read_key


def ok_message(text: str = "ok") -> dict[str, Any]:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-test-1",
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 3, "output_tokens": 1},
    }


def client(handler: Any, workspace_id: str | None = None) -> LlmClient:
    return LlmClient(
        "sk-test-key-not-real",
        "claude-test-1",
        base_url="http://model.test",
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
        workspace_id=workspace_id,
    )


async def test_a_workspace_id_is_sent_on_every_request_and_nothing_extra_without_one() -> None:
    seen: list[dict[str, str]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(dict(request.headers))
        return httpx2.Response(200, json=ok_message())

    scoped = client(handler, "wrkspc_test_0123")
    assert (await scoped.complete("s", "u")).text == "ok"
    assert seen[-1]["anthropic-workspace-id"] == "wrkspc_test_0123"
    plain = client(handler)
    await plain.complete("s", "u")
    assert "anthropic-workspace-id" not in seen[-1]


async def test_every_failure_becomes_plain_words_and_never_carries_the_key_or_the_services_text() -> (
    None
):
    cases = {
        401: "refused this server's key",
        429: "busy right now",
        400: "could not answer",
        500: "could not answer",
    }
    for status, words in cases.items():

        def handler(_r: httpx2.Request, status: int = status) -> httpx2.Response:
            return httpx2.Response(
                status,
                json={
                    "type": "error",
                    "error": {"type": "x", "message": "sk-test-key-not-real leaked"},
                },
            )

        with pytest.raises(LlmUnavailable) as caught:
            await client(handler).complete("s", "u")
        assert words in str(caught.value), (status, str(caught.value))
        assert "sk-test" not in str(caught.value) and "leaked" not in str(caught.value)


async def test_an_empty_answer_is_a_failure_not_a_blank_panel() -> None:
    def handler(_r: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=ok_message("   "))

    with pytest.raises(LlmUnavailable, match="empty answer"):
        await client(handler).complete("s", "u")


def test_a_key_is_read_from_an_env_file_or_a_file_holding_only_the_key(tmp_path: Path) -> None:
    env = tmp_path / "a.env"
    env.write_text("# a note\nANTHROPIC_API_KEY='sk-ant-aaa'\n", encoding="utf-8")
    assert read_key(str(env)) == "sk-ant-aaa"
    exported = tmp_path / "b.env"
    exported.write_text("export OTHER_KEY=sk-ant-bbb\n", encoding="utf-8")
    assert read_key(str(exported)) == "sk-ant-bbb"
    bare = tmp_path / "c.txt"
    bare.write_text("sk-ant-ccc\n", encoding="utf-8")
    assert read_key(str(bare)) == "sk-ant-ccc"
    junk = tmp_path / "d.txt"
    junk.write_text("not a key at all = nope\nmore\n", encoding="utf-8")
    assert read_key(str(junk)) is None
    assert read_key(str(tmp_path / "missing.env")) is None
    assert build_llm(str(tmp_path / "missing.env"), "claude-test-1") is None


async def test_the_workspace_id_reaches_the_client_the_app_builds(tmp_path: Path) -> None:
    env = tmp_path / "k.env"
    env.write_text("ANTHROPIC_API_KEY=sk-ant-test\n", encoding="utf-8")
    built = build_llm(str(env), "claude-test-1", workspace_id="wrkspc_x")
    assert built is not None
    assert built._client.default_headers["anthropic-workspace-id"] == "wrkspc_x"
    await built.aclose()
    assert json.dumps(ok_message())  # the fixture is valid JSON


# ------------------------------------------------------------------------------------- OpenAI-compatible services
def chat(message: dict[str, Any], finish: str = "stop") -> dict[str, Any]:
    return {
        "model": "vendor/some-model",
        "choices": [
            {"index": 0, "message": {"role": "assistant", **message}, "finish_reason": finish}
        ],
        "usage": {"prompt_tokens": 11, "completion_tokens": 5},
    }


def chat_client(handler: Any, **kw: Any) -> OpenAiClient:
    c = OpenAiClient(
        "sk-test-key-not-real",
        "vendor/some-model",
        base_url="http://model.test/v1/",
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
        **kw,
    )
    c.RETRY_AFTER = 0.0
    return c


async def test_a_plain_completion_goes_to_chat_completions_with_the_extra_body_and_reads_the_text() -> (
    None
):
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=chat({"content": " ok "}))

    c = chat_client(handler, extra_body={"chat_template_kwargs": {"enable_thinking": False}})
    answer = await c.complete("be brief", "say ok", max_tokens=33)
    assert (answer.text, answer.model, answer.input_tokens, answer.output_tokens) == (
        "ok",
        "vendor/some-model",
        11,
        5,
    )
    request = seen[0]
    assert str(request.url) == "http://model.test/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer sk-test-key-not-real"
    body = json.loads(request.content)
    assert body["model"] == "vendor/some-model" and body["max_tokens"] == 33
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert body["messages"] == [
        {"role": "system", "content": "be brief"},
        {"role": "user", "content": "say ok"},
    ]


def test_anthropic_style_blocks_become_chat_messages_and_tools_become_functions() -> None:
    history: list[dict[str, Any]] = [
        {"role": "user", "content": "Question from the owner: who comes on Fridays?"},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Let me look."},
                {"type": "tool_use", "id": "call_1", "name": "my_groups", "input": {}},
                {"type": "tool_use", "id": "call_2", "name": "my_hours", "input": {"day": "fri"}},
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "call_1", "content": '{"groups": 3}'},
                {
                    "type": "tool_result",
                    "tool_use_id": "call_2",
                    "content": {"open": True},
                    "is_error": False,
                },
            ],
        },
        {"role": "assistant", "content": [{"type": "text", "text": "(no text)"}]},
        {"role": "user", "content": "Finish by calling the answer tool with what you have."},
    ]
    out = OpenAiClient.messages_for("SYSTEM", history)
    assert out[0] == {"role": "system", "content": "SYSTEM"}
    assert out[1] == {"role": "user", "content": "Question from the owner: who comes on Fridays?"}
    assistant = out[2]
    assert assistant["role"] == "assistant" and assistant["content"] == "Let me look."
    assert [c["id"] for c in assistant["tool_calls"]] == ["call_1", "call_2"]
    assert json.loads(assistant["tool_calls"][1]["function"]["arguments"]) == {"day": "fri"}
    assert out[3] == {"role": "tool", "tool_call_id": "call_1", "content": '{"groups": 3}'}
    assert out[4] == {"role": "tool", "tool_call_id": "call_2", "content": '{"open": true}'}
    assert out[5] == {"role": "assistant", "content": "(no text)"}
    assert out[6]["role"] == "user"
    specs = OpenAiClient.tools_for(
        [
            {
                "name": "answer",
                "description": "Finish.",
                "input_schema": {"type": "object", "properties": {"verdict": {"type": "string"}}},
            }
        ]
    )
    assert specs == [
        {
            "type": "function",
            "function": {
                "name": "answer",
                "description": "Finish.",
                "parameters": {"type": "object", "properties": {"verdict": {"type": "string"}}},
            },
        }
    ]


async def test_tool_calls_are_read_back_as_blocks_with_their_arguments_parsed() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        assert body["tool_choice"] == "auto" and body["tools"][0]["function"]["name"] == "answer"
        return httpx2.Response(
            200,
            json=chat(
                {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "c9",
                            "type": "function",
                            "function": {
                                "name": "answer",
                                "arguments": '{"verdict": "Fridays are indie."}',
                            },
                        },
                        {
                            "type": "function",
                            "function": {"name": "broken", "arguments": "{not json"},
                        },
                    ],
                },
                "tool_calls",
            ),
        )

    turn = await chat_client(handler).converse(
        "s",
        [{"role": "user", "content": "q"}],
        [{"name": "answer", "input_schema": {"type": "object"}}],
    )
    assert turn.stop_reason == "tool_use" and turn.text == ""
    assert [(c.id, c.name, c.input) for c in turn.tool_calls[:1]] == [
        ("c9", "answer", {"verdict": "Fridays are indie."})
    ]
    assert (
        turn.tool_calls[1].name == "broken" and turn.tool_calls[1].input == {}
    )  # unreadable arguments are an empty call, not a crash
    assert turn.tool_calls[1].id.startswith(
        "call_"
    )  # a missing id is made up so the result can be matched
    assert [b["type"] for b in turn.content] == ["tool_use", "tool_use"]
    assert (turn.input_tokens, turn.output_tokens) == (11, 5)


async def test_words_with_no_tool_call_end_the_turn_and_a_cut_off_answer_says_so() -> None:
    answers = iter([chat({"content": "Here you go."}), chat({"content": "Half an ans"}, "length")])
    c = chat_client(lambda _r: httpx2.Response(200, json=next(answers)))
    first = await c.converse("s", [{"role": "user", "content": "q"}], [])
    assert (first.text, first.stop_reason, first.tool_calls) == ("Here you go.", "end_turn", ())
    assert first.content == [{"type": "text", "text": "Here you go."}]
    second = await c.converse("s", [{"role": "user", "content": "q"}], [])
    assert second.stop_reason == "max_tokens"


async def test_a_reply_with_no_words_and_no_calls_is_a_failure_even_if_the_model_only_thought() -> (
    None
):
    def handler(_r: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200, json=chat({"content": None, "reasoning_content": "thinking..."}, "length")
        )

    c = chat_client(handler)
    with pytest.raises(LlmUnavailable, match="empty answer"):
        await c.complete("s", "u")
    with pytest.raises(LlmUnavailable, match="empty answer"):
        await c.converse("s", [{"role": "user", "content": "q"}], [])


async def test_a_busy_service_is_tried_once_more_then_reported_and_a_refused_key_is_not_retried() -> (
    None
):
    calls: list[int] = []

    def busy_then_fine(_r: httpx2.Request) -> httpx2.Response:
        calls.append(1)
        return (
            httpx2.Response(429, json={})
            if len(calls) == 1
            else httpx2.Response(200, json=chat({"content": "ok"}))
        )

    assert (await chat_client(busy_then_fine).complete("s", "u")).text == "ok"
    assert len(calls) == 2

    always: list[int] = []

    def busy(_r: httpx2.Request) -> httpx2.Response:
        always.append(1)
        return httpx2.Response(429, json={})

    with pytest.raises(LlmUnavailable, match="busy right now"):
        await chat_client(busy).complete("s", "u")
    assert len(always) == 2

    refused: list[int] = []

    def forbidden(_r: httpx2.Request) -> httpx2.Response:
        refused.append(1)
        return httpx2.Response(401, json={"detail": "sk-test-key-not-real"})

    with pytest.raises(LlmUnavailable, match="refused this server's key") as caught:
        await chat_client(forbidden).complete("s", "u")
    assert len(refused) == 1 and "sk-test" not in str(caught.value)


async def test_timeouts_and_unreadable_answers_are_plain_failures() -> None:
    def slow(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("timed out", request=request)

    with pytest.raises(LlmUnavailable, match="did not answer in time"):
        await chat_client(slow).complete("s", "u")

    for body in ({"no": "choices"}, "not an object at all"):
        with pytest.raises(LlmUnavailable, match="could not be read"):
            await chat_client(lambda _r, b=body: httpx2.Response(200, json=b)).complete("s", "u")
    with pytest.raises(LlmUnavailable, match="could not be read"):
        await chat_client(lambda _r: httpx2.Response(200, content=b"<html>")).complete("s", "u")
    with pytest.raises(LlmUnavailable, match="could not answer"):
        await chat_client(lambda _r: httpx2.Response(400, json={})).complete("s", "u")


def test_the_openai_provider_needs_a_key_and_a_base_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("NIGIWAI_LLM_API_KEY", raising=False)
    assert build_llm(None, "m", provider="openai", base_url="http://x/v1") is None  # no key
    monkeypatch.setenv("NIGIWAI_LLM_API_KEY", "sk-from-env")
    assert build_llm(None, "m", provider="openai") is None  # no base url
    built = build_llm(None, "m", provider="openai", base_url="http://x/v1", extra_body={"a": 1})
    assert isinstance(built, OpenAiClient) and built.model == "m"
    env = tmp_path / "n.env"
    env.write_text("OTHER=1\nNVIDIA_API_KEY=nvapi-file\n", encoding="utf-8")
    from_file = build_llm(str(env), "m", provider="openai", base_url="http://x/v1")
    assert (
        isinstance(from_file, OpenAiClient)
        and from_file._headers["authorization"] == "Bearer nvapi-file"
    )
    assert isinstance(build_llm(str(env), "m"), LlmClient)
