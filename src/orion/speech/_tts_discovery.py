"""Auto-discover an available text-to-speech backend.

Mirrors ``_discovery.py`` (which does the same for speech-to-text), with one
extra rule that matters for this project specifically: **cloud backends are
refused unless the user has explicitly opted in.**

Orion's whole claim is that nothing leaves the machine unless a task genuinely
needs it. Voice is the easiest place for that claim to quietly become false --
a cloud TTS call ships the assistant's entire spoken output to a third party,
once per sentence. So ``config.tts.allow_cloud`` gates every non-local
backend, and naming one explicitly in ``config.tts.backend`` does not bypass
the gate; it fails loudly instead, so the user finds out at startup rather
than discovering it in a packet capture.
"""

from __future__ import annotations

import importlib.util
import logging
from typing import TYPE_CHECKING, Dict, List, Optional

if TYPE_CHECKING:
    from orion.core.config import OrionConfig
    from orion.speech.tts import TTSBackend

logger = logging.getLogger(__name__)

# Runs entirely on this machine. Kokoro comes first: it is what the Windows
# installer ships, and Chatterbox is several times slower than real time on CPU.
LOCAL_BACKENDS: List[str] = ["kokoro", "chatterbox"]

# The Python package each local backend imports when it first speaks. Both
# backends load lazily, so constructing one succeeds even when its package is
# missing; without this check "auto" picked Chatterbox on installs that only
# have Kokoro, and every spoken reply then failed.
_LOCAL_PACKAGES: Dict[str, str] = {"kokoro": "kokoro", "chatterbox": "chatterbox"}

# Ships text to a third party. Gated behind config.tts.allow_cloud.
CLOUD_BACKENDS: List[str] = ["cartesia", "elevenlabs", "openai"]

# Local-first: preferred order when config.tts.backend is "auto".
DISCOVERY_ORDER: List[str] = LOCAL_BACKENDS + CLOUD_BACKENDS


def is_local(key: str) -> bool:
    return key.strip().lower() in LOCAL_BACKENDS


def _package_installed(key: str) -> bool:
    package = _LOCAL_PACKAGES.get(key)
    if package is None:
        return True
    try:
        return importlib.util.find_spec(package) is not None
    except (ImportError, ValueError):
        return False


def _create_backend(key: str, config: "OrionConfig") -> Optional["TTSBackend"]:
    """Instantiate one TTS backend by registry key, or None if unavailable.

    Construction is deliberately lazy about models: both local backends defer
    weight loading to first synthesis, so a backend can be selected here
    without paying a multi-second model load during startup.
    """
    from orion.core.registry import TTSRegistry

    if not TTSRegistry.contains(key):
        return None
    if not _package_installed(key):
        logger.debug("TTS backend %r skipped: its package is not installed", key)
        return None

    tts = getattr(config, "tts", None)
    device = getattr(tts, "device", "cpu") or "cpu"
    voices_dir = getattr(tts, "voices_dir", "") or ""

    try:
        backend_cls = TTSRegistry.get(key)
        if key == "chatterbox":
            return backend_cls(device=device, voices_dir=voices_dir)
        if key == "kokoro":
            return backend_cls(device=device)
        return backend_cls()
    except Exception as exc:  # a broken optional backend must not stop startup
        logger.debug("TTS backend %r could not be constructed: %s", key, exc)
        return None


def get_tts_backend(config: "OrionConfig") -> Optional["TTSBackend"]:
    """Resolve the TTS backend to use, honouring the local-first policy."""
    # Importing the package runs each backend module's @TTSRegistry.register.
    import orion.speech  # noqa: F401

    tts = getattr(config, "tts", None)
    requested = (getattr(tts, "backend", "") or "auto").strip().lower()
    allow_cloud = bool(getattr(tts, "allow_cloud", False))

    if requested and requested != "auto":
        if requested in CLOUD_BACKENDS and not allow_cloud:
            logger.warning(
                "TTS backend %r is a cloud service and tts.allow_cloud is false, so it "
                "was not loaded. Set tts.allow_cloud = true to permit it, or pick a "
                "local backend (%s).",
                requested,
                ", ".join(LOCAL_BACKENDS),
            )
            return None
        backend = _create_backend(requested, config)
        if backend is not None:
            return backend
        if requested not in LOCAL_BACKENDS:
            logger.warning(
                "TTS backend %r is configured but unavailable -- the package is "
                "probably not installed.",
                requested,
            )
            return None
        # A local voice that isn't installed: use another local one rather than
        # going silent. Cloud voices are never a fallback.
        for key in LOCAL_BACKENDS:
            if key == requested:
                continue
            fallback = _create_backend(key, config)
            if fallback is not None:
                logger.warning(
                    "TTS backend %r is configured but not installed; using %r instead.",
                    requested,
                    key,
                )
                return fallback
        logger.warning("TTS backend %r is configured but not installed.", requested)
        return None

    for key in DISCOVERY_ORDER:
        if key in CLOUD_BACKENDS and not allow_cloud:
            continue
        backend = _create_backend(key, config)
        if backend is not None:
            logger.info("Selected TTS backend: %s", key)
            return backend
    return None


__all__ = [
    "get_tts_backend",
    "is_local",
    "LOCAL_BACKENDS",
    "CLOUD_BACKENDS",
    "DISCOVERY_ORDER",
]
