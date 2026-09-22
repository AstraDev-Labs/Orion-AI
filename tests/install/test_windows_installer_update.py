"""Regression coverage for the Windows install-versus-update decision."""

from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SETUP_SCRIPT = ROOT / "installer" / "windows" / "orion-setup.ps1"
INNO_SCRIPT = ROOT / "installer" / "windows" / "Orion.iss"


def test_completed_install_uses_the_update_path_only():
    setup = SETUP_SCRIPT.read_text(encoding="utf-8")
    inno = INNO_SCRIPT.read_text(encoding="utf-8")
    start = setup.index("function Update-ExistingInstall")
    end = setup.index("# Main", start)
    update = setup[start:end]

    assert "Can-UpdateExistingInstall" in setup
    assert "if ($Update -and (Can-UpdateExistingInstall))" in setup
    assert "Install-OrionRuntime" in update
    assert "Install-Ollama" not in update
    assert "Install-Models" not in update
    assert "Initialize-Voice" not in update
    assert "-Update" in inno
    assert "IsExistingOrionInstall" in inno
    assert "procedure ConfigureReadyPage" in inno
    assert "Ready to Update" in inno
    assert "NextButton.Caption := '&Update'" in inno


def test_windows_setup_script_has_valid_powershell_syntax():
    command = (
        "$errors = $null; "
        "[void][System.Management.Automation.Language.Parser]::ParseFile("
        f"'{SETUP_SCRIPT}', [ref]$null, [ref]$errors); "
        "if ($errors.Count) { exit 1 }"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
