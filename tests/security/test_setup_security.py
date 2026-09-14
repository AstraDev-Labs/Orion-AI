"""Tests for setup_security() helper."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from orion.core.config import CapabilitiesConfig, OrionConfig, SecurityConfig
from orion.core.events import EventBus
from orion.security import SecurityContext, setup_security


def _make_mock_engine() -> MagicMock:
    engine = MagicMock()
    engine.engine_id = "mock"
    engine.generate.return_value = {"content": "ok"}
    engine.list_models.return_value = ["m"]
    engine.health.return_value = True
    return engine


def _make_config(*, enabled: bool = True, caps_enabled: bool = False) -> OrionConfig:
    cfg = OrionConfig()
    cfg.security = SecurityConfig(
        enabled=enabled,
        secret_scanner=True,
        pii_scanner=True,
        mode="warn",
        capabilities=CapabilitiesConfig(enabled=caps_enabled),
    )
    return cfg


def _has_rust() -> bool:
    try:
        import orion_rust  # noqa: F401

        return True
    except ImportError:
        return False


class TestSetupSecurityEnabled:
    @pytest.mark.skipif(not _has_rust(), reason="Rust extension not compiled")
    def test_returns_wrapped_engine(self) -> None:
        from orion.security.guardrails import GuardrailsEngine

        engine = _make_mock_engine()
        bus = EventBus()
        sec = setup_security(_make_config(), engine, bus)

        assert isinstance(sec.engine, GuardrailsEngine)
        assert sec.audit_logger is not None

    def test_returns_security_context(self) -> None:
        engine = _make_mock_engine()
        bus = EventBus()
        sec = setup_security(_make_config(), engine, bus)

        assert isinstance(sec, SecurityContext)
        # Audit logger should always work (no Rust dependency)
        assert sec.audit_logger is not None

    def test_graceful_without_rust(self) -> None:
        """Scanners fail gracefully when Rust is unavailable."""
        engine = _make_mock_engine()
        bus = EventBus()
        sec = setup_security(_make_config(), engine, bus)

        # Should not raise — scanner failure is caught
        assert isinstance(sec, SecurityContext)


class TestSetupSecurityDisabled:
    def test_returns_original_engine(self) -> None:
        engine = _make_mock_engine()
        sec = setup_security(_make_config(enabled=False), engine)

        assert sec.engine is engine
        assert sec.capability_policy is None
        assert sec.audit_logger is None


def _scanner_names(ctx: SecurityContext) -> set[str]:
    return {type(s).__name__ for s in getattr(ctx.engine, "_scanners", [])}


@pytest.mark.skipif(not _has_rust(), reason="scanners need orion_rust")
def test_pii_redaction_skipped_for_local_engine():
    engine = _make_mock_engine()
    engine.engine_id = "ollama"
    ctx = setup_security(_make_config(), engine)
    names = _scanner_names(ctx)
    assert "SecretScanner" in names and "PIIScanner" not in names


@pytest.mark.skipif(not _has_rust(), reason="scanners need orion_rust")
def test_pii_redaction_kept_for_cloud_engine():
    engine = _make_mock_engine()
    engine.engine_id = "cloud"
    assert "PIIScanner" in _scanner_names(setup_security(_make_config(), engine))


@pytest.mark.skipif(not _has_rust(), reason="scanners need orion_rust")
def test_pii_redaction_local_opt_in():
    engine = _make_mock_engine()
    engine.engine_id = "ollama"
    cfg = _make_config()
    cfg.security.pii_scan_local = True
    assert "PIIScanner" in _scanner_names(setup_security(cfg, engine))
