"""Self-restart: hand the port off to a fresh backend process.

Used after a change that only takes effect on process start (a newly
registered tool, an evolved agent config) -- the running process cannot
hot-load those, so this replaces itself rather than asking the user to
run a command manually.

Same-port restarts can't be zero-downtime without a reverse proxy in
front: the old process must release the port before the new one can bind
it. This spawns the successor as a detached process that sleeps briefly
before starting (long enough for this process to exit and free the port),
then this process exits. There is a genuine, disclosed gap of a couple of
seconds with nothing listening -- the same gap every manual restart this
session already had.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)


def _repo_root() -> Path:
    # src/orion/system/self_restart.py -> repo root is 3 parents up
    return Path(__file__).resolve().parents[3]


def _orion_exe() -> str:
    root = _repo_root()
    candidate = root / ".venv" / "Scripts" / "orion.exe"
    if candidate.exists():
        return str(candidate)
    return "orion"  # fall back to PATH


def _restart_args() -> str:
    """Replay this process's own CLI args (e.g. "serve --port 9010"),
    instead of hardcoding bare "serve" -- so a self-restart lands back on
    whatever host/port/engine/model/agent the process actually started
    with, CLI-overridden or not, rather than silently falling back to
    config.toml's defaults. Doesn't attempt to quote args containing
    spaces; CLI values here (ports, names) normally don't have any.
    """
    args = sys.argv[1:]
    if not args:
        return "serve"
    return " ".join(args)


def _pid_file() -> Path:
    # Same file orion/cli/daemon_cmd.py's start()/stop()/status() read and
    # write -- writing the successor's real PID here keeps it visible to
    # those commands, instead of leaving server.pid pointing at the now-
    # dead original process after a self-restart.
    from orion.core.config import DEFAULT_CONFIG_DIR

    return DEFAULT_CONFIG_DIR / "server.pid"


def schedule_self_restart(*, delay_seconds: float = 1.0, handoff_seconds: float = 2.0) -> None:
    """Spawn a successor that waits `handoff_seconds` before binding the
    port, then exit this process after `delay_seconds` (long enough for
    the current HTTP response to actually flush to the client first).
    Fire-and-forget: runs in a background thread so the calling tool
    execution can return its own result immediately.
    """

    def _worker() -> None:
        try:
            exe = _orion_exe()
            args = _restart_args()
            pid_file = _pid_file()
            if sys.platform == "win32":
                # PowerShell wrapper: sleep first (gives this process time
                # to exit and free the port), then start the real server via
                # Start-Process -PassThru so we get its actual PID (not the
                # wrapper's) to record in server.pid.
                subprocess.Popen(
                    [
                        "powershell",
                        "-NoProfile",
                        "-WindowStyle",
                        "Hidden",
                        "-Command",
                        (
                            f"Start-Sleep -Seconds {handoff_seconds}; "
                            f"$p = Start-Process -FilePath '{exe}' -ArgumentList '{args}' "
                            f"-WorkingDirectory '{_repo_root()}' -WindowStyle Hidden -PassThru; "
                            f"Set-Content -Path '{pid_file}' -Value $p.Id"
                        ),
                    ],
                    cwd=str(_repo_root()),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,
                )
            else:
                # Background the real server and capture its PID via $! --
                # this shell process exits right after, but the
                # backgrounded server keeps running.
                subprocess.Popen(
                    [
                        "sh",
                        "-c",
                        f"sleep {handoff_seconds}; '{exe}' {args} & echo $! > '{pid_file}'",
                    ],
                    cwd=str(_repo_root()),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,
                )
            logger.info(
                "Self-restart: successor scheduled with args %r (handoff in %ss), "
                "exiting in %ss",
                args,
                handoff_seconds,
                delay_seconds,
            )
        except Exception:
            logger.exception("Self-restart: failed to schedule successor; staying up")
            return

        time.sleep(delay_seconds)
        os._exit(0)

    threading.Thread(target=_worker, daemon=True).start()


__all__ = ["schedule_self_restart"]
