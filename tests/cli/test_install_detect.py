"""Tests for install-method detection."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from orion.cli._install_detect import GIT_INSTALL_COMMAND, InstallInfo, detect_install


def _patch_pkg_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point ``orion.__file__`` at ``tmp_path / orion / __init__.py``."""
    pkg_dir = tmp_path / "orion"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    init = pkg_dir / "__init__.py"
    init.write_text("__version__ = '0.0.0+test'\n")

    import orion

    monkeypatch.setattr(orion, "__file__", str(init))
    return init


def test_windows_installer_install_detected(tmp_path, monkeypatch):
    # Layout: <install>/install.json, <install>/Orion.exe,
    #         <install>/runtime/.venv/Lib/site-packages/orion/__init__.py
    install = tmp_path / "Programs" / "Orion"
    site = install / "runtime" / ".venv" / "Lib" / "site-packages"
    site.mkdir(parents=True)
    (install / "install.json").write_text("{}")
    (install / "Orion.exe").write_bytes(b"")
    _patch_pkg_file(site, monkeypatch)

    info = detect_install()
    assert info.kind == "installer"
    assert info.upgrade_command is None
    assert "Update now" in info.upgrade_hint
    assert "releases" in info.upgrade_hint
    assert info.install_root == install


def test_editable_git_install_detected(tmp_path, monkeypatch):
    # Layout: <tmp>/repo/.git, <tmp>/repo/pyproject.toml,
    #         <tmp>/repo/src/orion/__init__.py
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / "pyproject.toml").write_text("[project]\nname='orion'\n")
    src = repo / "src"
    _patch_pkg_file(src, monkeypatch)

    info = detect_install()
    assert info.kind == "editable-git"
    assert "git pull" in info.upgrade_command
    assert "uv sync" in info.upgrade_command
    assert info.repo_root == repo


def test_uv_tool_install_detected(tmp_path, monkeypatch):
    fake = tmp_path / "share" / "uv" / "tools" / "orion" / "lib" / "python3.12"
    fake.mkdir(parents=True)
    _patch_pkg_file(fake, monkeypatch)

    info = detect_install()
    assert info.kind == "uv-tool"
    assert info.upgrade_command == "uv tool upgrade orion"


def test_site_packages_install_reinstalls_from_git(tmp_path, monkeypatch):
    fake = tmp_path / "venv" / "lib" / "python3.12" / "site-packages"
    fake.mkdir(parents=True)
    _patch_pkg_file(fake, monkeypatch)

    info = detect_install()
    assert info.kind == "pip-git"
    assert info.upgrade_command == GIT_INSTALL_COMMAND
    assert "git+https://github.com/AstraDev-Labs/Orion-AI" in info.upgrade_command


def test_unknown_install_runs_nothing(tmp_path, monkeypatch):
    fake = tmp_path / "somewhere" / "weird"
    fake.mkdir(parents=True)
    _patch_pkg_file(fake, monkeypatch)

    info = detect_install()
    assert info.kind == "unknown"
    assert info.upgrade_command is None
    assert "releases" in info.upgrade_hint


def test_missing_orion_file_runs_nothing(monkeypatch):
    """orion unimportable / no __file__ — still get a sane, safe default."""
    with patch("orion.cli._install_detect.Path") as mock_path:
        mock_path.side_effect = Exception("boom")
        info = detect_install()
    assert info.kind == "unknown"
    assert info.upgrade_command is None


@pytest.mark.parametrize(
    "layout",
    ["installer", "editable", "uv", "site", "unknown"],
)
def test_never_suggests_pypi_package(tmp_path, monkeypatch, layout):
    """``orion`` on PyPI is an unrelated project; never install it."""
    if layout == "installer":
        base = tmp_path / "Orion"
        pkg = base / "runtime" / "Lib" / "site-packages"
        pkg.mkdir(parents=True)
        (base / "install.json").write_text("{}")
        (base / "Orion.exe").write_bytes(b"")
    elif layout == "editable":
        base = tmp_path / "repo"
        (base / ".git").mkdir(parents=True)
        (base / "pyproject.toml").write_text("")
        pkg = base / "src"
    elif layout == "uv":
        pkg = tmp_path / "uv" / "tools" / "orion"
        pkg.mkdir(parents=True)
    elif layout == "site":
        pkg = tmp_path / "site-packages"
        pkg.mkdir(parents=True)
    else:
        pkg = tmp_path / "elsewhere"
        pkg.mkdir(parents=True)
    _patch_pkg_file(pkg, monkeypatch)

    info = detect_install()
    for text in (info.upgrade_command or "", info.upgrade_hint):
        assert "pip install orion" not in text
        assert "pip install --upgrade orion" not in text


def test_returns_install_info_dataclass():
    info = detect_install()
    assert isinstance(info, InstallInfo)
    assert info.kind in {"installer", "editable-git", "uv-tool", "pip-git", "unknown"}
    assert info.upgrade_hint
