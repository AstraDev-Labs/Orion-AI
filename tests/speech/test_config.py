"""Tests for speech configuration."""

from orion.core.config import OrionConfig, SpeechConfig


def test_speech_config_defaults():
    cfg = SpeechConfig()
    assert cfg.backend == "auto"
    assert cfg.model == "base"
    assert cfg.language == ""
    # Defaults to cpu, not auto: cuda DLLs are frequently missing on Windows
    # and CPU avoids contending with Ollama for VRAM (see SpeechConfig).
    assert cfg.device == "cpu"
    # int8 pairs with the cpu default; float16 needs GPU support.
    assert cfg.compute_type == "int8"


def test_orion_config_has_speech():
    cfg = OrionConfig()
    assert hasattr(cfg, "speech")
    assert isinstance(cfg.speech, SpeechConfig)
    assert cfg.speech.backend == "auto"


def test_orion_system_has_speech_backend():
    """OrionSystem has a speech_backend attribute."""
    from orion.system import OrionSystem

    assert "speech_backend" in OrionSystem.__dataclass_fields__
