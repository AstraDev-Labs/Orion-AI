"""Chatterbox TTS backend — local, expressive, MIT-licensed.

Chatterbox (Resemble AI) is the expressive counterpart to the Kokoro
backend. Kokoro is small and real-time on CPU but expressively flat; this
one exposes a genuine emotion-intensity dial (``exaggeration``) and does
zero-shot voice cloning from a short reference clip.

Requires the chatterbox package: pip install chatterbox-tts
Falls back gracefully if not installed.

Device note: defaults to CPU for the same reason kokoro_tts.py does --
this machine's GPU is shared with Ollama, and loading a second model onto
it causes VRAM thrashing. Pass device="cuda" explicitly only when you know
the LLM is not resident.

Voice note: Chatterbox has no fixed named voices. ``voice_id`` is
interpreted as a path to a reference .wav to clone; empty means the
built-in default voice.
"""

from __future__ import annotations

import contextlib
import io
import logging
from pathlib import Path
from typing import Any, Iterator, List, Optional, Tuple

from orion.core.registry import TTSRegistry
from orion.speech.tts import TTSBackend, TTSResult

logger = logging.getLogger(__name__)

# emotion -> (exaggeration, cfg_weight)
#
# exaggeration is emotion intensity (Chatterbox default 0.5). Raising it
# also speeds delivery up, so cfg_weight is lowered to slow the pacing
# back down -- that pairing is what keeps high-emotion output intelligible
# rather than rushed.
_EMOTION_PRESETS: dict[str, Tuple[float, float]] = {
    "neutral": (0.5, 0.5),
    "calm": (0.35, 0.5),
    "soft": (0.3, 0.55),
    "warm": (0.6, 0.45),
    "happy": (0.75, 0.4),
    "excited": (0.9, 0.35),
    "sad": (0.45, 0.35),
    "serious": (0.6, 0.5),
    "urgent": (0.85, 0.4),
}

DEFAULT_EMOTION = "neutral"


def emotion_to_params(emotion: str) -> Tuple[float, float]:
    """Map an emotion label to (exaggeration, cfg_weight).

    Unknown labels fall back to neutral rather than raising -- the caller
    is usually an LLM picking a label, and an unrecognized one should
    degrade to plain speech, not break synthesis.
    """
    key = (emotion or "").strip().lower()
    return _EMOTION_PRESETS.get(key, _EMOTION_PRESETS[DEFAULT_EMOTION])


def available_emotions() -> List[str]:
    """Emotion labels this backend understands."""
    return sorted(_EMOTION_PRESETS)


@contextlib.contextmanager
def _quiet_progress() -> Iterator[None]:
    """Silence chatterbox's internal tqdm sampling bar.

    It emits ~1000 progress lines per utterance, which is fine in a
    notebook and ruinous in a server log. The TQDM_DISABLE env var is not
    enough on its own -- chatterbox constructs its bar with an explicit
    `disable` argument, which takes precedence -- so force `disable=True`
    on the tqdm class itself for the duration of the call.
    """
    patched = []
    try:
        import tqdm as _tqdm

        for cls in (_tqdm.tqdm, getattr(_tqdm, "std", _tqdm).tqdm):
            if cls in (c for c, _ in patched):
                continue
            original = cls.__init__

            def make(orig):
                def _init(self, *args, **kwargs):
                    kwargs["disable"] = True
                    return orig(self, *args, **kwargs)

                return _init

            cls.__init__ = make(original)
            patched.append((cls, original))
    except Exception:  # tqdm absent or an unexpected shape -- not fatal
        logger.debug("Could not silence tqdm", exc_info=True)

    try:
        yield
    finally:
        for cls, original in patched:
            cls.__init__ = original


@TTSRegistry.register("chatterbox")
class ChatterboxTTSBackend(TTSBackend):
    """Chatterbox TTS — local expressive synthesis with an emotion dial."""

    backend_id = "chatterbox"

    def __init__(self, *, device: str = "cpu", voices_dir: str = "") -> None:
        self._device = device or "cpu"
        self._voices_dir = Path(voices_dir) if voices_dir else None
        self._model = None

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        try:
            from chatterbox.tts import ChatterboxTTS
        except ImportError as exc:
            raise RuntimeError(
                "chatterbox package not installed. "
                "Install with: pip install chatterbox-tts"
            ) from exc

        device = self._device
        if device == "auto":
            try:
                import torch

                device = "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                device = "cpu"

        logger.info("Loading Chatterbox TTS on %s", device)
        self._model = ChatterboxTTS.from_pretrained(device=device)

    def _resolve_reference(self, voice_id: str) -> Optional[str]:
        """Turn voice_id into a reference-audio path, or None for default."""
        if not voice_id:
            return None
        candidate = Path(voice_id)
        if candidate.is_file():
            return str(candidate)
        if self._voices_dir is not None:
            for ext in (".wav", ".mp3", ".flac"):
                guess = self._voices_dir / f"{voice_id}{ext}"
                if guess.is_file():
                    return str(guess)
        logger.warning(
            "Chatterbox voice_id %r did not resolve to a reference clip; "
            "using the default voice",
            voice_id,
        )
        return None

    def synthesize(
        self,
        text: str,
        *,
        voice_id: str = "",
        speed: float = 1.0,
        output_format: str = "wav",
        emotion: str = "",
        exaggeration: Optional[float] = None,
        cfg_weight: Optional[float] = None,
    ) -> TTSResult:
        """Synthesize speech.

        ``emotion`` selects a preset; ``exaggeration``/``cfg_weight``
        override it directly when given. ``speed`` is accepted for
        interface compatibility but Chatterbox has no direct speed control
        -- pacing is governed by cfg_weight instead.
        """
        self._ensure_model()
        import numpy as np
        import soundfile as sf

        preset_exag, preset_cfg = emotion_to_params(emotion or DEFAULT_EMOTION)
        exag = preset_exag if exaggeration is None else float(exaggeration)
        cfg = preset_cfg if cfg_weight is None else float(cfg_weight)

        kwargs: dict[str, Any] = {"exaggeration": exag, "cfg_weight": cfg}
        reference = self._resolve_reference(voice_id)
        if reference:
            kwargs["audio_prompt_path"] = reference

        with _quiet_progress():
            wav = self._model.generate(text, **kwargs)

        # chatterbox returns a torch tensor shaped (1, n_samples)
        samples = wav.squeeze(0).detach().cpu().numpy().astype(np.float32)
        sample_rate = int(getattr(self._model, "sr", 24000))

        buf = io.BytesIO()
        sf.write(buf, samples, sample_rate, format=(output_format or "wav").upper())
        buf.seek(0)

        return TTSResult(
            audio=buf.read(),
            format=output_format or "wav",
            voice_id=voice_id,
            sample_rate=sample_rate,
            duration_seconds=len(samples) / sample_rate if sample_rate else 0.0,
            metadata={
                "backend": "chatterbox",
                "emotion": (emotion or DEFAULT_EMOTION).lower(),
                "exaggeration": exag,
                "cfg_weight": cfg,
                "cloned_from": reference or "",
            },
        )

    def available_voices(self) -> List[str]:
        """Reference clips available for cloning.

        Chatterbox is zero-shot, so this is whatever .wav files sit in the
        configured voices directory -- not a fixed built-in roster.
        """
        voices = ["default"]
        if self._voices_dir is not None and self._voices_dir.is_dir():
            voices.extend(sorted(p.stem for p in self._voices_dir.glob("*.wav")))
        return voices

    def health(self) -> bool:
        try:
            self._ensure_model()
            return True
        except RuntimeError:
            return False
        except Exception:
            logger.debug("Chatterbox health check failed", exc_info=True)
            return False


__all__ = [
    "ChatterboxTTSBackend",
    "available_emotions",
    "emotion_to_params",
    "DEFAULT_EMOTION",
]
