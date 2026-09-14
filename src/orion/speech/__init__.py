"""Speech subsystem — speech-to-text and text-to-speech backends."""

import importlib
import logging

logger = logging.getLogger(__name__)

# Optional STT backends — each registers itself via @SpeechRegistry.register()
for _mod in ("faster_whisper", "openai_whisper", "deepgram", "whisper_cpp"):
    try:
        importlib.import_module(f".{_mod}", __name__)
    except ImportError:
        pass

# Optional TTS backends — each registers itself via @TTSRegistry.register()
# A missing backend here is the normal case, not an error: every one of
# these is an opt-in extra (see pyproject's speech-* extras), so this logs
# at debug rather than printing to stdout on every startup.
for _mod in ("cartesia_tts", "kokoro_tts", "chatterbox_tts", "openai_tts", "elevenlabs_tts"):
    try:
        importlib.import_module(f".{_mod}", __name__)
    except ImportError as e:
        logger.debug("TTS backend '%s' not available: %s", _mod, e)
