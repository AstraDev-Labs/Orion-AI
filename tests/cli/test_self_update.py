"""Smoke tests for `orion self-update`.

Focus on the surface that's easy to corrupt (output formatting, exit
codes, --check short-circuit). We don't actually run pip/uv from a
unit test; the subprocess call is mocked.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from orion.cli._install_detect import GIT_INSTALL_COMMAND, InstallInfo
from orion.cli.self_update_cmd import self_update


def _mock_info(kind: str = "pip-git") -> InstallInfo:
    commands = {
        "pip-git": GIT_INSTALL_COMMAND,
        "uv-tool": "uv tool upgrade orion",
        "editable-git": "cd /tmp/repo && git pull && uv sync",
        "installer": None,
        "unknown": None,
    }
    command = commands[kind]
    return InstallInfo(
        kind=kind,
        upgrade_command=command,
        upgrade_hint=command or "Download the latest installer from GitHub Releases",
    )


def test_check_flag_prints_command_and_exits_clean():
    with patch(
        "orion.cli.self_update_cmd.detect_install",
        return_value=_mock_info("pip-git"),
    ):
        result = CliRunner().invoke(self_update, ["--check"])
    assert result.exit_code == 0
    assert GIT_INSTALL_COMMAND in result.output
    assert "Install method: pip-git" in result.output


def test_check_does_not_invoke_subprocess():
    with (
        patch(
            "orion.cli.self_update_cmd.detect_install",
            return_value=_mock_info("pip-git"),
        ),
        patch("orion.cli.self_update_cmd.subprocess.run") as mock_run,
    ):
        CliRunner().invoke(self_update, ["--check"])
    mock_run.assert_not_called()


def test_yes_skips_confirmation_and_runs():
    mock_proc = MagicMock(returncode=0)
    with (
        patch(
            "orion.cli.self_update_cmd.detect_install",
            return_value=_mock_info("pip-git"),
        ),
        patch(
            "orion.cli.self_update_cmd.subprocess.run",
            return_value=mock_proc,
        ) as mock_run,
    ):
        result = CliRunner().invoke(self_update, ["-y"])
    assert result.exit_code == 0
    mock_run.assert_called_once()
    # The pip path uses shlex.split (no shell=True) and installs from git.
    args, kwargs = mock_run.call_args
    assert kwargs.get("shell") is not True
    assert args[0][:3] == ["pip", "install", "--upgrade"]
    assert args[0][3].startswith("git+https://github.com/AstraDev-Labs/Orion-AI")


def test_editable_git_uses_shell_true():
    """The git path uses `&&` so shell=True is needed; the others don't."""
    mock_proc = MagicMock(returncode=0)
    with (
        patch(
            "orion.cli.self_update_cmd.detect_install",
            return_value=_mock_info("editable-git"),
        ),
        patch(
            "orion.cli.self_update_cmd.subprocess.run",
            return_value=mock_proc,
        ) as mock_run,
    ):
        CliRunner().invoke(self_update, ["-y"])
    _, kwargs = mock_run.call_args
    assert kwargs.get("shell") is True


def test_failed_upgrade_propagates_exit_code():
    mock_proc = MagicMock(returncode=3)
    with (
        patch(
            "orion.cli.self_update_cmd.detect_install",
            return_value=_mock_info("pip-git"),
        ),
        patch(
            "orion.cli.self_update_cmd.subprocess.run",
            return_value=mock_proc,
        ),
    ):
        result = CliRunner().invoke(self_update, ["-y"])
    assert result.exit_code == 3


def test_installer_copy_explains_and_runs_nothing():
    with (
        patch(
            "orion.cli.self_update_cmd.detect_install",
            return_value=_mock_info("installer"),
        ),
        patch("orion.cli.self_update_cmd.subprocess.run") as mock_run,
    ):
        result = CliRunner().invoke(self_update, ["-y"])
    assert result.exit_code == 0
    assert "How to update:" in result.output
    assert "pip install" not in result.output
    mock_run.assert_not_called()


def test_unknown_install_runs_nothing():
    with (
        patch(
            "orion.cli.self_update_cmd.detect_install",
            return_value=_mock_info("unknown"),
        ),
        patch("orion.cli.self_update_cmd.subprocess.run") as mock_run,
    ):
        result = CliRunner().invoke(self_update, ["-y"])
    assert result.exit_code == 0
    assert "How to update:" in result.output
    mock_run.assert_not_called()


def test_decline_confirmation_exits_nonzero():
    with (
        patch(
            "orion.cli.self_update_cmd.detect_install",
            return_value=_mock_info("pip-git"),
        ),
        patch("orion.cli.self_update_cmd.subprocess.run") as mock_run,
    ):
        result = CliRunner().invoke(self_update, input="n\n")
    assert result.exit_code == 1
    assert "Aborted" in result.output
    mock_run.assert_not_called()
