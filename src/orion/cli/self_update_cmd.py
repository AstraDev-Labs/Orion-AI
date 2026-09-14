"""`orion self-update` — upgrade Orion to the latest release.

Runs the right upgrade command for how the user installed Orion:

- Windows installer copies are pointed at the app's own signed updater
  (or the latest installer); nothing is run.
- Editable git checkouts get ``git pull && uv sync`` in the checkout.
- uv-tool installs get ``uv tool upgrade orion``.
- pip installs from git re-install from the repository.

Orion is not on PyPI, so ``pip install orion`` is never run.

The detection logic is shared with the post-command "new version
available" hint in ``_version_check.py`` so both surfaces stay in sync.
"""

from __future__ import annotations

import shlex
import subprocess
import sys

import click

import orion
from orion.cli._install_detect import detect_install


@click.command(
    "self-update",
    help=(
        "Upgrade Orion to the latest release. Detects how you "
        "installed (Windows installer, editable git, uv tool, pip from "
        "git) and runs the right command. Use --check to only print the "
        "upgrade command without running it."
    ),
)
@click.option(
    "--check",
    is_flag=True,
    help="Print the upgrade command that would run, without executing it.",
)
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    help="Skip the interactive confirmation prompt.",
)
def self_update(check: bool, yes: bool) -> None:
    info = detect_install()
    current = orion.__version__

    click.echo(f"Current Orion version: v{current}")
    click.echo(f"Install method: {info.kind}")

    if info.upgrade_command is None:
        # Windows installer, or an install we can't identify: there is no
        # command we can safely run on the user's behalf.
        click.echo(f"How to update: {info.upgrade_hint}")
        return

    click.echo(f"Upgrade command: {info.upgrade_command}")

    if check:
        return

    if not yes:
        if not click.confirm("\nRun the upgrade command now?", default=True):
            click.echo("Aborted.")
            sys.exit(1)

    click.echo(f"\n→ {info.upgrade_command}\n")

    # ``editable-git`` uses shell features (``&&``); the others are
    # simple argv-style commands. Use ``shell=True`` only for the
    # editable case to keep the surface small. The command itself is
    # constructed from a trusted, locally-detected path — no user
    # input flows into it.
    if info.kind == "editable-git":
        result = subprocess.run(info.upgrade_command, shell=True)
    else:
        result = subprocess.run(shlex.split(info.upgrade_command))

    if result.returncode != 0:
        click.echo(
            f"\nUpgrade command exited with code {result.returncode}. "
            "Inspect the output above for the failure mode.",
            err=True,
        )
        sys.exit(result.returncode)

    click.echo("\nUpgrade complete. Re-run `orion --version` to confirm.")
