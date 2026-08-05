"""Smoke test that the tmp_orion_home fixture works."""

from __future__ import annotations

from pathlib import Path

from orion.core import config as config_mod


def test_fixture_redirects_default_config_dir(tmp_orion_home: Path) -> None:
    assert config_mod.DEFAULT_CONFIG_DIR == tmp_orion_home
    assert tmp_orion_home.exists()
    assert (tmp_orion_home / ".state").exists()
    assert (tmp_orion_home / ".state" / "models").exists()


def test_fixture_redirects_config_path(tmp_orion_home: Path) -> None:
    assert config_mod.DEFAULT_CONFIG_PATH == tmp_orion_home / "config.toml"
