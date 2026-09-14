"""Text-to-speech tool — synthesize text to audio via configurable TTS backend."""

from __future__ import annotations

import inspect
import tempfile
from pathlib import Path
from typing import Any

from orion.core.registry import ToolRegistry, TTSRegistry
from orion.core.types import ToolResult
from orion.tools._stubs import BaseTool, ToolSpec


def _configured_tts_backend() -> str:
    try:
        from orion.core.config import load_config

        return (getattr(load_config().tts, "backend", "") or "kokoro").strip()
    except Exception:
        return "kokoro"


@ToolRegistry.register("text_to_speech")
class TextToSpeechTool(BaseTool):
    """Synthesize text into spoken audio using a TTS backend."""

    tool_id = "text_to_speech"
    is_local = False

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="text_to_speech",
            description=(
                "Convert text to spoken audio. Returns the file path to the "
                "generated audio file."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The text to synthesize into speech.",
                    },
                    "voice_id": {
                        "type": "string",
                        "description": "Voice identifier for the TTS backend.",
                    },
                    "backend": {
                        "type": "string",
                        "description": (
                            "TTS backend. Local: 'kokoro' (fast, flat delivery), "
                            "'chatterbox' (expressive, supports emotion). "
                            "Cloud: 'cartesia', 'openai_tts', 'elevenlabs'."
                        ),
                    },
                    "emotion": {
                        "type": "string",
                        "description": (
                            "Emotional tone to speak with: neutral, calm, soft, warm, "
                            "happy, excited, sad, serious, urgent. Only the 'chatterbox' "
                            "backend renders this; other backends ignore it. Pick the "
                            "tone that fits what is being said."
                        ),
                    },
                    "output_dir": {
                        "type": "string",
                        "description": "Directory to save the audio file.",
                    },
                },
                "required": ["text"],
            },
            category="audio",
            timeout_seconds=120.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        # Ensure TTS backends are registered
        import orion.speech  # noqa: F401

        text = params.get("text", "")
        voice_id = params.get("voice_id", "")
        # Default to the voice configured for Orion ([tts] backend, local-first)
        # rather than Cartesia, a cloud service that needs its own API key.
        backend_key = params.get("backend") or _configured_tts_backend()
        _ALIASES = {"openai": "openai_tts"}
        backend_key = _ALIASES.get(backend_key, backend_key)
        output_dir = params.get("output_dir", "")
        speed = float(params.get("speed", 1.0))

        if not text:
            return ToolResult(
                tool_name="text_to_speech",
                content="No text provided.",
                success=False,
            )

        if not TTSRegistry.contains(backend_key):
            return ToolResult(
                tool_name="text_to_speech",
                content=f"TTS backend '{backend_key}' not available.",
                success=False,
            )

        backend_cls = TTSRegistry.get(backend_key)
        backend = backend_cls()

        # Only forward `emotion` to backends whose synthesize() accepts it --
        # kokoro/cartesia/etc. would raise TypeError on an unexpected kwarg.
        call_kwargs: dict[str, Any] = {"voice_id": voice_id, "speed": speed}
        emotion = params.get("emotion", "")
        if emotion:
            try:
                accepted = inspect.signature(backend.synthesize).parameters
                if "emotion" in accepted:
                    call_kwargs["emotion"] = emotion
            except (TypeError, ValueError):
                pass

        result = backend.synthesize(text, **call_kwargs)

        # Save to file
        if output_dir:
            out_dir = Path(output_dir)
        else:
            out_dir = Path(tempfile.mkdtemp(prefix="orion-tts-"))

        out_dir.mkdir(parents=True, exist_ok=True)
        ext = result.format or "mp3"
        audio_path = out_dir / f"digest.{ext}"
        result.save(audio_path)

        return ToolResult(
            tool_name="text_to_speech",
            content=str(audio_path),
            success=True,
            metadata={
                "audio_path": str(audio_path),
                "format": ext,
                "duration_seconds": result.duration_seconds,
                "voice_id": result.voice_id,
                "backend": backend_key,
                "emotion": result.metadata.get("emotion", ""),
            },
        )
