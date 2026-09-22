"""Regression coverage for Orion's Windows model cleanup."""

from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
UNINSTALL_SCRIPT = ROOT / "installer" / "windows" / "orion-uninstall.ps1"
INNO_SCRIPT = ROOT / "installer" / "windows" / "Orion.iss"


def test_uninstaller_removes_private_models_from_older_installs():
    uninstall = UNINSTALL_SCRIPT.read_text(encoding="utf-8")
    inno = INNO_SCRIPT.read_text(encoding="utf-8")

    assert "Join-Path $AppDir 'models\\ollama'" in uninstall
    assert "Stop-OllamaServingModels $modelsDir" in uninstall
    assert uninstall.index("Stop-OllamaServingModels $modelsDir") < uninstall.index(
        "Remove-Tree $modelsDir"
    )
    assert "DirExists(App + '\\models\\ollama')" in inno


def test_windows_uninstaller_has_valid_powershell_syntax():
    command = (
        "$errors = $null; "
        "[void][System.Management.Automation.Language.Parser]::ParseFile("
        f"'{UNINSTALL_SCRIPT}', [ref]$null, [ref]$errors); "
        "if ($errors.Count) { exit 1 }"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_uninstaller_deletes_legacy_private_model_directory(tmp_path: Path):
    """The fallback must work when an old install has no uninstall.ini."""
    model_blob = tmp_path / "models" / "ollama" / "blobs" / "sha256-test"
    model_blob.parent.mkdir(parents=True)
    model_blob.write_bytes(b"orion model test")

    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(UNINSTALL_SCRIPT),
            "-AppDir",
            str(tmp_path),
            "-Remove",
            "models",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert not model_blob.parent.parent.exists()
