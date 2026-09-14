"""Check for newer Orion releases on GitHub.

Orion is released as GitHub Releases (tags like ``v1.0.1``); it is not on
PyPI. Copies installed with the Windows installer skip this check entirely:
the desktop app has its own update checker, which the user controls from the
tray menu.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_CACHE_PATH = Path("~/.orion/version-check.json").expanduser()
_CACHE_TTL = 86400  # 24 hours
_RELEASES_API = (
    "https://api.github.com/repos/AstraDev-Labs/Orion-AI/releases?per_page=30"
)


def _config_path() -> Path:
    """Resolve the config path, honoring ``OPENORION_CONFIG`` like core.config."""
    override = os.environ.get("OPENORION_CONFIG")
    if override:
        return Path(override).expanduser()
    return Path("~/.orion/config.toml").expanduser()


# Commands that surface the "new version available" nudge. We deliberately
# cast a wide net for interactive commands (anything a human runs at a
# terminal and would benefit from knowing about an update), and skip
# automation-facing ones (``_bootstrap``, ``daemon``, ``host``) so we
# don't add noise to background processes or CI.
_CHECK_COMMANDS = {
    "ask",
    "chat",
    "serve",
    "doctor",
    "init",
    "quickstart",
    "model",
    "agents",
    "skill",
    "memory",
    "bench",
    "telemetry",
    "config",
    "eval",
    "optimize",
}

# Environment opt-outs (any truthy value disables the check):
# - ``OPENORION_NO_UPDATE_CHECK=1`` — project-specific
# - ``CI=true`` — set by every major CI provider, suppresses by default
_OPT_OUT_ENV_VARS = ("OPENORION_NO_UPDATE_CHECK",)


def _check_disabled() -> bool:
    """Return True when the user has opted out of update checks."""
    for name in _OPT_OUT_ENV_VARS:
        raw = os.environ.get(name, "")
        if raw and raw.strip().lower() not in ("", "0", "false", "no", "off"):
            return True
    # CI defaults to skipping. Users in CI can override with
    # ``OPENORION_NO_UPDATE_CHECK=0`` if they want the nudge anyway.
    if os.environ.get("CI", "").strip().lower() in ("1", "true", "yes", "on"):
        return True
    if _installed_by_installer():
        return True
    return _config_disabled()


def _installed_by_installer() -> bool:
    """True for Windows installer copies, whose desktop app handles updates."""
    try:
        from orion.cli._install_detect import detect_install

        return detect_install().kind == "installer"
    except Exception:
        return False


def _config_disabled() -> bool:
    """Return True if config.toml has ``[updates] auto_update = false``.

    On a malformed config we conservatively return ``True`` — if the user
    tried to express an opt-out and the file has a typo, we should not
    silently flip back to auto-checking against their intent.
    """
    path = _config_path()
    if not path.exists():
        return False
    try:
        import tomllib
    except ImportError:  # Python 3.10
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ImportError:
            logger.debug("tomli not available, skipping config opt-out check")
            return False
    try:
        with open(path, "rb") as f:
            config = tomllib.load(f)
    except OSError as exc:
        logger.debug("config read failed: %s", exc)
        return False
    except tomllib.TOMLDecodeError as exc:
        logger.debug("config malformed at %s: %s — treating as opt-out", path, exc)
        return True
    return not config.get("updates", {}).get("auto_update", True)


def check_for_updates(command_name: str) -> None:
    """Print a message if a newer version is available. Best-effort, never raises.

    Honors ``OPENORION_NO_UPDATE_CHECK=1`` and ``CI=true`` — any
    truthy value (``1``, ``true``, ``yes``, ``on``) disables both the
    GitHub poll and the banner. See ``_check_disabled`` for the full list.
    """
    if command_name not in _CHECK_COMMANDS:
        return
    if _check_disabled():
        return
    try:
        _do_check()
    except Exception:
        pass


def _do_check() -> None:
    import orion

    current = orion.__version__
    latest = _get_latest_version(current)
    if latest is None:
        return

    from packaging.version import InvalidVersion, Version

    try:
        if Version(latest) > Version(current):
            from orion.cli._install_detect import detect_install

            info = detect_install()
            follow_up = "Or run: orion self-update\n" if info.upgrade_command else ""
            sys.stderr.write(
                f"\033[33mA new version of Orion is available "
                f"(v{current} → v{latest})\n"
                f"Update: {info.upgrade_hint}\n"
                f"{follow_up}\033[0m\n"
            )
    except InvalidVersion:
        pass


def _get_latest_version(current: str) -> str | None:
    """Return the latest non-prerelease version string from cache or GitHub.

    Returns ``None`` on network/parse failures rather than caching a stale
    or empty result. Dev/pre-release versions (``.devN``, ``aN``, ``bN``,
    ``rcN``) are filtered out so users on a stable release are not nudged
    to a rolling autotag build — they can still opt in via ``--pre``.
    """
    try:
        if _CACHE_PATH.exists():
            data = json.loads(_CACHE_PATH.read_text())
            last_check = data.get("last_check", 0)
            if time.time() - last_check < _CACHE_TTL:
                cached = data.get("latest_version")
                return cached or None
    except Exception:
        pass

    latest = _fetch_latest_stable()
    if not latest:
        return None

    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_PATH.write_text(
            json.dumps(
                {
                    "last_check": time.time(),
                    "latest_version": latest,
                    "current_version": current,
                }
            )
        )
    except Exception:
        pass

    return latest


def _fetch_latest_stable() -> str | None:
    """Query GitHub Releases and return the highest stable version, or ``None``.

    Drafts, GitHub pre-releases, tags that aren't versions (such as
    ``desktop-latest``) and dev/pre-release versions are all ignored.
    """
    try:
        import urllib.request

        request = urllib.request.Request(
            _RELEASES_API,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "orion-cli",
            },
        )
        with urllib.request.urlopen(request, timeout=3) as resp:
            releases = json.loads(resp.read())
    except Exception as exc:
        logger.debug("GitHub release poll failed: %s", exc)
        return None

    if not isinstance(releases, list):
        return None

    try:
        from packaging.version import InvalidVersion, Version
    except ImportError:
        return None

    stable: list[Version] = []
    for release in releases:
        if (
            not isinstance(release, dict)
            or release.get("draft")
            or release.get("prerelease")
        ):
            continue
        tag = str(release.get("tag_name") or "")
        try:
            v = Version(tag[1:] if tag[:1] in ("v", "V") else tag)
        except InvalidVersion:
            continue
        if v.is_prerelease or v.is_devrelease:
            continue
        stable.append(v)

    return str(max(stable)) if stable else None
