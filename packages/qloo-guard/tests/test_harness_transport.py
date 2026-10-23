"""HarnessTransport: request mapping, error parsing, capability and process handling, against a fake CLI."""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest
from qloo_guard import QlooAuthError, TransportError
from qloo_guard.transports import HarnessTransport

FAKE = str(Path(__file__).with_name("fake_qloo_cli.py"))
ID_A = "11111111-1111-4111-8111-111111111111"


@pytest.fixture
def launcher(tmp_path: Path) -> tuple[str, ...]:
    """A real executable path for the fake CLI so shutil.which resolves it on every platform."""
    if os.name == "nt":
        bat = tmp_path / "qloo.cmd"
        bat.write_text(f'@echo off\r\n"{sys.executable}" "{FAKE}" %*\r\n', encoding="utf-8")
        return (str(bat),)
    sh = tmp_path / "qloo"
    sh.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE}" "$@"\n', encoding="utf-8")
    sh.chmod(sh.stat().st_mode | stat.S_IEXEC)
    return (str(sh),)


def make(launcher: tuple[str, ...], timeout: float = 20.0) -> HarnessTransport:
    return HarnessTransport(
        "https://hackathon.api.qloo.com", "test-key-value", launcher, timeout, None
    )


def test_capabilities() -> None:
    t = HarnessTransport("https://h", "k")
    assert t.supports("/search", [("query", "x"), ("types", "urn:entity:artist")])
    assert t.supports("/v2/tags", [("filter.query", "jazz")])
    assert t.supports("/v2/analysis/compare", [("a.signal.interests.entities", ID_A)])
    assert t.supports(
        "/v2/insights", [("filter.type", "urn:entity:place"), ("filter.location", "POINT(1 2)")]
    )
    # seeded insights need warnings; the batch /entities needs more than one id; demographics is not a CLI type
    assert not t.supports(
        "/v2/insights", [("filter.type", "urn:entity:artist"), ("signal.interests.entities", ID_A)]
    )
    assert not t.supports("/entities", [("entity_ids", ID_A)])
    assert not t.supports("/v2/insights", [("filter.type", "urn:demographics")])


def test_argv_search_uses_params_for_types_take_page() -> None:
    t = HarnessTransport("https://h", "k")
    argv = t.argv(
        "/search",
        [
            ("query", "radio head"),
            ("types", "urn:entity:artist,urn:entity:brand"),
            ("take", "5"),
            ("page", "2"),
        ],
    )
    assert argv[:4] == ["api", "search", "-q", "radio head"]
    assert json.loads(argv[argv.index("--params") + 1]) == {
        "types": "urn:entity:artist,urn:entity:brand",
        "take": "5",
        "page": "2",
    }
    assert argv[-1] == "--json"


def test_argv_insights_sends_the_exact_location_through_params() -> None:
    """`--filter-location` would map to filter.location.query (trap 17), so the point goes through --params."""
    t = HarnessTransport("https://h", "k")
    argv = t.argv(
        "/v2/insights",
        [
            ("filter.type", "urn:entity:place"),
            ("filter.location", "POINT(-73.99 40.72)"),
            ("filter.location.radius", "1500"),
            ("take", "5"),
        ],
    )
    assert "--filter-location" not in argv
    assert argv[argv.index("-t") + 1] == "urn:entity:place"
    extra = json.loads(argv[argv.index("--params") + 1])
    assert extra["filter.location"] == "POINT(-73.99 40.72)" and "filter.type" not in extra


async def test_search_output_is_wrapped_like_rest(launcher: tuple[str, ...]) -> None:
    raw = await make(launcher).get("/search", [("query", "x"), ("types", "urn:entity:artist")])
    assert raw.status == 200 and raw.transport == "harness"
    assert raw.body["results"][0]["name"] == "Lantern Hollow"
    assert raw.headers == {}  # the harness exposes no response headers


async def test_insights_and_tags_wrapping(launcher: tuple[str, ...]) -> None:
    ins = await make(launcher).get(
        "/v2/insights", [("filter.type", "urn:entity:place"), ("take", "3")]
    )
    assert ins.body["success"] is True and ins.body["results"]["entities"]
    tags = await make(launcher).get("/v2/tags", [("filter.query", "jazz")])
    assert tags.body["results"]["tags"][0]["id"] == "urn:tag:genre:music:jazz"


async def test_analyze_passes_the_envelope_through(launcher: tuple[str, ...]) -> None:
    raw = await make(launcher).get(
        "/v2/analysis/compare",
        [("a.signal.interests.entities", ID_A), ("b.signal.interests.entities", ID_A)],
    )
    assert raw.body["results"]["tags"] == []


async def test_environment_carries_the_key_and_host_but_not_secrets_from_the_parent(
    launcher: tuple[str, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_QLOO_MODE", "log")
    monkeypatch.setenv("SOME_OTHER_SECRET", "must-not-leak")
    monkeypatch.setenv("FAKE_QLOO_MODE", "log")
    t = make(launcher)
    # FAKE_QLOO_MODE is not in the allow-list, so pass it through the transport's environment hook for this test
    env = t._env()
    assert env["QLOO_API_KEY"] == "test-key-value"
    assert env["QLOO_BASE_URL"] == env["QLOO_TRUSTED_BASE_URL"] == "https://hackathon.api.qloo.com"
    assert "SOME_OTHER_SECRET" not in env


@pytest.mark.parametrize(("mode", "expected"), [("400", 400), ("500", 500)])
async def test_api_errors_become_statuses(
    launcher: tuple[str, ...], monkeypatch: pytest.MonkeyPatch, mode: str, expected: int
) -> None:
    monkeypatch.setattr(
        HarnessTransport,
        "_env",
        lambda self: {**os.environ, "QLOO_API_KEY": "k", "FAKE_QLOO_MODE": mode},
    )
    raw = await make(launcher).get("/search", [("query", "x"), ("types", "urn:entity:artist")])
    assert raw.status == expected and raw.body is None


async def test_unauthorised_raises_the_auth_error(
    launcher: tuple[str, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        HarnessTransport,
        "_env",
        lambda self: {**os.environ, "QLOO_API_KEY": "k", "FAKE_QLOO_MODE": "401"},
    )
    with pytest.raises(QlooAuthError):
        await make(launcher).get("/search", [("query", "x"), ("types", "urn:entity:artist")])


async def test_crash_and_garbage_are_transport_errors_or_empty(
    launcher: tuple[str, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        HarnessTransport,
        "_env",
        lambda self: {**os.environ, "QLOO_API_KEY": "k", "FAKE_QLOO_MODE": "crash"},
    )
    with pytest.raises(TransportError):
        await make(launcher).get("/search", [("query", "x"), ("types", "urn:entity:artist")])
    monkeypatch.setattr(
        HarnessTransport,
        "_env",
        lambda self: {**os.environ, "QLOO_API_KEY": "k", "FAKE_QLOO_MODE": "garbage"},
    )
    raw = await make(launcher).get("/search", [("query", "x"), ("types", "urn:entity:artist")])
    assert raw.body == {"results": []} and raw.text.startswith("not json")


async def test_timeout_kills_the_process_and_is_retryable(
    launcher: tuple[str, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        HarnessTransport,
        "_env",
        lambda self: {**os.environ, "QLOO_API_KEY": "k", "FAKE_QLOO_MODE": "hang"},
    )
    with pytest.raises(TransportError) as err:
        await make(launcher, timeout=0.5).get(
            "/search", [("query", "x"), ("types", "urn:entity:artist")]
        )
    assert err.value.retryable


async def test_missing_command_is_a_clear_error() -> None:
    t = HarnessTransport("https://h", "k", ("definitely-not-installed-qloo",))
    with pytest.raises(TransportError, match="not found"):
        await t.get("/search", [("query", "x"), ("types", "urn:entity:artist")])


async def test_entities_path_is_refused() -> None:
    t = HarnessTransport("https://h", "k", (sys.executable,))
    with pytest.raises(TransportError):
        await t.get("/entities", [("entity_ids", ID_A)])
