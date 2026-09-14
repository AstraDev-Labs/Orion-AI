"""Security guardrails — scanners, engine wrapper, audit, SSRF."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from orion.core.events import EventBus
from orion.security._stubs import BaseScanner
from orion.security.audit import AuditLogger
from orion.security.file_policy import (
    DEFAULT_SENSITIVE_PATTERNS,
    filter_sensitive_paths,
    is_sensitive_file,
)
from orion.security.guardrails import GuardrailsEngine, SecurityBlockError
from orion.security.scanner import PIIScanner, SecretScanner
from orion.security.ssrf import check_ssrf, is_private_ip
from orion.security.types import (
    RedactionMode,
    ScanFinding,
    ScanResult,
    SecurityEvent,
    SecurityEventType,
    ThreatLevel,
)

logger = logging.getLogger(__name__)


@dataclass
class SecurityContext:
    """Result of setup_security() — wrapped engine, policy, audit."""

    engine: Any
    capability_policy: Any = None
    audit_logger: Any = None


def _sends_data_off_machine(engine: Any) -> bool:
    """True for engines that call a remote API (cloud providers, routers)."""
    from orion.engine._discovery import _CLOUD_ENGINES

    engine_id = str(getattr(engine, "engine_id", "") or "").lower()
    return not engine_id or engine_id in _CLOUD_ENGINES


def setup_security(
    config: Any,
    engine: Any,
    bus: Optional[EventBus] = None,
) -> SecurityContext:
    """Apply security guardrails to an engine based on config.

    Returns a SecurityContext. No-ops if config.security.enabled is False.
    """
    if not config.security.enabled:
        return SecurityContext(engine=engine)

    # Scanners + engine wrapping
    try:
        scanners: list[BaseScanner] = []
        if config.security.secret_scanner:
            scanners.append(SecretScanner())
        # PII redaction protects personal data from leaving the machine. For a
        # local engine nothing leaves, and redacting only broke the user's own
        # requests: "email 12345678@example.edu" reached the model as
        # "email [REDACTED:email]", so no draft could ever be addressed.
        if config.security.pii_scanner and (
            _sends_data_off_machine(engine) or getattr(config.security, "pii_scan_local", False)
        ):
            scanners.append(PIIScanner())

        if scanners:
            mode = RedactionMode(config.security.mode)
            engine = GuardrailsEngine(
                engine,
                scanners=scanners,
                mode=mode,
                scan_input=config.security.scan_input,
                scan_output=config.security.scan_output,
                bus=bus,
            )
    except Exception as exc:
        logger.debug("Failed to set up security scanners: %s", exc)

    # Capability policy
    cap_policy = None
    if config.security.capabilities.enabled:
        try:
            from orion.security.capabilities import CapabilityPolicy

            cap_policy = CapabilityPolicy(
                policy_path=config.security.capabilities.policy_path or None,
            )
        except Exception as exc:
            logger.debug("Failed to set up capability policy: %s", exc)

    # Audit logger
    audit = None
    try:
        audit = AuditLogger(
            db_path=config.security.audit_log_path,
            bus=bus,
        )
    except Exception as exc:
        logger.debug("Failed to set up audit logger: %s", exc)

    return SecurityContext(
        engine=engine,
        capability_policy=cap_policy,
        audit_logger=audit,
    )


__all__ = [
    "AuditLogger",
    "BaseScanner",
    "DEFAULT_SENSITIVE_PATTERNS",
    "GuardrailsEngine",
    "PIIScanner",
    "RedactionMode",
    "ScanFinding",
    "ScanResult",
    "SecretScanner",
    "SecurityBlockError",
    "SecurityContext",
    "SecurityEvent",
    "SecurityEventType",
    "ThreatLevel",
    "check_ssrf",
    "filter_sensitive_paths",
    "is_private_ip",
    "is_sensitive_file",
    "setup_security",
]
