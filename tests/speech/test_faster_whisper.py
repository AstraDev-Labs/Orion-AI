"""Tests for Faster-Whisper speech backend."""

from unittest.mock import MagicMock, patch

import pytest

from orion.core.registry import SpeechRegistry
from orion.speech.faster_whisper import FasterWhisperBackend


@pytest.fixture(autouse=True)
def _register_faster_whisper():
    """Re-register after any registry clear."""
    if not SpeechRegistry.contains("faster-whisper"):
        SpeechRegistry.register_value("faster-whisper", FasterWhisperBackend)


def test_faster_whisper_backend_registers():
    """Backend registers itself in SpeechRegistry."""
    assert SpeechRegistry.contains("faster-whisper")


def test_faster_whisper_transcribe():
    """Transcribe returns a TranscriptionResult."""
    from orion.speech._stubs import TranscriptionResult

    mock_model = MagicMock()
    mock_segment = MagicMock()
    mock_segment.text = " Hello world"
    mock_segment.start = 0.0
    mock_segment.end = 1.2
    mock_segment.avg_logprob = -0.3

    mock_info = MagicMock()
    mock_info.language = "en"
    mock_info.language_probability = 0.95
    mock_info.duration = 1.5

    mock_model.transcribe.return_value = ([mock_segment], mock_info)

    # _decode_audio_bytes must be mocked too: b"fake audio bytes" is not
    # decodable audio, and this only appeared to pass while PyAV was absent.
    with patch(
        "orion.speech.faster_whisper.WhisperModel",
        return_value=mock_model,
    ), patch(
        "orion.speech.faster_whisper._decode_audio_bytes",
        return_value=[0.0] * 16000,
    ):
        from orion.speech.faster_whisper import FasterWhisperBackend

        backend = FasterWhisperBackend(model_size="base", device="cpu")
        result = backend.transcribe(b"fake audio bytes")

        assert isinstance(result, TranscriptionResult)
        assert result.text == "Hello world"
        assert result.language == "en"
        assert result.duration_seconds == 1.5


def test_faster_whisper_health_when_not_installed():
    """Health is False when the faster-whisper package is not installed.

    WhisperModel is now imported lazily (the eager import cost ~6 s of server
    startup), so `WhisperModel is None` means "not loaded yet", not "missing".
    Absence is simulated at the package-discovery level instead.
    """
    with patch("orion.speech.faster_whisper.WhisperModel", new=None), patch(
        "orion.speech.faster_whisper._importlib_util.find_spec",
        return_value=None,
    ):
        from orion.speech.faster_whisper import FasterWhisperBackend

        backend = FasterWhisperBackend.__new__(FasterWhisperBackend)
        backend._model = None
        assert backend.health() is False


def test_faster_whisper_healthy_before_first_load():
    """Installed but not yet loaded must still report healthy.

    The model only loads on the first transcription; /v1/speech/health must not
    report STT as unavailable just because nobody has spoken yet.
    """
    with patch("orion.speech.faster_whisper.WhisperModel", new=None), patch(
        "orion.speech.faster_whisper._importlib_util.find_spec",
        return_value=object(),
    ):
        from orion.speech.faster_whisper import FasterWhisperBackend

        backend = FasterWhisperBackend.__new__(FasterWhisperBackend)
        backend._model = None
        assert backend.health() is True


def test_faster_whisper_supported_formats():
    """Backend supports standard audio formats."""
    with patch("orion.speech.faster_whisper.WhisperModel"):
        from orion.speech.faster_whisper import FasterWhisperBackend

        backend = FasterWhisperBackend.__new__(FasterWhisperBackend)
        formats = backend.supported_formats()
        assert "wav" in formats
        assert "mp3" in formats
        assert "webm" in formats
