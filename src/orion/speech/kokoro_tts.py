"""Kokoro TTS backend — fully open-source, runs locally.

Requires the kokoro package: pip install kokoro
Falls back gracefully if not installed.
"""

from __future__ import annotations

import io
from typing import Any, Iterator, List

from orion.core.registry import TTSRegistry
from orion.speech.tts import TTSBackend, TTSResult


@TTSRegistry.register("kokoro")
class KokoroTTSBackend(TTSBackend):
    """Kokoro TTS — local open-source voice synthesis."""

    backend_id = "kokoro"

    def __init__(self, *, model_path: str = "", device: str = "auto") -> None:
        self._model_path = model_path
        self._device = device
        self._pipeline = None

    def _ensure_pipeline(self) -> None:
        if self._pipeline is not None:
            return
        try:
            from kokoro import KPipeline

            # Force CPU to prevent VRAM exhaustion alongside Ollama and Whisper
            device = "cpu"
            self._pipeline = KPipeline(lang_code="a", device=device)
        except ImportError:
            raise RuntimeError(
                "kokoro package not installed. Install with: pip install kokoro"
            )

    def iter_synthesize(
        self,
        text: str,
        *,
        voice_id: str = "af_heart",
        speed: float = 1.0,
    ) -> Iterator[Any]:
        """Yield raw audio chunks as Kokoro generates them (24 kHz)."""
        self._ensure_pipeline()
        if not voice_id:
            voice_id = "af_heart"
        for _, _, audio in self._pipeline(text, voice=voice_id, speed=speed):
            yield audio

    def synthesize(
        self,
        text: str,
        *,
        voice_id: str = "af_heart",
        speed: float = 1.0,
        output_format: str = "wav",
    ) -> TTSResult:
        self._ensure_pipeline()
        import numpy as np
        import soundfile as sf

        # Always fall back to a valid bundled voice
        if not voice_id:
            voice_id = "af_heart"

        samples = list(self.iter_synthesize(text, voice_id=voice_id, speed=speed))

        if not samples:
            return TTSResult(audio=b"", format=output_format, voice_id=voice_id)

        combined = np.concatenate(samples)
        buf = io.BytesIO()
        sf.write(buf, combined, 24000, format=output_format.upper())
        buf.seek(0)

        return TTSResult(
            audio=buf.read(),
            format=output_format,
            voice_id=voice_id,
            sample_rate=24000,
            duration_seconds=len(combined) / 24000,
            metadata={"backend": "kokoro"},
        )

    def available_voices(self) -> List[str]:
        return ["af_heart", "af_bella", "am_adam", "am_michael"]

    def health(self) -> bool:
        try:
            self._ensure_pipeline()
            return True
        except RuntimeError:
            return False
