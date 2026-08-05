"""Structural protocols for substituting fakes in place of OrionSystem."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, List, Optional, Protocol

if TYPE_CHECKING:
    from orion.core.config import OrionConfig
    from orion.core.events import EventBus
    from orion.engine._stubs import InferenceEngine
    from orion.security.capabilities import CapabilityPolicy
    from orion.sessions.session import SessionStore
    from orion.tools._stubs import BaseTool
    from orion.tools.storage._stubs import MemoryBackend
    from orion.traces.collector import TraceCollector
    from orion.traces.store import TraceStore


class OrchestratorDeps(Protocol):
    """Minimum surface of OrionSystem that QueryOrchestrator depends on.

    Tests can satisfy this with a lightweight class — no need to construct
    the full OrionSystem dataclass or materialize every subsystem.
    """

    config: OrionConfig
    bus: EventBus
    engine: InferenceEngine
    engine_key: str
    model: str
    agent_name: str
    tools: List[BaseTool]
    memory_backend: Optional[MemoryBackend]
    capability_policy: Optional[CapabilityPolicy]
    session_store: Optional[SessionStore]
    trace_store: Optional[TraceStore]
    trace_collector: Optional[TraceCollector]  # written by _run_agent

    # Optional attribute (getattr with default) — declared for type clarity.
    _skill_few_shot_examples: Any
