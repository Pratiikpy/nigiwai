"""REST transport over httpx. Full fidelity: it returns `warnings` and the rate-limit headers."""

from __future__ import annotations

import json
import time

import httpx

from ..errors import QlooAuthError, TransportError
from ..requests import Params
from .base import RawResponse

USER_AGENT = "nigiwai-qloo-guard/0.1"
_RATE_HEADERS = (
    "x-second-ratelimit-limit",
    "x-second-ratelimit-remaining",
    "x-second-ratelimit-reset",
    "x-month-ratelimit-limit",
    "x-month-ratelimit-remaining",
    "x-month-ratelimit-reset",
)


class RestTransport:
    name = "rest"

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout_s: float = 20.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(timeout_s),
            headers={"X-Api-Key": api_key, "Accept": "application/json", "User-Agent": USER_AGENT},
        )

    def supports(self, path: str, params: Params) -> bool:
        return True

    async def get(self, path: str, params: Params) -> RawResponse:
        t0 = time.monotonic()
        try:
            query: list[tuple[str, str | int | float | bool | None]] = list(params)
            resp = await self._client.get(path, params=query)
        except httpx.TimeoutException as exc:
            raise TransportError("qloo request timed out", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise TransportError(
                f"qloo request failed: {type(exc).__name__}", retryable=True
            ) from exc
        elapsed = int((time.monotonic() - t0) * 1000)
        headers = {k.lower(): v for k, v in resp.headers.items() if k.lower() in _RATE_HEADERS}
        text = resp.content.decode("utf-8", errors="replace")  # explicit UTF-8, never the locale
        try:
            body = json.loads(text) if text.strip() else None
        except json.JSONDecodeError:
            body = None
        if resp.status_code in (401, 403):
            raise QlooAuthError(
                f"qloo rejected the credential ({resp.status_code})", resp.status_code
            )
        return RawResponse(
            status=resp.status_code,
            body=body,
            headers=headers,
            elapsed_ms=elapsed,
            transport=self.name,
            text="" if body is not None else text[:200],
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
