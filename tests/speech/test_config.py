"""Tests for speech configuration."""

from orion.core.config import OrionConfig, SpeechConfig


def test_speech_config_defaults():
    cfg = SpeechConfig()
    assert cfg.backend == "auto"
    assert cfg.model == "base"
    assert cfg.language == ""
    assert cfg.device == "auto"
    assert cfg.compute_type == "float16"


def test_orion_config_has_speech():
    cfg = OrionConfig()
    assert hasattr(cfg, "speech")
    assert isinstance(cfg.speech, SpeechConfig)
    assert cfg.speech.backend == "auto"


def test_orion_system_has_speech_backend():
    """OrionSystem has a speech_backend attribute."""
    from orion.system import OrionSystem

    assert "speech_backend" in OrionSystem.__dataclass_fields__
