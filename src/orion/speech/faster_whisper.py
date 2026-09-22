"""Faster-Whisper speech-to-text backend (local, CTranslate2-based)."""

from __future__ import annotations

import importlib.util as _importlib_util
import io
import sys
from typing import List, Optional

import numpy as np

from orion.core.registry import SpeechRegistry
from orion.speech._stubs import Segment, SpeechBackend, TranscriptionResult

# Resolved lazily by _whisper_model_cls(). Importing faster_whisper eagerly pulls
# in ctranslate2 and transformers -- about 6 s -- and this module is imported at
# every server start just to register the backend, long before anyone speaks.
# Kept as a module global so tests (and callers) can still patch it.
WhisperModel = None  # type: ignore[assignment, misc]


def _is_noise_hallucination(segment: object) -> bool:
    """True when Whisper rates a segment as probably not speech and low-confidence."""
    no_speech = getattr(segment, "no_speech_prob", None)
    logprob = getattr(segment, "avg_logprob", None)
    if not isinstance(no_speech, (int, float)) or not isinstance(logprob, (int, float)):
        return False
    return no_speech > 0.6 and logprob < -1.0


def _faster_whisper_available() -> bool:
    """Whether faster-whisper is installed, without importing it."""
    return WhisperModel is not None or _importlib_util.find_spec("faster_whisper") is not None


def _whisper_model_cls():
    """Import and return WhisperModel on first use (or the patched global)."""
    global WhisperModel
    if WhisperModel is None:
        try:
            from faster_whisper import WhisperModel as _cls
        except ImportError:
            return None
        WhisperModel = _cls
    return WhisperModel

_TARGET_SAMPLE_RATE = 16000


def _decode_audio_bytes(audio: bytes) -> np.ndarray:
    """Decode uploaded audio to 16 kHz mono float32 (no temp files)."""
    import av

    container = av.open(io.BytesIO(audio))
    if not container.streams.audio:
        raise ValueError("No audio stream in recording")

    resampler = av.AudioResampler(
        format="flt",
        layout="mono",
        rate=_TARGET_SAMPLE_RATE,
    )
    chunks: list[np.ndarray] = []
    for frame in container.decode(audio=0):
        for resampled in resampler.resample(frame):
            chunks.append(resampled.to_ndarray().astype(np.float32))

    if not chunks:
        raise ValueError("No audio samples in recording")

    samples = np.concatenate(chunks, axis=-1).reshape(-1)
    if samples.size == 0:
        raise ValueError("Empty audio recording")
    return samples


@SpeechRegistry.register("faster-whisper")
class FasterWhisperBackend(SpeechBackend):
    """Local speech-to-text using Faster-Whisper (CTranslate2)."""

    backend_id = "faster-whisper"

    def __init__(
        self,
        model_size: str = "base",
        device: str = "auto",
        compute_type: str = "float16",
    ) -> None:
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type
        self._model: Optional[WhisperModel] = None
        self._active_device = ""

    def _model_candidates(self) -> list[tuple[str, str]]:
        """Prefer CPU when CUDA libraries are missing (common on Windows)."""
        compute = self._compute_type
        device = self._device

        if device == "cpu":
            cpu_compute = "int8" if compute in ("float16", "float32") else compute
            return [("cpu", cpu_compute)]

        if device == "cuda":
            return [(device, compute), ("cpu", "int8")]

        # auto: CPU-only on Windows; elsewhere try CUDA then fall back to CPU
        if sys.platform == "win32":
            return [("cpu", "int8")]

        return [(device, compute), ("cpu", "int8")]

    @staticmethod
    def _is_cuda_runtime_error(exc: BaseException) -> bool:
        message = str(exc).lower()
        return any(
            token in message
            for token in ("cublas", "cudnn", "cuda", "cudart", "dll is not found")
        )

    def _load_model(self) -> "WhisperModel":
        model_cls = _whisper_model_cls()
        if model_cls is None:
            raise ImportError(
                "faster-whisper is not installed. "
                "Install with: uv sync --extra speech"
            )

        errors: list[str] = []
        from orion.speech._model_files import local_whisper_path

        model_path = local_whisper_path(self._model_size) or self._model_size
        for device, compute_type in self._model_candidates():
            try:
                model = model_cls(
                    model_path,
                    device=device,
                    compute_type=compute_type,
                )
                self._active_device = device
                return model
            except Exception as exc:
                errors.append(f"{device}/{compute_type}: {exc}")

        raise RuntimeError(
            "Could not load Whisper on any device. " + "; ".join(errors)
        ) from None

    def _ensure_model(self) -> WhisperModel:
        """Lazy-load the Whisper model on first use."""
        if self._model is None:
            self._model = self._load_model()
        return self._model

    def _reset_model(self) -> None:
        self._model = None
        self._active_device = ""

    def _run_transcription(
        self,
        samples: np.ndarray,
        *,
        language: Optional[str] = None,
        prompt: Optional[str] = None,
    ) -> TranscriptionResult:
        model = self._ensure_model()
        kwargs: dict = {}
        if language:
            kwargs["language"] = language
        if prompt:
            # Vocabulary context (the assistant's and user's names, how emails
            # are written). On whisper-base it turned "12345678 at exampel.edu"
            # into "12345678 at example.edu" at no speed cost, where moving to
            # small.en was 3.4x slower and still misheard the name.
            kwargs["initial_prompt"] = prompt

        # Silero VAD drops leading/trailing room noise before decoding, and a
        # clip is decoded on its own rather than conditioned on earlier text:
        # both stop Whisper inventing words ("Thank you.") from background hiss.
        kwargs.setdefault("vad_filter", True)
        kwargs.setdefault("vad_parameters", {"min_silence_duration_ms": 500, "speech_pad_ms": 300})
        kwargs.setdefault("condition_on_previous_text", False)

        segments_iter, info = model.transcribe(samples, **kwargs)
        # A segment Whisper itself rates as probably-not-speech with a low
        # log-probability is a hallucination on noise, not something said.
        segments_list = [seg for seg in segments_iter if not _is_noise_hallucination(seg)]

        text = "".join(seg.text for seg in segments_list).strip()
        segments = [
            Segment(
                text=seg.text.strip(),
                start=seg.start,
                end=seg.end,
                confidence=None,
            )
            for seg in segments_list
        ]

        return TranscriptionResult(
            text=text,
            language=getattr(info, "language", None),
            confidence=getattr(info, "language_probability", None),
            duration_seconds=getattr(info, "duration", 0.0),
            segments=segments,
        )

    def transcribe(
        self,
        audio: bytes,
        *,
        format: str = "wav",
        language: Optional[str] = None,
        prompt: Optional[str] = None,
    ) -> TranscriptionResult:
        """Transcribe audio bytes using Faster-Whisper."""
        del format  # format hint unused — PyAV detects container from bytes
        samples = _decode_audio_bytes(audio)

        try:
            return self._run_transcription(samples, language=language, prompt=prompt)
        except Exception as exc:
            if not self._is_cuda_runtime_error(exc):
                raise
            self._reset_model()
            self._device = "cpu"
            self._compute_type = "int8"
            return self._run_transcription(samples, language=language, prompt=prompt)

    def health(self) -> bool:
        """Check if model is loaded or loadable."""
        if self._model is not None:
            return True
        return _faster_whisper_available()

    def supported_formats(self) -> List[str]:
        """Supported audio formats (same as ffmpeg/Whisper)."""
        return ["wav", "mp3", "m4a", "ogg", "flac", "webm"]
