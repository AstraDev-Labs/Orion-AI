"""pywhispercpp speech-to-text backend (local, Georgi Gerganov's whisper.cpp port)."""

from __future__ import annotations

import os
import tempfile
from typing import Any, List, Optional

from orion.core.registry import SpeechRegistry
from orion.speech._stubs import Segment, SpeechBackend, TranscriptionResult

try:
    from pywhispercpp.model import Model
except ImportError:
    Model = None  # type: ignore[assignment, misc]


@SpeechRegistry.register("whisper-cpp")
class WhisperCppBackend(SpeechBackend):
    """Local speech-to-text using pywhispercpp."""

    backend_id = "whisper-cpp"

    def __init__(
        self,
        model_size: str = "base",
    ) -> None:
        self._model_size = model_size
        self._model: Optional[Model] = None

    def _ensure_model(self) -> Model:
        """Lazy-load the Whisper model on first use."""
        if self._model is None:
            if Model is None:
                raise ImportError(
                    "pywhispercpp is not installed. "
                    "Install with: uv sync --extra speech-whispercpp"
                )
            self._model = Model(self._model_size)
        return self._model

    def _transcribe_media(
        self,
        media: Any,
        *,
        language: Optional[str] = None,
        accurate: bool = False,
        initial_prompt: Optional[str] = None,
    ) -> TranscriptionResult:
        """Transcribe a path or 16 kHz float32 numpy samples."""
        model = self._ensure_model()
        params = {
            "print_progress": False,
            "print_realtime": False,
            "print_timestamps": False,
            "suppress_blank": True,
            "no_context": not accurate,
            "single_segment": not accurate,
        }
        if language:
            params["language"] = language
        if initial_prompt:
            params["initial_prompt"] = initial_prompt
        native_params = getattr(model, "_params", None)
        if native_params is not None:
            params = {
                key: value
                for key, value in params.items()
                if hasattr(native_params, key)
            }

        segments_iter = model.transcribe(media, **params)

        segments = []
        text_parts = []

        for seg in segments_iter:
            seg_text = seg.text.strip()
            start_sec = seg.t0 / 100.0 if hasattr(seg, "t0") else 0.0
            end_sec = seg.t1 / 100.0 if hasattr(seg, "t1") else 0.0

            text_parts.append(seg_text)
            segments.append(
                Segment(
                    text=seg_text,
                    start=start_sec,
                    end=end_sec,
                    confidence=None,
                )
            )

        text = " ".join(text_parts).strip()
        duration = segments[-1].end if segments else 0.0

        return TranscriptionResult(
            text=text,
            language=language or "en",
            confidence=None,
            duration_seconds=duration,
            segments=segments,
        )

    def transcribe_samples(
        self,
        samples: Any,
        *,
        language: Optional[str] = None,
        accurate: bool = False,
        initial_prompt: Optional[str] = None,
    ) -> TranscriptionResult:
        """Transcribe 16 kHz mono float32 samples without writing a WAV file."""
        return self._transcribe_media(
            samples, language=language, accurate=accurate, initial_prompt=initial_prompt
        )

    def transcribe(
        self,
        audio: bytes,
        *,
        format: str = "wav",
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        """Transcribe audio bytes using pywhispercpp."""
        suffix = f".{format}" if not format.startswith(".") else format
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(audio)
            tmp.flush()
            tmp_name = tmp.name

        try:
            return self._transcribe_media(tmp_name, language=language)
        finally:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)

    def health(self) -> bool:
        """Check if model is loaded or loadable."""
        if self._model is not None:
            return True
        return Model is not None

    def supported_formats(self) -> List[str]:
        """Supported audio formats."""
        return ["wav", "mp3", "m4a", "ogg", "flac", "webm"]
