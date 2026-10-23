"""A stand-in for the `qloo` harness CLI used by the transport tests. It mimics the verified behaviour of
@qloo/qloo-harness 0.1.26 `qloo api <command>`: unwrapped lists for search, tags and insights, the full envelope for
analyze, and {"error": true, ...} with exit code 5 on API errors. All data is invented."""

from __future__ import annotations

import io
import json
import os
import sys
import time


def main(argv: list[str]) -> int:
    if argv[:1] != ["api"]:
        print(json.dumps({"error": True, "code": "USAGE", "message": "expected api"}))
        return 2
    mode = os.environ.get("FAKE_QLOO_MODE", "ok")
    if os.environ.get("QLOO_API_KEY") in (None, ""):
        print(json.dumps({"error": True, "code": "AUTH_FAILED", "message": "no key"}))
        return 5
    if mode == "log":  # echo what the CLI was given, for the mapping test
        env = {k: v for k, v in os.environ.items() if k.startswith("QLOO_")}
        env["QLOO_API_KEY"] = "<present>" if env.get("QLOO_API_KEY") else "<missing>"
        print(json.dumps([{"argv": argv, "env": env}]))
        return 0
    if mode == "400":
        print(
            json.dumps(
                {
                    "error": True,
                    "code": "API_ERROR",
                    "message": "API request failed: 400 Bad Request",
                }
            )
        )
        return 5
    if mode == "401":
        print(
            json.dumps(
                {
                    "error": True,
                    "code": "API_ERROR",
                    "message": "API request failed: 401 Unauthorized",
                }
            )
        )
        return 5
    if mode == "500":
        print(
            json.dumps(
                {
                    "error": True,
                    "code": "API_ERROR",
                    "message": "API request failed: 500 Internal Server Error",
                }
            )
        )
        return 5
    if mode == "hang":
        time.sleep(30)
    if mode == "garbage":
        print("not json at all")
        return 0
    if mode == "crash":
        sys.stderr.write("boom")
        return 1
    command = argv[1]
    if command == "analyze":
        print(
            json.dumps(
                {"duration": 3, "results": {"tags": [], "a": [], "b": [], "matchEntities": []}}
            )
        )
    elif command == "tags":
        print(
            json.dumps(
                [
                    {
                        "id": "urn:tag:genre:music:jazz",
                        "name": "Jazz",
                        "type": "urn:tag:genre:music",
                        "popularity": 0.9,
                    }
                ]
            )
        )
    elif command in ("search", "insights"):
        print(
            json.dumps(
                [
                    {
                        "name": "Lantern Hollow",
                        "entity_id": "00000000-0000-4000-8000-000000000001",
                        "types": ["urn:entity:artist"],
                    }
                ]
            )
        )
    else:
        print(json.dumps([]))
    return 0


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    raise SystemExit(main(sys.argv[1:]))
