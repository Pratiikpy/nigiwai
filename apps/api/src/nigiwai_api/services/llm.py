"""The language model behind the "AI alone" comparison (PRD M23).

A thin wrapper over the Anthropic Messages API. The key is read from a file on the server and never leaves it. Every
failure becomes a plain `LlmUnavailable` with wording safe to show: the product keeps working without the model, and the
panel says why there is no AI answer. The comparison sends nothing about a venue or a guest, only an act's public name. Ask Nigiwai (`converse`) is the one
place a model sees more: the owner's question, and only what the tools it calls return.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import anthropic
import httpx2

log = logging.getLogger("nigiwai.llm")


class LlmUnavailable(Exception):
    """The model could not answer. The message is written for the person looking at the panel."""


@dataclass(frozen=True)
class LlmAnswer:
    text: str
    model: str
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass(frozen=True)
class Turn:
    """One model turn: its words, the tools it wants run, and the blocks to send back so the conversation continues."""

    text: str
    tool_calls: tuple[ToolCall, ...]
    stop_reason: str | None
    model: str
    input_tokens: int
    output_tokens: int
    content: list[dict[str, Any]]


def read_key(path: str | None, env_name: str = "ANTHROPIC_API_KEY") -> str | None:
    """The key from a `NAME=value` env file (any name containing KEY), or from a file holding only the key. With no
    file named, the environment variable `env_name`, as the Qloo key can come from QLOO_API_KEY."""
    if not path:
        return os.environ.get(env_name) or None
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError:
        return None
    for line in raw.splitlines():
        m = re.match(r"\s*(?:export\s+)?[A-Z0-9_]*KEY[A-Z0-9_]*\s*=\s*['\"]?([^'\"\s]+)", line)
        if m:
            return m.group(1)
    plain = raw.strip()
    return plain if plain and "\n" not in plain and "=" not in plain else None


class ModelClient(Protocol):
    """What the rest of the product needs from a language model, whichever service is behind it."""

    model: str

    async def complete(self, system: str, user: str, *, max_tokens: int = 400) -> LlmAnswer: ...

    async def converse(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        max_tokens: int = 1500,
    ) -> Turn: ...

    async def aclose(self) -> None: ...


class LlmClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        base_url: str | None = None,
        timeout: float = 25.0,
        http_client: httpx2.AsyncClient | None = None,
        workspace_id: str | None = None,
    ) -> None:
        self.model = model
        # a key that is not scoped to one workspace must say which workspace a request is for
        headers = {"anthropic-workspace-id": workspace_id} if workspace_id else None
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=1,
            http_client=http_client,
            default_headers=headers,
        )

    async def _send(self, **request: Any) -> Any:
        """One call to the Messages API; every failure becomes an `LlmUnavailable` with wording safe to show."""
        try:
            return await self._client.messages.create(model=self.model, **request)
        except anthropic.AuthenticationError as exc:
            log.error("the model key was refused (%s)", type(exc).__name__)
            raise LlmUnavailable("The AI service refused this server's key.") from exc
        except anthropic.RateLimitError as exc:
            raise LlmUnavailable("The AI service is busy right now.") from exc
        except (anthropic.APITimeoutError, anthropic.APIConnectionError) as exc:
            raise LlmUnavailable("The AI service did not answer in time.") from exc
        except anthropic.APIStatusError as exc:
            log.warning("model call failed with status %s", exc.status_code)
            raise LlmUnavailable("The AI service could not answer.") from exc

    async def complete(self, system: str, user: str, *, max_tokens: int = 400) -> LlmAnswer:
        message = await self._send(
            max_tokens=max_tokens, system=system, messages=[{"role": "user", "content": user}]
        )
        text = "".join(block.text for block in message.content if block.type == "text").strip()
        if not text:
            raise LlmUnavailable("The AI service returned an empty answer.")
        return LlmAnswer(
            text, message.model, message.usage.input_tokens, message.usage.output_tokens
        )

    async def converse(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        max_tokens: int = 1500,
    ) -> Turn:
        """One turn of a tool-using conversation. The caller runs the tools and sends the results back."""
        message = await self._send(
            max_tokens=max_tokens, system=system, messages=messages, tools=tools
        )
        blocks: list[dict[str, Any]] = []
        calls: list[ToolCall] = []
        words: list[str] = []
        for block in message.content:
            if block.type == "text":
                words.append(block.text)
                blocks.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                args = block.input if isinstance(block.input, dict) else {}
                calls.append(ToolCall(block.id, block.name, args))
                blocks.append(
                    {"type": "tool_use", "id": block.id, "name": block.name, "input": args}
                )
        return Turn(
            "".join(words).strip(),
            tuple(calls),
            message.stop_reason,
            message.model,
            message.usage.input_tokens,
            message.usage.output_tokens,
            blocks,
        )

    async def aclose(self) -> None:
        await self._client.close()


class OpenAiClient:
    """The same surface over any OpenAI-compatible chat completions service (a hosted open model, a gateway, a local server).

    The rest of the product speaks in Anthropic-style blocks (text, tool_use, tool_result); this class translates them to chat
    messages and tool calls and back, so Ask, the onboarding interview and the AI-alone panel run unchanged on either service.
    `extra_body` is merged into every request (for example `{"chat_template_kwargs": {"enable_thinking": false}}` for a model
    that otherwise spends its tokens thinking)."""

    RETRY_AFTER = 2.0

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        base_url: str,
        timeout: float = 25.0,
        http_client: httpx2.AsyncClient | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> None:
        self.model = model
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._headers = {"authorization": f"Bearer {api_key}", "content-type": "application/json"}
        self._extra = extra_body or {}
        self._http = http_client or httpx2.AsyncClient(timeout=timeout)
        self._owns_http = http_client is None

    @staticmethod
    def messages_for(system: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Anthropic-style conversation to chat messages. A tool_result becomes a `tool` message, which must follow the
        assistant message whose call it answers, so results are emitted before any plain user text."""
        out: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for m in messages:
            content = m["content"]
            if isinstance(content, str):
                out.append({"role": m["role"], "content": content})
                continue
            if m["role"] == "assistant":
                words = "".join(b.get("text", "") for b in content if b.get("type") == "text")
                calls = [
                    {
                        "id": b["id"],
                        "type": "function",
                        "function": {
                            "name": b["name"],
                            "arguments": json.dumps(b.get("input") or {}),
                        },
                    }
                    for b in content
                    if b.get("type") == "tool_use"
                ]
                message: dict[str, Any] = {"role": "assistant", "content": words or None}
                if calls:
                    message["tool_calls"] = calls
                out.append(message)
                continue
            for b in content:
                if b.get("type") == "tool_result":
                    body = b.get("content")
                    out.append(
                        {
                            "role": "tool",
                            "tool_call_id": b["tool_use_id"],
                            "content": body if isinstance(body, str) else json.dumps(body),
                        }
                    )
            texts = [b["text"] for b in content if b.get("type") == "text"]
            if texts:
                out.append({"role": "user", "content": "\n".join(texts)})
        return out

    @staticmethod
    def tools_for(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema") or {"type": "object", "properties": {}},
                },
            }
            for t in tools
        ]

    async def _send(self, body: dict[str, Any]) -> dict[str, Any]:
        """One request, retried once after a short wait when the service is busy or briefly down. Every failure becomes an
        `LlmUnavailable` with wording safe to show."""
        payload = {"model": self.model, **self._extra, **body}
        unreadable = "The AI service answered in a form that could not be read."
        last: LlmUnavailable | None = None
        for attempt in range(2):
            try:
                response = await self._http.post(self._url, headers=self._headers, json=payload)
            except (httpx2.TimeoutException, httpx2.NetworkError) as exc:
                last = LlmUnavailable("The AI service did not answer in time.")
                last.__cause__ = exc
            else:
                status = response.status_code
                if status == 200:
                    try:
                        data = response.json()
                    except ValueError as exc:
                        raise LlmUnavailable(unreadable) from exc
                    if not isinstance(data, dict) or not data.get("choices"):
                        raise LlmUnavailable(unreadable)
                    return data
                if status in (401, 403):
                    log.error("the model key was refused (status %s)", status)
                    raise LlmUnavailable("The AI service refused this server's key.")
                if status == 429:
                    last = LlmUnavailable("The AI service is busy right now.")
                elif status >= 500:
                    last = LlmUnavailable("The AI service could not answer.")
                else:
                    log.warning("model call failed with status %s", status)
                    raise LlmUnavailable("The AI service could not answer.")
            if attempt == 0:
                await asyncio.sleep(self.RETRY_AFTER)
        assert last is not None
        raise last

    async def complete(self, system: str, user: str, *, max_tokens: int = 400) -> LlmAnswer:
        data = await self._send(
            {
                "max_tokens": max_tokens,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            }
        )
        text = (data["choices"][0].get("message", {}).get("content") or "").strip()
        if not text:
            raise LlmUnavailable("The AI service returned an empty answer.")
        usage = data.get("usage") or {}
        return LlmAnswer(
            text,
            str(data.get("model") or self.model),
            int(usage.get("prompt_tokens") or 0),
            int(usage.get("completion_tokens") or 0),
        )

    async def converse(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        max_tokens: int = 1500,
    ) -> Turn:
        data = await self._send(
            {
                "max_tokens": max_tokens,
                "messages": self.messages_for(system, messages),
                "tools": self.tools_for(tools),
                "tool_choice": "auto",
            }
        )
        choice = data["choices"][0]
        message = choice.get("message") or {}
        words = (message.get("content") or "").strip()
        blocks: list[dict[str, Any]] = []
        calls: list[ToolCall] = []
        if words:
            blocks.append({"type": "text", "text": words})
        for raw in message.get("tool_calls") or []:
            function = raw.get("function") or {}
            try:
                args = json.loads(function.get("arguments") or "{}")
            except ValueError:
                args = {}
            if not isinstance(args, dict):
                args = {}
            call_id = str(raw.get("id") or f"call_{uuid.uuid4().hex[:12]}")
            name = str(function.get("name") or "")
            calls.append(ToolCall(call_id, name, args))
            blocks.append({"type": "tool_use", "id": call_id, "name": name, "input": args})
        if not words and not calls:
            raise LlmUnavailable("The AI service returned an empty answer.")
        finish = choice.get("finish_reason")
        usage = data.get("usage") or {}
        return Turn(
            words,
            tuple(calls),
            "tool_use" if calls else ("max_tokens" if finish == "length" else "end_turn"),
            str(data.get("model") or self.model),
            int(usage.get("prompt_tokens") or 0),
            int(usage.get("completion_tokens") or 0),
            blocks,
        )

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()


def build_llm(
    key_file: str | None,
    model: str,
    *,
    provider: str = "anthropic",
    base_url: str | None = None,
    timeout: float = 25.0,
    workspace_id: str | None = None,
    extra_body: dict[str, Any] | None = None,
) -> ModelClient | None:
    """The configured model client, or None when there is no key (the product then says so where the model would speak)."""
    if provider == "openai":
        key = read_key(key_file, "NIGIWAI_LLM_API_KEY")
        if key is None:
            return None
        if not base_url:
            log.warning(
                "an OpenAI-compatible model needs NIGIWAI_LLM_BASE_URL; none is set, so there is no model"
            )
            return None
        return OpenAiClient(key, model, base_url=base_url, timeout=timeout, extra_body=extra_body)
    key = read_key(key_file)
    if key is None:
        return None
    return LlmClient(key, model, base_url=base_url, timeout=timeout, workspace_id=workspace_id)
