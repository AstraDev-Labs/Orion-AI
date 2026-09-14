"""User activity / away-state tracking.

Two independent signals combine to decide whether the user counts as
"away" for the purposes of channel auto-reply:

- OS-level idle time (no mouse/keyboard input for N minutes), read via the
  Windows ``GetLastInputInfo`` API.
- A manual away flag the user (or the agent, on the user's behalf, e.g.
  "I'm stepping out") can set explicitly, persisted to disk so it survives
  backend restarts.

Either signal alone is enough to count as away.
"""

from __future__ import annotations

import ctypes
import json
import logging
import platform
import time
from typing import Optional

from orion.core.config import DEFAULT_CONFIG_DIR

logger = logging.getLogger(__name__)

_STATE_PATH = DEFAULT_CONFIG_DIR / "away_state.json"


def get_os_idle_seconds() -> Optional[float]:
    """Return seconds since the last keyboard/mouse input, or ``None`` if unknown."""
    if platform.system() != "Windows":
        return None

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(LASTINPUTINFO)
    try:
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return None
        tick_count = ctypes.windll.kernel32.GetTickCount()
        idle_ms = tick_count - info.dwTime
        if idle_ms < 0:
            return None
        return idle_ms / 1000.0
    except Exception:
        logger.debug("GetLastInputInfo failed", exc_info=True)
        return None


def _load_manual_away() -> dict:
    if not _STATE_PATH.exists():
        return {}
    try:
        return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def set_manual_away(away: bool) -> None:
    """Explicitly mark the user as away (or back), overriding the idle timer."""
    try:
        DEFAULT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        _STATE_PATH.write_text(
            json.dumps({"manual_away": away, "set_at": time.time()}),
            encoding="utf-8",
        )
    except Exception:
        logger.debug("Failed to persist manual away state", exc_info=True)


# A manual "I'm away" flag set more than this long ago, with the keyboard or
# mouse used in the last couple of minutes, means the user is back. Without
# this the flag lived forever: one "I'm stepping out" on 21 August had Orion
# telling WhatsApp contacts the user was away for more than three weeks.
_MANUAL_AWAY_STALE_SECONDS = 30 * 60
_RECENT_INPUT_SECONDS = 120


def get_manual_away() -> bool:
    state = _load_manual_away()
    if not state.get("manual_away", False):
        return False
    set_at = float(state.get("set_at") or 0)
    if time.time() - set_at > _MANUAL_AWAY_STALE_SECONDS:
        idle = get_os_idle_seconds()
        if idle is not None and idle < _RECENT_INPUT_SECONDS:
            set_manual_away(False)
            logger.info("Cleared manual away flag: recent keyboard/mouse input")
            return False
    return True


def is_user_away(idle_threshold_minutes: float = 10.0) -> bool:
    """Return ``True`` if the user should be treated as away right now.

    Away if either the manual flag is set, or the OS has seen no input for
    at least ``idle_threshold_minutes``. If OS idle time can't be read
    (non-Windows, or the API call failed), only the manual flag is used.
    """
    if get_manual_away():
        return True

    idle_seconds = get_os_idle_seconds()
    if idle_seconds is None:
        return False
    return idle_seconds >= idle_threshold_minutes * 60.0


__all__ = [
    "get_os_idle_seconds",
    "set_manual_away",
    "get_manual_away",
    "is_user_away",
]
