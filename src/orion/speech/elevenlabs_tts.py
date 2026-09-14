"""ElevenLabs text-to-speech backend.

Uses the ElevenLabs REST API for the most human-sounding voice synthesis
available to Orion. Requires ELEVENLABS_API_KEY environment variable.
"""

from __future__ import annotations

import os
from typing import List

import httpx

from orion.core.registry import TTSRegistry
from orion.speech.tts import TTSBackend, TTSResult

_ELEVENLABS_API_BASE = "https://api.elevenlabs.io/v1"

# "Adam" — a warm, natural, general-purpose narrator voice. Override with
# ELEVENLABS_VOICE_ID or the voice_id param for a different premade/cloned voice.
_DEFAULT_VOICE_ID = "pNInz6obpgDQGcFmaJgB"


def _elevenlabs_synthesize(
    api_key: str,
    text: str,
    voice_id: str,
    model: str = "eleven_turbo_v2_5",
) -> bytes:
    """Call the ElevenLabs TTS API and return raw mp3 audio bytes."""
    resp = httpx.post(
        f"{_ELEVENLABS_API_BASE}/text-to-speech/{voice_id}",
        headers={
            "xi-api-key": api_key,
            "Accept": "audio/mpeg",
        },
        json={
            "text": text,
            "model_id": model,
            "voice_settings": {
                "stability": 0.45,
                "similarity_boost": 0.8,
                "style": 0.35,
                "use_speaker_boost": True,
            },
        },
        timeout=120.0,
    )
    resp.raise_for_status()
    return resp.content


@TTSRegistry.register("elevenlabs")
class ElevenLabsTTSBackend(TTSBackend):
    """ElevenLabs TTS backend — the most natural, human-sounding voice option."""

    backend_id = "elevenlabs"

    def __init__(self, *, api_key: str = "", model: str = "eleven_turbo_v2_5") -> None:
        self._api_key = api_key or os.environ.get("ELEVENLABS_API_KEY", "")
        self._model = model
        self._default_voice = os.environ.get("ELEVENLABS_VOICE_ID", _DEFAULT_VOICE_ID)

    def synthesize(
        self,
        text: str,
        *,
        voice_id: str = "",
        speed: float = 1.0,
        output_format: str = "mp3",
    ) -> TTSResult:
        if not self._api_key:
            raise RuntimeError("ELEVENLABS_API_KEY not set")

        voice_id = voice_id or self._default_voice

        audio = _elevenlabs_synthesize(
            self._api_key,
            text,
            voice_id=voice_id,
            model=self._model,
        )

        return TTSResult(
            audio=audio,
            format="mp3",
            voice_id=voice_id,
            metadata={"backend": "elevenlabs", "model": self._model},
        )

    def available_voices(self) -> List[str]:
        if not self._api_key:
            return []
        resp = httpx.get(
            f"{_ELEVENLABS_API_BASE}/voices",
            headers={"xi-api-key": self._api_key},
            timeout=30.0,
        )
        resp.raise_for_status()
        return [v["voice_id"] for v in resp.json().get("voices", [])]

    def health(self) -> bool:
        return bool(self._api_key)
