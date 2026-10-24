"""The language model behind the "AI alone" comparison (PRD M23).

A thin wrapper over the Anthropic Messages API. The key is read from a file on the server and never leaves it. Every
failure becomes a plain `LlmUnavailable` with wording safe to show: the product keeps working without the model, and the
panel says why there is no AI answer. The comparison sends nothing about a venue or a guest, only an act's public name. Ask Nigiwai (`converse`) is the one
place a model sees more: the owner's question, and only what the tools it calls return.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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


def read_key(path: str | None) -> str | None:
    """The key from a `NAME=value` env file (any name containing KEY), or from a file holding only the key. With no
    file named, the ANTHROPIC_API_KEY environment variable, as the Qloo key can come from QLOO_API_KEY."""
    if not path:
        return os.environ.get("ANTHROPIC_API_KEY") or None
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


class LlmClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        base_url: str | None = None,
        timeout: float = 25.0,
        http_client: httpx2.AsyncClient | None = None,
    ) -> None:
        self.model = model
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=1,
            http_client=http_client,
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


def build_llm(
    key_file: str | None,
    model: str,
    *,
    base_url: str | None = None,
    timeout: float = 25.0,
) -> LlmClient | None:
    key = read_key(key_file)
    if key is None:
        return None
    return LlmClient(key, model, base_url=base_url, timeout=timeout)
