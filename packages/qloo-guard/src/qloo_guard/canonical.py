"""Canonical parameter lists and cache keys (ARCHITECTURE 3.5)."""

from __future__ import annotations

import hashlib
import json

from .requests import Params

GUARD_RULES_VERSION = "1"


def canonical_params(params: Params) -> list[tuple[str, str]]:
    """Sorted by key then value so the same request always has the same key."""
    return sorted(params, key=lambda kv: (kv[0], kv[1]))


def canonical_json(host: str, endpoint: str, params: Params) -> str:
    return json.dumps(
        {
            "host": host,
            "endpoint": endpoint,
            "params": canonical_params(params),
            "rules": GUARD_RULES_VERSION,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def cache_key(host: str, endpoint: str, params: Params) -> str:
    return hashlib.sha256(canonical_json(host, endpoint, params).encode("utf-8")).hexdigest()
