"""Tests for the chat startup banner."""

from __future__ import annotations

from pathlib import Path

from orion.cli import _bg_state
from orion.cli._bg_state import model_state_filename
from orion.cli._chat_banner import render_startup_banner


def test_banner_empty_when_all_ready(tmp_orion_home: Path) -> None:
    (tmp_orion_home / ".state" / "extension-built").write_text("")
    (tmp_orion_home / ".state" / "models" / model_state_filename("qwen3.5:9b", "ready")).write_text("")
    s = _bg_state.get_status()
    banner = render_startup_banner(s)
    assert banner == ""


def test_banner_shows_rust_building(tmp_orion_home: Path) -> None:
    """Pending rust ext (no marker file) is shown as 'building'."""
    s = _bg_state.get_status()  # all pending
    banner = render_startup_banner(s)
    assert "Rust extension" in banner
    assert "building" in banner.lower()


def test_banner_shows_model_downloading(tmp_orion_home: Path) -> None:
    (tmp_orion_home / ".state" / "extension-built").write_text("")
    models_dir = tmp_orion_home / ".state" / "models"
    (models_dir / model_state_filename("qwen3.5:9b", "downloading")).write_text("")
    s = _bg_state.get_status()
    banner = render_startup_banner(s)
    assert "qwen3.5:9b" in banner
    assert "downloading" in banner.lower()


def test_banner_shows_failed_in_dim_warning(tmp_orion_home: Path) -> None:
    (tmp_orion_home / ".state" / "extension-failed").write_text("error tail")
    s = _bg_state.get_status()
    banner = render_startup_banner(s)
    assert "failed" in banner.lower()
    assert "doctor" in banner.lower()
