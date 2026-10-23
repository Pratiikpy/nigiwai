"""Transport over the Qloo harness CLI (`qloo api <command>`), the supported event surface.

Verified facts (2026-10-23, @qloo/qloo-harness 0.1.26):
- It prints entities already unwrapped and drops `warnings` and every response header.
- `entity` takes one id and has no `--params`, so batched `/entities` is not supported here.
- `insights --filter-location` maps to `filter.location.query` (trap 17), so exact areas are sent through
  `--params {"filter.location": "POINT(lon lat)"}` instead.
- Errors print {"error": true, "code": "API_ERROR", "message": "API request failed: 400 Bad Request"} and exit 5.
- `analyze` prints the full REST envelope; `search` and `tags` print a bare list.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import shutil
import signal
import sys
import time
from pathlib import Path
from typing import Any

from ..errors import QlooAuthError, TransportError
from ..requests import Params
from .base import RawResponse

_STATUS = re.compile(r"failed:\s*(\d{3})")


async def _terminate(proc: asyncio.subprocess.Process) -> None:
    """Kill the process and its children (npm shims start a second process), then reap it."""
    try:
        if os.name == "nt":
            killer = await asyncio.create_subprocess_exec(
                "taskkill",
                "/T",
                "/F",
                "/PID",
                str(proc.pid),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await killer.wait()
        elif sys.platform != "win32":
            os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
    # drain and reap so no pipe stays open
    with contextlib.suppress(TimeoutError, ProcessLookupError):
        await asyncio.wait_for(proc.communicate(), timeout=3.0)


class HarnessTransport:
    name = "harness"

    def __init__(
        self,
        base_url: str,
        api_key: str,
        command: tuple[str, ...] = ("qloo",),
        timeout_s: float = 20.0,
        home: str | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._command = command
        self._timeout_s = timeout_s
        self._home = home

    # -- capability -----------------------------------------------------------------------------------------
    def supports(self, path: str, params: Params) -> bool:
        names = {k for k, _ in params}
        if path in ("/search", "/v2/tags", "/v2/analysis/compare"):
            return True
        if path == "/v2/insights":
            if ("filter.type", "urn:demographics") in params:
                return False
            # Seeds can be dropped silently and only REST reports it, so seeded insights stay on REST.
            return "signal.interests.entities" not in names
        return False  # /entities is batched on REST; the CLI handles one id

    # -- request mapping ------------------------------------------------------------------------------------
    def argv(self, path: str, params: Params) -> list[str]:
        p = dict(params)
        if path == "/search":
            extra = {k: v for k, v in p.items() if k in ("types", "take", "page")}
            return ["api", "search", "-q", p["query"], "--params", json.dumps(extra), "--json"]
        if path == "/v2/tags":
            return ["api", "tags", "-q", p["filter.query"], "-n", p.get("take", "10"), "--json"]
        if path == "/v2/analysis/compare":
            return [
                "api",
                "analyze",
                "--a",
                p["a.signal.interests.entities"],
                "--b",
                p["b.signal.interests.entities"],
                "--json",
            ]
        if path == "/v2/insights":
            typ = p["filter.type"]
            extra = {k: v for k, v in p.items() if k != "filter.type"}
            return ["api", "insights", "-t", typ, "--params", json.dumps(extra), "--json"]
        raise TransportError(f"harness cannot carry {path}")

    def _env(self) -> dict[str, str]:
        keep = (
            "PATH",
            "SystemRoot",
            "SYSTEMROOT",
            "TEMP",
            "TMP",
            "USERPROFILE",
            "HOME",
            "APPDATA",
            "LOCALAPPDATA",
        )
        env = {k: v for k, v in os.environ.items() if k in keep}
        env.update(
            {
                "QLOO_API_KEY": self._api_key,
                "QLOO_BASE_URL": self._base_url,
                "QLOO_TRUSTED_BASE_URL": self._base_url,
                "NO_COLOR": "1",
            }
        )
        if self._home:
            Path(self._home).mkdir(parents=True, exist_ok=True)
            env["QLOO_HOME"] = self._home
        return env

    def _resolve(self) -> list[str]:
        exe = shutil.which(self._command[0])
        if exe is None:
            raise TransportError(f"harness command not found: {self._command[0]}")
        return [exe, *self._command[1:]]

    # -- execution ------------------------------------------------------------------------------------------
    async def get(self, path: str, params: Params) -> RawResponse:
        argv = [*self._resolve(), *self.argv(path, params)]
        t0 = time.monotonic()
        proc: asyncio.subprocess.Process | None = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                env=self._env(),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=(
                    os.name != "nt"
                ),  # own process group so a timeout can kill the whole tree
            )
            out, err = await asyncio.wait_for(proc.communicate(), timeout=self._timeout_s)
        except TimeoutError as exc:
            if proc is not None:
                await _terminate(proc)
            raise TransportError("harness timed out", retryable=True) from exc
        except OSError as exc:
            raise TransportError(f"harness could not start: {exc.__class__.__name__}") from exc
        elapsed = int((time.monotonic() - t0) * 1000)
        text = out.decode("utf-8", errors="replace")
        try:
            data: Any = json.loads(text) if text.strip() else None
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict) and data.get("error") is True:
            return self._error(data, elapsed)
        if proc.returncode not in (0, None):
            raise TransportError(
                f"harness exited {proc.returncode}",
                retryable=True,
                body=err.decode("utf-8", "replace"),
            )
        return RawResponse(
            status=200,
            body=self._wrap(path, data),
            headers={},
            elapsed_ms=elapsed,
            transport=self.name,
            text="" if data is not None else text[:200],
        )

    def _error(self, data: dict[str, Any], elapsed: int) -> RawResponse:
        message = str(data.get("message", ""))
        m = _STATUS.search(message)
        status = int(m.group(1)) if m else 500
        if data.get("code") == "AUTH_FAILED" or status in (401, 403):
            raise QlooAuthError("qloo rejected the credential", status if m else 401)
        return RawResponse(
            status=status,
            body=None,
            headers={},
            elapsed_ms=elapsed,
            transport=self.name,
            text=message[:200],
        )

    @staticmethod
    def _wrap(path: str, data: Any) -> Any:
        """Give the CLI's unwrapped output the same envelope REST returns, so the Guard parses one shape."""
        if path == "/search":
            return {"results": data if isinstance(data, list) else []}
        if path == "/v2/insights":
            return {
                "success": True,
                "results": {"entities": data if isinstance(data, list) else []},
            }
        if path == "/v2/tags":
            return {"success": True, "results": {"tags": data if isinstance(data, list) else []}}
        return data  # analyze already prints the full envelope

    async def aclose(self) -> None:
        return None
