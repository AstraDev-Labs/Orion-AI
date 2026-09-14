"""Tests for orion.cli._bg_state."""

from __future__ import annotations

from pathlib import Path

from orion.cli import _bg_state
from orion.cli._bg_state import model_state_filename


def test_get_status_empty(tmp_orion_home: Path) -> None:
    """No state files = everything 'pending'."""
    s = _bg_state.get_status()
    assert s.rust_extension == "pending"
    assert s.models == {}


def test_get_status_rust_built(tmp_orion_home: Path) -> None:
    (tmp_orion_home / ".state" / "extension-built").write_text("")
    s = _bg_state.get_status()
    assert s.rust_extension == "ready"


def test_get_status_rust_failed(tmp_orion_home: Path) -> None:
    (tmp_orion_home / ".state" / "extension-failed").write_text("error tail here")
    s = _bg_state.get_status()
    assert s.rust_extension == "failed"
    assert s.rust_error == "error tail here"


def test_get_status_model_downloading(tmp_orion_home: Path) -> None:
    (tmp_orion_home / ".state" / "models" / model_state_filename("qwen3.5:9b", "downloading")).write_text(
        ""
    )
    s = _bg_state.get_status()
    assert s.models == {"qwen3.5:9b": "downloading"}


def test_get_status_model_ready(tmp_orion_home: Path) -> None:
    (tmp_orion_home / ".state" / "models" / model_state_filename("qwen3.5:9b", "ready")).write_text("")
    s = _bg_state.get_status()
    assert s.models == {"qwen3.5:9b": "ready"}


def test_get_status_model_failed(tmp_orion_home: Path) -> None:
    (tmp_orion_home / ".state" / "models" / model_state_filename("qwen3.5:9b", "failed")).write_text(
        "net error"
    )
    s = _bg_state.get_status()
    assert s.models == {"qwen3.5:9b": "failed"}


def test_get_status_ready_supersedes_downloading(tmp_orion_home: Path) -> None:
    """If both .downloading and .ready exist (race window), .ready wins."""
    models_dir = tmp_orion_home / ".state" / "models"
    (models_dir / model_state_filename("qwen3.5:9b", "downloading")).write_text("")
    (models_dir / model_state_filename("qwen3.5:9b", "ready")).write_text("")
    s = _bg_state.get_status()
    assert s.models["qwen3.5:9b"] == "ready"


def test_all_ready_true_when_all_ready(tmp_orion_home: Path) -> None:
    (tmp_orion_home / ".state" / "extension-built").write_text("")
    (tmp_orion_home / ".state" / "models" / model_state_filename("qwen3.5:9b", "ready")).write_text("")
    s = _bg_state.get_status()
    assert s.all_ready() is True


def test_all_ready_false_when_anything_pending(tmp_orion_home: Path) -> None:
    (tmp_orion_home / ".state" / "extension-built").write_text("")
    (tmp_orion_home / ".state" / "models" / model_state_filename("qwen3.5:9b", "downloading")).write_text(
        ""
    )
    s = _bg_state.get_status()
    assert s.all_ready() is False


def test_get_status_handles_deleted_file_race(tmp_orion_home: Path) -> None:
    """File present at glob-time, gone at read-time = treat as missing."""
    f = tmp_orion_home / ".state" / "extension-failed"
    f.write_text("oops")
    f.unlink()  # simulate race
    # No assertion error expected
    s = _bg_state.get_status()
    assert s.rust_extension == "pending"
