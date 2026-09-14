"""Auto-discover available speech-to-text backends."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from orion.core.config import OrionConfig
    from orion.speech._stubs import SpeechBackend

# Priority order: local first, then cloud
DISCOVERY_ORDER = [
    "faster-whisper",
    "openai",
    "deepgram",
]


# Whisper sizes that have an English-only variant ("base" -> "base.en").
_ENGLISH_VARIANTS = frozenset({"tiny", "base", "small", "medium"})


def whisper_model_for(model: str, language: str) -> str:
    """The Whisper model to load: the English-only variant when speech is English.

    Measured through a real laptop microphone on ten spoken commands, with
    language locked to English either way: multilingual "base" got 41.7% of
    words wrong ("Open Notepad" -> "Open no path", "Play Shape of You on
    YouTube" -> "You can play a shape if you want to use it"); "base.en"
    got 11.7% at the same speed.
    """
    name = (model or "base").strip()
    lang = (language or "").strip().lower()
    if lang in ("en", "english") and name in _ENGLISH_VARIANTS:
        return f"{name}.en"
    return name


def _create_backend(
    key: str,
    config: "OrionConfig",
) -> Optional["SpeechBackend"]:
    """Try to instantiate a speech backend by registry key."""
    from orion.core.registry import SpeechRegistry

    if not SpeechRegistry.contains(key):
        return None

    try:
        backend_cls = SpeechRegistry.get(key)

        if key == "faster-whisper":
            device = config.speech.device
            compute_type = config.speech.compute_type
            if device == "auto":
                device = "cpu"
            if device == "cpu" and compute_type in ("float16", "float32"):
                compute_type = "int8"
            return backend_cls(
                model_size=whisper_model_for(config.speech.model, config.speech.language),
                device=device,
                compute_type=compute_type,
            )
        elif key == "openai":
            api_key = os.environ.get("OPENAI_API_KEY", "")
            if not api_key:
                return None
            return backend_cls(api_key=api_key)
        elif key == "deepgram":
            api_key = os.environ.get("DEEPGRAM_API_KEY", "")
            if not api_key:
                return None
            return backend_cls(api_key=api_key)
        else:
            return backend_cls()
    except Exception:
        return None


def get_speech_backend(config: "OrionConfig") -> Optional["SpeechBackend"]:
    """Resolve the speech backend from config.

    If ``config.speech.backend`` is ``"auto"``, tries backends in
    priority order and returns the first healthy one.
    """
    # Trigger registration of built-in backends
    import orion.speech  # noqa: F401

    backend_key = config.speech.backend

    if backend_key != "auto":
        return _create_backend(backend_key, config)

    # Auto-discovery: try each in priority order
    for key in DISCOVERY_ORDER:
        backend = _create_backend(key, config)
        if backend is not None:
            return backend

    return None
