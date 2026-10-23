"""Harness command resolution."""

from __future__ import annotations

from pathlib import Path

from qloo_guard import QlooConfig
from qloo_guard.config import find_harness_entry, resolve_harness_command


def _make(root: Path) -> Path:
    entry = root / "node_modules" / "@qloo" / "qloo-harness" / "dist" / "bin.js"
    entry.parent.mkdir(parents=True)
    entry.write_text("// fake", encoding="utf-8")
    return entry


def test_finds_the_entry_by_walking_up(tmp_path: Path) -> None:
    entry = _make(tmp_path)
    deep = tmp_path / "apps" / "api"
    deep.mkdir(parents=True)
    assert find_harness_entry(deep, {}) == entry


def test_explicit_environment_variable_wins(tmp_path: Path) -> None:
    other = tmp_path / "custom.js"
    other.write_text("//", encoding="utf-8")
    assert find_harness_entry(tmp_path, {"NIGIWAI_QLOO_HARNESS_JS": str(other)}) == other


def test_resolves_to_node_and_the_entry(tmp_path: Path) -> None:
    entry = _make(tmp_path)
    cmd = resolve_harness_command(QlooConfig(), tmp_path)
    assert cmd[-1] == str(entry) and Path(cmd[0]).name.lower().startswith("node")


def test_custom_command_is_left_alone(tmp_path: Path) -> None:
    _make(tmp_path)
    assert resolve_harness_command(QlooConfig(harness_command=("my-qloo", "--x")), tmp_path) == (
        "my-qloo",
        "--x",
    )
