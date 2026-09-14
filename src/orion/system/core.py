"""OrionSystem — the fully wired system dataclass."""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from orion.core.config import OrionConfig
from orion.core.events import EventBus, EventType
from orion.core.types import Message, Role
from orion.engine._stubs import InferenceEngine
from orion.system.bundles import (
    AgentRuntime,
    Observability,
    Scheduling,
    SecurityContext,
)
from orion.tools._stubs import BaseTool, ToolExecutor

if TYPE_CHECKING:
    from orion.agents._stubs import BaseAgent
    from orion.agents.executor import AgentExecutor
    from orion.agents.manager import AgentManager
    from orion.agents.scheduler import AgentScheduler
    from orion.channels._stubs import BaseChannel
    from orion.learning._stubs import RouterPolicy
    from orion.learning.learning_orchestrator import LearningOrchestrator
    from orion.mcp.client import MCPClient
    from orion.mcp.server import MCPServer
    from orion.operators.manager import OperatorManager
    from orion.sandbox.runner import ContainerRunner
    from orion.scheduler.scheduler import TaskScheduler
    from orion.scheduler.store import SchedulerStore
    from orion.security.audit import AuditLogger
    from orion.security.boundary import BoundaryGuard
    from orion.security.capabilities import CapabilityPolicy
    from orion.sessions.session import SessionStore
    from orion.skills.manager import SkillManager
    from orion.speech._stubs import SpeechBackend
    from orion.system.orchestrator import QueryOrchestrator
    from orion.telemetry.gpu_monitor import GpuMonitor
    from orion.telemetry.store import TelemetryStore
    from orion.tools.storage._stubs import MemoryBackend
    from orion.traces.collector import TraceCollector
    from orion.traces.store import TraceStore
    from orion.workflow.engine import WorkflowEngine

logger = logging.getLogger(__name__)

# Human-readable channel names for the auto-reply prompt.
_CHANNEL_LABELS = {
    "whatsapp_baileys": "WhatsApp",
    "whatsapp": "WhatsApp",
    "telegram": "Telegram",
    "discord": "Discord",
    "slack": "Slack",
}


@dataclass
class OrionSystem:
    """Fully wired system -- the single source of truth for primitive composition."""

    config: OrionConfig
    bus: EventBus
    engine: InferenceEngine
    engine_key: str
    model: str
    agent: Optional[BaseAgent] = None
    agent_name: str = ""
    tools: List[BaseTool] = field(default_factory=list)
    tool_executor: Optional[ToolExecutor] = None
    memory_backend: Optional[MemoryBackend] = None
    channel_backend: Optional[BaseChannel] = None
    router: Optional[RouterPolicy] = None
    mcp_server: Optional[MCPServer] = None
    telemetry_store: Optional[TelemetryStore] = None
    trace_store: Optional[TraceStore] = None
    trace_collector: Optional[TraceCollector] = None
    gpu_monitor: Optional[GpuMonitor] = None
    scheduler_store: Optional[SchedulerStore] = None
    scheduler: Optional[TaskScheduler] = None
    container_runner: Optional[ContainerRunner] = None
    workflow_engine: Optional[WorkflowEngine] = None
    session_store: Optional[SessionStore] = None
    capability_policy: Optional[CapabilityPolicy] = None
    audit_logger: Optional[AuditLogger] = None
    boundary_guard: Optional[BoundaryGuard] = None
    operator_manager: Optional[OperatorManager] = None
    agent_manager: Optional[AgentManager] = None
    agent_scheduler: Optional[AgentScheduler] = None
    agent_executor: Optional[AgentExecutor] = None
    speech_backend: Optional[SpeechBackend] = None
    skill_manager: Optional[SkillManager] = None
    _learning_orchestrator: Optional[LearningOrchestrator] = None
    _mcp_clients: List[MCPClient] = field(default_factory=list)

    @property
    def security(self) -> SecurityContext:
        return SecurityContext(
            capability_policy=self.capability_policy,
            audit_logger=self.audit_logger,
            boundary_guard=self.boundary_guard,
        )

    @property
    def observability(self) -> Observability:
        return Observability(
            telemetry_store=self.telemetry_store,
            trace_store=self.trace_store,
            trace_collector=self.trace_collector,
            gpu_monitor=self.gpu_monitor,
        )

    @property
    def agents(self) -> AgentRuntime:
        return AgentRuntime(
            agent=self.agent,
            agent_name=self.agent_name,
            manager=self.agent_manager,
            scheduler=self.agent_scheduler,
            executor=self.agent_executor,
        )

    @property
    def scheduling(self) -> Scheduling:
        return Scheduling(
            store=self.scheduler_store,
            runner=self.scheduler,
        )

    def _get_orchestrator(self) -> QueryOrchestrator:
        orch = self.__dict__.get("_orchestrator")
        if orch is None:
            from orion.system.orchestrator import QueryOrchestrator

            orch = QueryOrchestrator(self)
            self.__dict__["_orchestrator"] = orch
        return orch

    def ask(
        self,
        query: str,
        *,
        context: bool = True,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        agent: Optional[str] = None,
        tools: Optional[List[str]] = None,
        system_prompt: Optional[str] = None,
        operator_id: Optional[str] = None,
        prior_messages: Optional[List[Message]] = None,
    ) -> Dict[str, Any]:
        return self._get_orchestrator().ask(
            query,
            context=context,
            temperature=temperature,
            max_tokens=max_tokens,
            agent=agent,
            tools=tools,
            system_prompt=system_prompt,
            operator_id=operator_id,
            prior_messages=prior_messages,
        )

    def _detect_agent_intent(self, query: str) -> Optional[str]:
        return self._get_orchestrator()._detect_agent_intent(query)

    def _build_tools(self, tool_names: List[str]) -> List[BaseTool]:
        return self._get_orchestrator()._build_tools(tool_names)

    def _run_agent(
        self,
        query,
        messages,
        agent_name,
        tool_names,
        temperature,
        max_tokens,
        *,
        system_prompt=None,
        operator_id=None,
        prior_messages=None,
    ) -> Dict[str, Any]:
        return self._get_orchestrator()._run_agent(
            query,
            messages,
            agent_name,
            tool_names,
            temperature,
            max_tokens,
            system_prompt=system_prompt,
            operator_id=operator_id,
            prior_messages=prior_messages,
        )

    def wire_channel(self, channel_bridge: Any) -> None:
        """Register a message handler on *channel_bridge* that routes every
        incoming message through this system (agent or engine) and replies.

        Sessions are isolated per ``"<channel>:<conversation_id>"`` key so
        each chat retains its own history.

        Parameters
        ----------
        channel_bridge:
            A connected :class:`~orion.channels._stubs.BaseChannel`
            instance whose ``on_message`` method accepts a callable.
        """
        from orion.core.activity import is_user_away
        from orion.core.auto_reply import build_auto_reply_prompt
        from orion.core.message_priority import PRIORITY_EMERGENCY, classify_priority
        from orion.core.notify import notify_telegram
        from orion.core.types import Message
        from orion.sessions.session import SessionStore

        away_idle_minutes = getattr(self.config.channel, "away_idle_minutes", 10.0)
        owner_name = getattr(self.config.channel, "owner_name", "") or "the user"
        assistant_name = (
            getattr(self.config.channel.whatsapp_baileys, "assistant_name", "")
            or "Orion"
        )

        if self.session_store is None:
            from pathlib import Path

            self.session_store = SessionStore(
                db_path=Path(self.config.sessions.db_path).expanduser(),
                max_age_hours=self.config.sessions.max_age_hours,
                consolidation_threshold=self.config.sessions.consolidation_threshold,
            )

        _system = self  # capture for closure

        # Bounded so a burst of inbound messages can't spawn unbounded
        # concurrent inferences against a single local model.
        _reply_pool = ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="channel-reply",
        )

        def _is_group_conversation(cm) -> bool:
            """Best-effort group-chat detection."""
            channel, conversation_id = cm.channel, cm.conversation_id
            if channel == "whatsapp_baileys":
                return conversation_id.endswith("@g.us")
            if channel == "telegram":
                # Telegram represents group/supergroup chat ids as negative integers.
                try:
                    return int(conversation_id) < 0
                except ValueError:
                    return False
            if channel == "discord":
                # Anything outside a direct message is a server channel.
                return not bool((cm.metadata or {}).get("is_dm"))
            return False

        def _may_auto_reply(cm, is_group: bool) -> bool:
            """Whether Orion should answer *cm* on the user's behalf.

            The rule differs per platform because "a group" means different
            things. A WhatsApp group is a private conversation among people
            who all know each other, and the user asked never to have Orion
            speak there. A Discord server channel is public and high-traffic:
            a bot sees every message it can read, so replying to all of them
            would spam strangers -- but staying silent when the user is
            @mentioned would defeat the point. So Discord answers only when
            addressed, whereas WhatsApp groups stay silent unconditionally.
            """
            if cm.channel == "discord":
                md = cm.metadata or {}
                return bool(md.get("is_dm") or md.get("mentions_owner"))
            return not is_group

        def _on_channel_message(cm) -> None:
            session_key = f"{cm.channel}:{cm.conversation_id}"
            session = _system.session_store.get_or_create(
                session_key,
                channel=cm.channel,
                channel_user_id=cm.sender,
            )

            received_at = time.time()
            priority = classify_priority(cm.content)
            away = is_user_away(away_idle_minutes)
            is_group = _is_group_conversation(cm)

            # Every inbound message gets a desktop-toast notification
            # regardless of away state -- it's useful even when the user is
            # active in some other app. Only auto-reply is gated on `away`.
            try:
                _system.bus.publish(
                    EventType.CHANNEL_MESSAGE_NOTIFY,
                    {
                        "channel": cm.channel,
                        "sender": cm.sender,
                        "preview": cm.content[:280],
                        "priority": priority,
                        "away": away,
                        "is_group": is_group,
                        "conversation_id": cm.conversation_id,
                    },
                )
            except Exception:
                logger.debug("Notify publish failed", exc_info=True)

            if priority == PRIORITY_EMERGENCY and away:
                notify_telegram(
                    f"[EMERGENCY] {cm.channel} message from {cm.sender}:\n{cm.content[:500]}"
                )

            try:
                _system.session_store.save_message(
                    session.session_id,
                    "user",
                    cm.content,
                    channel=cm.channel,
                )
            except Exception:
                logger.debug("Session save error", exc_info=True)

            # Auto-reply only while the user is away, only where the
            # platform's rules allow it (see _may_auto_reply), only while the
            # user hasn't turned it off entirely, and only for senders on the
            # allowlist when one is configured. Read live off `_system.config`
            # rather than captured once at wire-up time, so the Governance UI's
            # toggle/allowlist take effect without a backend restart.
            if not away or not _may_auto_reply(cm, is_group):
                return
            if not getattr(_system.config.channel, "auto_reply_enabled", True):
                return
            allowlist_raw = getattr(_system.config.channel, "auto_reply_allowlist", "") or ""
            allowlist = {c.strip() for c in allowlist_raw.split(",") if c.strip()}
            if allowlist and cm.sender not in allowlist:
                return

            # Generating a reply is slow (a local model can take a minute or
            # more), and this handler runs inline on the channel's own reader
            # thread. Blocking it stops that thread from draining the bridge's
            # stdout pipe; once the OS buffer fills, the bridge process blocks
            # on its next write and the whole connection silently freezes --
            # observed here as "messages just stopped arriving". Do the slow
            # work on a background pool so the reader keeps consuming.
            _reply_pool.submit(_generate_and_send_reply, cm, session, priority, received_at)

        def _generate_and_send_reply(cm, session, priority: str, received_at: float) -> None:
            prior_msgs: List[Message] = []
            for sm in session.messages:
                try:
                    role = Role(sm.role)
                except ValueError:
                    role = Role.USER
                prior_msgs.append(Message(role=role, content=sm.content))

            reply = ""
            try:
                # Deliberately no agent and no tools here. The reply goes to a
                # third party, so the model's only job is to answer what they
                # asked on the owner's behalf -- handing it a tool belt just
                # invites it to "perform" tasks it cannot do and then report
                # fabricated results to a contact.
                result = _system.ask(
                    cm.content,
                    context=False,
                    system_prompt=build_auto_reply_prompt(
                        owner=owner_name,
                        assistant=assistant_name,
                        channel=_CHANNEL_LABELS.get(cm.channel, cm.channel),
                        priority=priority,
                    ),
                    prior_messages=prior_msgs,
                )
                reply = result.get("content", "")
            except Exception:
                logger.exception("Channel message handler error")
                reply = ""  # stay silent rather than send an error to a contact

            try:
                _system.session_store.save_message(
                    session.session_id,
                    "assistant",
                    reply,
                    channel=cm.channel,
                )
            except Exception:
                logger.debug("Session save error", exc_info=True)

            if not reply:
                return

            # Re-check right before sending, not just at receipt: generating
            # a reply can take a minute or more on a local model, plenty of
            # time for the owner to come back to their desktop or reply to
            # the message themselves from their phone. Sending a stale
            # auto-reply after either of those happened is exactly the
            # "still auto-replies after I've already seen/answered it" bug.
            if not is_user_away(away_idle_minutes):
                logger.info("Owner returned before auto-reply was ready -- not sending")
                return
            owner_replied_since = getattr(channel_bridge, "owner_replied_since", None)
            if owner_replied_since is not None and owner_replied_since(cm.conversation_id, received_at):
                logger.info("Owner already replied in %s -- not sending auto-reply", cm.conversation_id)
                return

            try:
                channel_bridge.send(
                    cm.channel,
                    reply,
                    conversation_id=cm.conversation_id,
                )
            except Exception:
                logger.exception("Channel send error")

        channel_bridge.on_message(_on_channel_message)

    def _close_mcp_clients(self) -> None:
        """Close all persistent MCP client connections."""
        for client in self._mcp_clients:
            try:
                client.close()
            except Exception:
                logger.debug("Error closing MCP client", exc_info=True)

    def close(self) -> None:
        """Release resources."""
        if self.scheduler and hasattr(self.scheduler, "stop"):
            self.scheduler.stop()
        for resource in (
            self.scheduler_store,
            self.engine,
            self.gpu_monitor,
            self.telemetry_store,
            self.trace_store,
            self.memory_backend,
            self.session_store,
            self.channel_backend,
            self.workflow_engine,
            self.container_runner,
        ):
            if resource and hasattr(resource, "close"):
                resource.close()
        if self.agent_manager is not None:
            self.agent_manager.close()
        if self.agent_scheduler is not None:
            self.agent_scheduler.stop()
        self._close_mcp_clients()

    def __enter__(self) -> OrionSystem:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


__all__ = ["OrionSystem"]
