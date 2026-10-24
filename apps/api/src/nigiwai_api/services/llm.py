"""The language model behind the "AI alone" comparison (PRD M23).

A thin wrapper over the Anthropic Messages API. The key is read from a file on the server and never leaves it. Every
failure becomes a plain `LlmUnavailable` with wording safe to show: the product keeps working without the model, and the
panel says why there is no AI answer. Nothing about a venue or a guest is ever sent: only an act's public name.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

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

    async def complete(self, system: str, user: str, *, max_tokens: int = 400) -> LlmAnswer:
        try:
            message = await self._client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
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
        text = "".join(block.text for block in message.content if block.type == "text").strip()
        if not text:
            raise LlmUnavailable("The AI service returned an empty answer.")
        return LlmAnswer(
            text, message.model, message.usage.input_tokens, message.usage.output_tokens
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
