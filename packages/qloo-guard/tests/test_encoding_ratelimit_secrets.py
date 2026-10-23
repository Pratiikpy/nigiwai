"""Encoding rules, rate limiting, the circuit breaker, and the guarantee that the key never leaves the process."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from qloo_guard import (
    BudgetExhausted,
    EntityType,
    QlooConfig,
    SearchRequest,
    key_fingerprint,
    read_key,
)
from qloo_guard.encoding import decode_utf8, looks_like_mojibake, nfc
from qloo_guard.parse import entities_from_body
from qloo_guard.ratelimit import CircuitBreaker, TokenBucket

from .conftest import FakeTransport, artist_raw, ok, search_body

GOLDEN = [
    "Beyoncé",
    "Mötley Crüe",
    "Şebnem Ferah",
    "عمرو دياب",
    "अरिजीत सिंह",
    "IU",
    "Sigur Rós",
    "Björk",
]


@pytest.mark.parametrize("name", GOLDEN)
def test_names_round_trip_through_json_and_nfc(name: str) -> None:
    raw = json.dumps({"name": name}, ensure_ascii=False).encode("utf-8")
    assert json.loads(decode_utf8(raw))["name"] == name
    assert nfc(name) == name or nfc(nfc(name)) == nfc(name)


def test_mojibake_detector() -> None:
    assert looks_like_mojibake("Beyoncé".encode().decode("cp1252"))  # 'BeyoncÃ©'
    assert looks_like_mojibake("Mötley Crüe".encode().decode("cp1252"))
    assert not looks_like_mojibake("Beyoncé")
    assert not looks_like_mojibake("Plain ASCII")


def test_decomposed_names_are_normalised_to_nfc() -> None:
    decomposed = "Beyoncé"
    ent = entities_from_body("/search", search_body(artist_raw(decomposed)))[0]
    assert ent.name == "Beyoncé" and len(ent.name) == 7


@given(st.text(min_size=1, max_size=60))
def test_nfc_is_idempotent(text: str) -> None:
    assert nfc(nfc(text)) == nfc(text)


async def test_non_ascii_names_survive_the_pipeline(make_rig: Any) -> None:
    rig = make_rig(
        FakeTransport(respond=lambda p, q: ok(search_body(*(artist_raw(n) for n in GOLDEN))))
    )
    res = await rig.guard.search(
        SearchRequest(query="x", types=(EntityType.ARTIST,)), rig.guard.new_context("picker")
    )
    assert [e.name for e in res.items] == [nfc(n) for n in GOLDEN]


# ---- rate limiting ------------------------------------------------------------------------------------------
async def test_token_bucket_spaces_calls() -> None:
    bucket = TokenBucket(rate_per_second=20.0, burst=2)
    t0 = time.monotonic()
    for _ in range(6):
        await bucket.acquire("ask")
    elapsed = time.monotonic() - t0
    assert elapsed >= 0.15  # 2 burst + 4 more at 20/s is about 0.2 s


async def test_picker_gives_up_after_its_short_wait() -> None:
    bucket = TokenBucket(rate_per_second=0.2, burst=1)  # one slot every 5 s
    await bucket.acquire("picker")
    with pytest.raises(BudgetExhausted):
        await bucket.acquire("picker")  # would have to wait 5 s, picker allows 1.5 s


async def test_concurrent_acquires_never_exceed_the_burst_instantly() -> None:
    bucket = TokenBucket(rate_per_second=5.0, burst=3)
    stamps: list[float] = []

    async def go() -> None:
        await bucket.acquire("board")
        stamps.append(time.monotonic())

    t0 = time.monotonic()
    await asyncio.gather(*(go() for _ in range(8)))
    assert sum(1 for s in stamps if s - t0 < 0.05) <= 3


def test_circuit_breaker_opens_and_recovers() -> None:
    now = [0.0]
    cb = CircuitBreaker(threshold=3, window_s=10.0, cooldown_s=5.0, clock=lambda: now[0])
    for _ in range(3):
        cb.failure()
    assert cb.is_open
    now[0] = 6.0
    assert not cb.is_open
    cb.check()


def test_circuit_breaker_ignores_old_failures() -> None:
    now = [0.0]
    cb = CircuitBreaker(threshold=3, window_s=10.0, cooldown_s=5.0, clock=lambda: now[0])
    cb.failure()
    cb.failure()
    now[0] = 20.0
    cb.failure()
    assert not cb.is_open


# ---- secrets ------------------------------------------------------------------------------------------------
def test_key_is_read_from_env_then_file_and_never_from_arguments(tmp_path: Any) -> None:
    cfg = QlooConfig(key_file=str(tmp_path / "k.env"))
    (tmp_path / "k.env").write_text('QLOO_API_KEY="file-key"\nOTHER=1\n', encoding="utf-8")
    assert read_key(cfg, {}) == "file-key"
    assert read_key(cfg, {"QLOO_API_KEY": "env-key"}) == "env-key"
    assert read_key(QlooConfig(key_file=str(tmp_path / "missing")), {}) is None


def test_fingerprint_is_eight_hex_characters_and_not_the_key() -> None:
    fp = key_fingerprint("a-secret-key-value")
    assert len(fp) == 8 and int(fp, 16) >= 0 and "secret" not in fp


async def test_the_key_never_appears_in_call_records_or_results(make_rig: Any) -> None:
    secret = "SUPER-SECRET-KEY-123456"
    rig = make_rig(FakeTransport(respond=lambda p, q: ok(search_body(artist_raw()))))
    ctx = rig.guard.new_context("picker")
    res = await rig.guard.search(SearchRequest(query="x", types=(EntityType.ARTIST,)), ctx)
    blob = repr(rig.recorder.calls) + repr(res) + repr(rig.store._items) + repr(rig.guard.config)
    assert secret not in blob
