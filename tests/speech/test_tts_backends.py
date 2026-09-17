"""Tests for TTS backend infrastructure."""

from __future__ import annotations

from unittest.mock import patch

from orion.core.registry import TTSRegistry
from orion.speech.tts import TTSResult

# ---------------------------------------------------------------------------
# TTSResult tests
# ---------------------------------------------------------------------------


def test_tts_result_dataclass():
    result = TTSResult(
        audio=b"fake-audio-bytes",
        format="mp3",
        duration_seconds=3.5,
        voice_id="orion-v1",
    )
    assert result.audio == b"fake-audio-bytes"
    assert result.format == "mp3"
    assert result.duration_seconds == 3.5


def test_tts_result_save(tmp_path):
    result = TTSResult(audio=b"fake-mp3-data", format="mp3")
    out = result.save(tmp_path / "test.mp3")
    assert out.exists()
    assert out.read_bytes() == b"fake-mp3-data"


# ---------------------------------------------------------------------------
# Cartesia backend tests
# ---------------------------------------------------------------------------


def test_cartesia_registered():
    from orion.speech.cartesia_tts import CartesiaTTSBackend

    TTSRegistry.register_value("cartesia", CartesiaTTSBackend)
    assert TTSRegistry.contains("cartesia")


def test_cartesia_synthesize():
    from orion.speech.cartesia_tts import CartesiaTTSBackend

    backend = CartesiaTTSBackend(api_key="fake-key")

    with patch(
        "orion.speech.cartesia_tts._cartesia_synthesize",
        return_value=b"fake-audio-mp3-bytes",
    ):
        result = backend.synthesize("Hello world", voice_id="test-voice")

    assert result.audio == b"fake-audio-mp3-bytes"
    assert result.format == "mp3"
    assert result.voice_id == "test-voice"


# ---------------------------------------------------------------------------
# Kokoro backend tests
# ---------------------------------------------------------------------------


def test_kokoro_registered():
    from orion.speech.kokoro_tts import KokoroTTSBackend

    TTSRegistry.register_value("kokoro", KokoroTTSBackend)
    assert TTSRegistry.contains("kokoro")


def test_kokoro_health_false_without_package(monkeypatch):
    import sys

    from orion.speech.kokoro_tts import KokoroTTSBackend

    # Simulate the package being absent even where it is installed: a None
    # entry in sys.modules makes `from kokoro import ...` raise ImportError.
    monkeypatch.setitem(sys.modules, "kokoro", None)
    backend = KokoroTTSBackend()
    assert backend.health() is False


# ---------------------------------------------------------------------------
# OpenAI TTS backend tests
# ---------------------------------------------------------------------------


def test_openai_tts_registered():
    from orion.speech.openai_tts import OpenAITTSBackend

    TTSRegistry.register_value("openai_tts", OpenAITTSBackend)
    assert TTSRegistry.contains("openai_tts")


def test_openai_tts_synthesize():
    from orion.speech.openai_tts import OpenAITTSBackend

    backend = OpenAITTSBackend(api_key="fake-key")

    with patch(
        "orion.speech.openai_tts._openai_tts_request",
        return_value=b"fake-openai-audio",
    ):
        result = backend.synthesize("Hello", voice_id="nova")

    assert result.audio == b"fake-openai-audio"
    assert result.voice_id == "nova"


def test_english_speech_uses_english_whisper_model():
    # Multilingual "base" misheard 41.7% of words through a laptop mic with
    # English locked; "base.en" 11.7% at the same speed.
    from orion.speech._discovery import whisper_model_for

    assert whisper_model_for("base", "en") == "base.en"
    assert whisper_model_for("small", "English") == "small.en"
    assert whisper_model_for("base", "") == "base"  # auto-detect keeps multilingual
    assert whisper_model_for("base", "ta") == "base"
    assert whisper_model_for("large-v3", "en") == "large-v3"  # no English-only variant
    assert whisper_model_for("base.en", "en") == "base.en"


# ---------------------------------------------------------------------------
# Backend discovery
# ---------------------------------------------------------------------------


def _config(backend: str = "auto", allow_cloud: bool = False):
    from orion.core.config import OrionConfig

    cfg = OrionConfig()
    cfg.tts.backend = backend
    cfg.tts.allow_cloud = allow_cloud
    return cfg


def _installed(monkeypatch, *packages: str):
    from orion.speech import _tts_discovery
    from orion.speech.chatterbox_tts import ChatterboxTTSBackend
    from orion.speech.kokoro_tts import KokoroTTSBackend

    # The registry is cleared between tests; register both local voices.
    TTSRegistry.register_value("kokoro", KokoroTTSBackend)
    TTSRegistry.register_value("chatterbox", ChatterboxTTSBackend)
    monkeypatch.setattr(
        _tts_discovery,
        "_package_installed",
        lambda key: key not in _tts_discovery._LOCAL_PACKAGES or key in packages,
    )


def test_auto_skips_chatterbox_when_only_kokoro_is_installed(monkeypatch):
    from orion.speech._tts_discovery import get_tts_backend
    from orion.speech.kokoro_tts import KokoroTTSBackend

    _installed(monkeypatch, "kokoro")
    assert isinstance(get_tts_backend(_config()), KokoroTTSBackend)


def test_auto_prefers_kokoro_when_both_are_installed(monkeypatch):
    from orion.speech._tts_discovery import get_tts_backend
    from orion.speech.kokoro_tts import KokoroTTSBackend

    _installed(monkeypatch, "kokoro", "chatterbox")
    assert isinstance(get_tts_backend(_config()), KokoroTTSBackend)


def test_missing_configured_local_voice_falls_back_to_installed_one(monkeypatch):
    from orion.speech._tts_discovery import get_tts_backend
    from orion.speech.kokoro_tts import KokoroTTSBackend

    _installed(monkeypatch, "kokoro")
    assert isinstance(get_tts_backend(_config("chatterbox")), KokoroTTSBackend)


def test_no_local_voice_installed_never_falls_back_to_cloud(monkeypatch):
    from orion.speech._tts_discovery import get_tts_backend

    _installed(monkeypatch)
    assert get_tts_backend(_config()) is None
    assert get_tts_backend(_config("chatterbox")) is None
