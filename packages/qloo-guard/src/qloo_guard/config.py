"""Guard configuration. Everything has a safe default; the key is read only from the environment or a file."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class QlooConfig:
    base_url: str = "https://hackathon.api.qloo.com"
    key_env: str = "QLOO_API_KEY"
    key_file: str | None = None
    transport: str = "harness"  # harness | rest (decision D5)
    mode: str = "live"  # live | record | replay
    timeout_s: float = 20.0
    # Purposes that go to REST before the harness. The harness starts a Node process per call (measured 2.4 s extra
    # per call on 2026-10-23: search 3.4 s via harness against 1.0 s via REST), which is too slow for type-ahead.
    rest_first_purposes: tuple[str, ...] = ("picker",)
    harness_command: tuple[str, ...] = ("qloo",)
    harness_home: str | None = None
    # Rate: the hackathon key reported 10 requests per second on 2026-10-23; use 80% (rule: 20% headroom).
    rate_per_second: float = 8.0
    burst: int = 8
    month_limit: int = 50_000
    month_floor: int = 2_000  # below this, only the incident class may call
    # Share of the monthly allowance by purpose class (assumptions, ARCHITECTURE 3.4).
    class_shares: dict[str, float] = field(
        default_factory=lambda: {
            "picker": 0.45,
            "card": 0.15,
            "ask": 0.20,
            "board": 0.10,
            "fit": 0.10,
            "tribes": 0.10,
            "eval": 0.06,
            "canary": 0.06,
            "lineup": 0.04,
            "system": 0.04,
        }
    )

    @property
    def host(self) -> str:
        return self.base_url.rstrip("/")


def find_harness_entry(
    start: Path | None = None, environ: dict[str, str] | None = None
) -> Path | None:
    """Locate the harness's JavaScript entry (`dist/bin.js`) so it can be run with `node` directly.

    npm's `.cmd` shim on Windows passes JSON arguments through cmd.exe, which breaks on the quotes in
    `--params '{"filter.type": ...}'` (verified 2026-10-23). Running `node dist/bin.js` avoids the shell.
    """
    env = os.environ if environ is None else environ
    explicit = env.get("NIGIWAI_QLOO_HARNESS_JS")
    if explicit and Path(explicit).is_file():
        return Path(explicit)
    here = (start or Path.cwd()).resolve()
    for folder in (here, *here.parents):
        candidate = folder / "node_modules" / "@qloo" / "qloo-harness" / "dist" / "bin.js"
        if candidate.is_file():
            return candidate
    return None


def resolve_harness_command(config: QlooConfig, start: Path | None = None) -> tuple[str, ...]:
    """The command that starts the harness. A non-default command is used as given."""
    if config.harness_command != ("qloo",):
        return config.harness_command
    import shutil

    entry = find_harness_entry(start)
    node = shutil.which("node")
    if entry is not None and node is not None:
        return (node, str(entry))
    return config.harness_command


def read_key(config: QlooConfig, environ: dict[str, str] | None = None) -> str | None:
    """Return the key or None. The value is never logged by this package."""
    env = os.environ if environ is None else environ
    value = env.get(config.key_env, "").strip()
    if value:
        return value
    path = config.key_file or env.get("NIGIWAI_QLOO_KEY_FILE")
    if path and Path(path).is_file():
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if line.startswith(f"{config.key_env}="):
                return line.split("=", 1)[1].strip().strip("\"'")
    return None


def key_fingerprint(key: str) -> str:
    """First 8 hex characters of the key's SHA-256: safe to store, useless to attackers."""
    import hashlib

    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]
