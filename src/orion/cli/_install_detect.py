"""Detect how Orion was installed so we can show the right upgrade
command (and run the right upgrade command for ``orion self-update``).

Orion is not published on PyPI (the ``orion`` name there belongs to an
unrelated project), so no upgrade path may ever run ``pip install orion``.
The supported install paths are:

- **Windows installer** (``OrionSetup-<version>.exe``). The install folder
  holds ``install.json`` and ``Orion.exe``. The desktop app installs signed
  updates itself; otherwise download the latest installer.
- **Editable git checkout** (``uv sync`` / ``pip install -e .`` from a
  cloned repo). The package's ``__file__`` is inside a working tree
  with a ``.git`` directory at the repo root. Upgrade with
  ``git pull && uv sync`` from the checkout.
- **uv tool** (``uv tool install git+<repo>``). Lives in a uv-managed
  isolated venv under ``.../uv/tools/``. ``uv tool upgrade orion``
  re-installs from the recorded git source.
- **pip from git** (``pip install git+<repo>``). Lives in ``site-packages``.
  Upgrade by re-installing from the repository.

We detect by inspecting ``orion.__file__``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

REPO_URL = "https://github.com/AstraDev-Labs/Orion-AI"
RELEASES_URL = f"{REPO_URL}/releases/latest"
GIT_INSTALL_COMMAND = f"pip install --upgrade git+{REPO_URL}.git"

# Walk up at most this many parents: enough for
# ``<install>/runtime/.venv/Lib/site-packages/orion/__init__.py`` and
# ``<repo>/src/orion/__init__.py`` plus headroom, without wandering into
# the home folder or drive root.
_MAX_PARENTS = 8


@dataclass(frozen=True)
class InstallInfo:
    """How Orion was installed."""

    kind: str  # "installer" | "editable-git" | "uv-tool" | "pip-git" | "unknown"
    # Shell command that upgrades this install, or ``None`` when the upgrade
    # is not a command (the Windows installer).
    upgrade_command: Optional[str]
    # What to tell a person, always set.
    upgrade_hint: str
    repo_root: Optional[Path] = None  # only set for editable-git
    install_root: Optional[Path] = None  # only set for installer


def _installer_hint() -> str:
    return (
        'Orion updates itself: use "Update now" in the app or its tray menu, '
        f"or download the latest installer from {RELEASES_URL}"
    )


def detect_install() -> InstallInfo:
    """Return an :class:`InstallInfo` for the running interpreter.

    Cheap: just walks the parent directories of ``orion.__file__``
    once and checks for marker files. No subprocess calls.
    """
    try:
        import orion

        pkg_file = Path(orion.__file__).resolve()
    except Exception:
        return _unknown()

    candidate = pkg_file.parent
    for _ in range(_MAX_PARENTS):
        if (candidate / "install.json").is_file() and (
            candidate / "Orion.exe"
        ).is_file():
            return InstallInfo(
                kind="installer",
                upgrade_command=None,
                upgrade_hint=_installer_hint(),
                install_root=candidate,
            )
        if (candidate / ".git").exists() and (candidate / "pyproject.toml").exists():
            command = f"cd {candidate} && git pull && uv sync"
            return InstallInfo(
                kind="editable-git",
                upgrade_command=command,
                upgrade_hint=command,
                repo_root=candidate,
            )
        if candidate.parent == candidate:
            break
        candidate = candidate.parent

    parts = [p.lower() for p in pkg_file.parts]

    if "uv" in parts and "tools" in parts:
        return InstallInfo(
            kind="uv-tool",
            upgrade_command="uv tool upgrade orion",
            upgrade_hint="uv tool upgrade orion",
        )

    if "site-packages" in parts:
        return InstallInfo(
            kind="pip-git",
            upgrade_command=GIT_INSTALL_COMMAND,
            upgrade_hint=GIT_INSTALL_COMMAND,
        )

    return _unknown()


def _unknown() -> InstallInfo:
    return InstallInfo(
        kind="unknown",
        upgrade_command=None,
        upgrade_hint=(
            f"Download the latest installer from {RELEASES_URL}, "
            "or run `git pull && uv sync` in your Orion checkout"
        ),
    )
