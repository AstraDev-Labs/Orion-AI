# ruff: noqa: E501
"""Proactive agent tools — check/record permissions, queue and execute actions.

These tools are used exclusively by ``ProactiveAgent`` to manage the
propose → approve → execute lifecycle for autonomous actions.

Permission key convention: ``"{action_type}:{context_key}"``

Approval response parsing
-------------------------
When the user replies to a pending-actions notification, their message is
expected to contain one or more tokens of the form:

    ``{action_id} yes``   or   ``{action_id} no``
    ``yes {action_id}``   or   ``no {action_id}``
    ``always yes {action_id}``  →  approve + remember
    ``always no {action_id}``   →  deny + remember
    ``yes all``  /  ``no all``  →  bulk approve/deny all pending

Call ``parse_approval_response(text, store)`` from any channel message handler
to process these replies without running the full agent.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from orion.core.registry import ToolRegistry
from orion.core.types import ToolResult
from orion.tools._stubs import BaseTool, ToolSpec
from orion.tools.approval_store import (
    DECISION_ALWAYS_APPROVE,
    DECISION_ALWAYS_DENY,
    STATUS_APPROVED,
    STATUS_DENIED,
    TIER_HIGH,
    TIER_LOW,
    TIER_MEDIUM,
    TIER_TRIVIAL,
    ApprovalStore,
    PendingAction,
)

# ---------------------------------------------------------------------------
# Shared store (lazily initialised, one per process)
# ---------------------------------------------------------------------------

_store: Optional[ApprovalStore] = None


def get_store() -> ApprovalStore:
    global _store
    if _store is None:
        _store = ApprovalStore()
    return _store


# ---------------------------------------------------------------------------
# check_permission
# ---------------------------------------------------------------------------


@ToolRegistry.register("check_permission")
class CheckPermissionTool(BaseTool):
    """Look up whether the user has a remembered decision for a permission key."""

    tool_id = "check_permission"

    def __init__(self, store: Optional[ApprovalStore] = None) -> None:
        self._store = store

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="check_permission",
            description=(
                "Check whether the user has a remembered permission decision for "
                "an action pattern. Returns 'always_approve', 'always_deny', or 'unknown'."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "permission_key": {
                        "type": "string",
                        "description": (
                            "Permission pattern key, e.g. "
                            "'email_delete:domain:noreply.github.com'"
                        ),
                    },
                },
                "required": ["permission_key"],
            },
            category="proactive",
        )

    def execute(self, **params: Any) -> ToolResult:
        key = params.get("permission_key", "")
        store = self._store or get_store()
        rule = store.get_permission(key)
        decision = rule.decision if rule else "unknown"
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=decision,
            metadata={"permission_key": key, "decision": decision},
        )


# ---------------------------------------------------------------------------
# queue_action
# ---------------------------------------------------------------------------


@ToolRegistry.register("queue_action")
class QueueActionTool(BaseTool):
    """Queue a proposed action for user approval or immediate execution."""

    tool_id = "queue_action"

    def __init__(self, store: Optional[ApprovalStore] = None) -> None:
        self._store = store

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="queue_action",
            description=(
                "Queue a proposed action. Tier controls whether user approval is required:\n"
                f"  '{TIER_TRIVIAL}' — execute immediately, no approval needed\n"
                f"  '{TIER_LOW}'     — ask once per pattern, then remember\n"
                f"  '{TIER_MEDIUM}'  — ask each time unless user said 'always'\n"
                f"  '{TIER_HIGH}'    — always ask, never auto-remember\n"
                "Returns the action_id so you can reference it in notifications."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action_type": {
                        "type": "string",
                        "description": (
                            "Short slug, e.g. 'email_send', 'email_delete', 'sms_draft_reply'. "
                            "For email_send the payload is {recipient, subject, body}."
                        ),
                    },
                    "description": {
                        "type": "string",
                        "description": "Human-readable description of what will be done.",
                    },
                    "payload": {
                        "type": "object",
                        "description": "JSON payload the executor will use to carry out the action.",
                    },
                    "permission_key": {
                        "type": "string",
                        "description": "Pattern key for permission memory lookup.",
                    },
                    "tier": {
                        "type": "string",
                        "enum": [TIER_TRIVIAL, TIER_LOW, TIER_MEDIUM, TIER_HIGH],
                        "description": "Approval tier.",
                    },
                },
                "required": [
                    "action_type",
                    "description",
                    "payload",
                    "permission_key",
                    "tier",
                ],
            },
            category="proactive",
        )

    def execute(self, **params: Any) -> ToolResult:
        store = self._store or get_store()
        if params.get("action_type") == "email_send":
            # Catch a mistyped address at draft time ("example.e"), while the
            # user is still here to correct it -- not after they said "send it".
            from orion.tools.email_send import is_valid_address

            payload = params.get("payload") or {}
            recipient = payload.get("recipient") or payload.get("to") or ""
            if isinstance(recipient, list):
                recipient = recipient[0] if recipient else ""
            if not is_valid_address(str(recipient)):
                return ToolResult(
                    tool_name=self.spec.name,
                    success=False,
                    content=(
                        f"'{recipient}' is not a complete email address, so no draft was "
                        "created. Ask the user to repeat the address, then queue it again."
                    ),
                )
        action = store.queue_action(
            action_type=params["action_type"],
            description=params["description"],
            payload=params.get("payload", {}),
            permission_key=params["permission_key"],
            tier=params["tier"],
        )
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=action.id,
            metadata={"action_id": action.id, "status": action.status},
        )


# ---------------------------------------------------------------------------
# get_pending_actions
# ---------------------------------------------------------------------------


@ToolRegistry.register("get_pending_actions")
class GetPendingActionsTool(BaseTool):
    """Return all pending (not yet decided) actions as a JSON list."""

    tool_id = "get_pending_actions"

    def __init__(self, store: Optional[ApprovalStore] = None) -> None:
        self._store = store

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="get_pending_actions",
            description="Return all pending actions awaiting user approval as a JSON list.",
            parameters={"type": "object", "properties": {}},
            category="proactive",
        )

    def execute(self, **params: Any) -> ToolResult:
        store = self._store or get_store()
        store.expire_stale()
        actions = store.list_pending()
        data = [
            {
                "id": a.id,
                "action_type": a.action_type,
                "description": a.description,
                "tier": a.tier,
                "permission_key": a.permission_key,
                "created_at": a.created_at,
            }
            for a in actions
        ]
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=json.dumps(data, indent=2),
            metadata={"count": len(data)},
        )


# ---------------------------------------------------------------------------
# record_decision
# ---------------------------------------------------------------------------


@ToolRegistry.register("record_decision")
class RecordDecisionTool(BaseTool):
    """Record a user approval or denial for a queued action."""

    tool_id = "record_decision"

    def __init__(self, store: Optional[ApprovalStore] = None) -> None:
        self._store = store

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="record_decision",
            description=(
                "Record the user's approval or denial for a pending action. "
                "Set remember=true to save the decision to permission memory so "
                "the same pattern is handled automatically in future."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action_id": {
                        "type": "string",
                        "description": "The action_id returned by queue_action.",
                    },
                    "approved": {
                        "type": "boolean",
                        "description": "True to approve, false to deny.",
                    },
                    "remember": {
                        "type": "boolean",
                        "description": "Save decision to permission memory for this pattern.",
                    },
                    "notes": {
                        "type": "string",
                        "description": "Optional note to store alongside the permission rule.",
                    },
                },
                "required": ["action_id", "approved"],
            },
            category="proactive",
        )

    def execute(self, **params: Any) -> ToolResult:
        store = self._store or get_store()
        action_id = params["action_id"]
        approved = bool(params.get("approved", False))
        remember = bool(params.get("remember", False))
        notes = params.get("notes", "")

        action = store.get_action(action_id)
        if action is None:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content=f"Action not found: {action_id}",
            )

        new_status = STATUS_APPROVED if approved else STATUS_DENIED
        if not store.decide_pending(action_id, new_status):
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content=(
                    f"Action {action_id} is no longer waiting for a decision "
                    f"(it is {action.status}); nothing was changed."
                ),
            )

        if remember:
            decision = DECISION_ALWAYS_APPROVE if approved else DECISION_ALWAYS_DENY
            store.set_permission(
                action.permission_key,
                decision,
                approved=approved,
                notes=notes,
            )

        msg = f"Action {action_id} {'approved' if approved else 'denied'}."
        if remember:
            msg += f" Permission '{action.permission_key}' saved as {decision}."
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=msg,
            metadata={
                "action_id": action_id,
                "approved": approved,
                "remembered": remember,
            },
        )


# ---------------------------------------------------------------------------
# execute_pending_actions
# ---------------------------------------------------------------------------


@ToolRegistry.register("execute_pending_actions")
class ExecutePendingActionsTool(BaseTool):
    """Execute all approved (or trivial) actions and return a summary."""

    tool_id = "execute_pending_actions"

    def __init__(
        self,
        store: Optional[ApprovalStore] = None,
        executor_fn: Optional[Any] = None,
    ) -> None:
        self._store = store
        # executor_fn(action: PendingAction) -> (success: bool, message: str)
        self._executor_fn = executor_fn

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="execute_pending_actions",
            description=(
                "Execute all approved actions in the queue. "
                "Returns a JSON summary of what succeeded and what failed."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of specific action IDs to execute. "
                        "If omitted, executes all approved actions.",
                    },
                },
            },
            category="proactive",
        )

    def execute(self, **params: Any) -> ToolResult:
        store = self._store or get_store()
        action_ids: Optional[List[str]] = params.get("action_ids")

        if action_ids:
            actions = [a for a in store.list_approved() if a.id in set(action_ids)]
        else:
            actions = store.list_approved()

        results: List[Dict[str, Any]] = []
        for action in actions:
            # Claim the action before running it, so a duplicate or concurrent
            # request can never run the same message, email or install twice.
            if not store.claim_approved(action.id):
                continue
            success, message = self._run_action(action)
            results.append(
                {
                    "id": action.id,
                    "action_type": action.action_type,
                    "description": action.description,
                    "success": success,
                    "message": message,
                }
            )

        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=json.dumps(results, indent=2),
            metadata={"executed": len(results)},
        )

    def _run_action(self, action: PendingAction) -> Tuple[bool, str]:
        if self._executor_fn is not None:
            try:
                return self._executor_fn(action)
            except Exception as exc:
                return False, str(exc)

        # Built-in dispatcher — extend as connectors grow
        payload = action.payload
        atype = action.action_type

        try:
            if atype == "email_delete":
                return _exec_email_delete(payload)
            if atype == "email_archive":
                return _exec_email_archive(payload)
            if atype.startswith("tool_call:"):
                return _exec_tool_call(payload)
            if atype == "email_send":
                from orion.tools.email_send import exec_email_send

                return exec_email_send(payload)
            if atype == "channel_send":
                return _exec_channel_send(payload)
            if atype == "sms_send":
                return _exec_sms_send(payload)
            if atype == "sms_draft_reply":
                # Draft only — surface in next digest, don't send
                return True, f"Draft saved: {payload.get('draft', '')[:80]}"
            if atype == "calendar_decline":
                return _exec_calendar_decline(payload)
            if atype == "calendar_accept":
                return _exec_calendar_accept(payload)
            if atype == "create_tool":
                return _exec_create_tool(payload)
            if atype == "install_app":
                from orion.tools.app_install import exec_install_app

                return exec_install_app(payload)
            if atype == "install_game":
                from orion.tools.game_install import exec_install_game

                return exec_install_game(payload)
            return False, (
                f"No executor registered for action_type '{atype}'. This action "
                "type has no backend implementation -- if this represents a "
                "genuine missing capability, use propose_new_tool to draft a "
                "real tool for it instead of queuing further actions of this "
                "type; it needs your approval and a restart before it works."
            )
        except Exception as exc:
            return False, str(exc)


# ---------------------------------------------------------------------------
# Built-in action executors (thin wrappers around connector/channel APIs)
# ---------------------------------------------------------------------------


def _exec_email_delete(payload: Dict[str, Any]) -> Tuple[bool, str]:
    msg_id = payload.get("message_id", "")
    if not msg_id:
        return False, "Missing message_id in payload"
    try:
        from orion.connectors.gmail import GmailConnector

        conn = GmailConnector()
        conn.delete_message(msg_id)
        return True, f"Deleted email {msg_id}"
    except Exception as exc:
        return False, str(exc)


def _exec_email_archive(payload: Dict[str, Any]) -> Tuple[bool, str]:
    msg_id = payload.get("message_id", "")
    if not msg_id:
        return False, "Missing message_id in payload"
    try:
        from orion.connectors.gmail import GmailConnector

        conn = GmailConnector()
        conn.archive_message(msg_id)
        return True, f"Archived email {msg_id}"
    except Exception as exc:
        return False, str(exc)


_CHANNEL_CLASSES = {}


def _get_channel_classes() -> Dict[str, Any]:
    global _CHANNEL_CLASSES
    if not _CHANNEL_CLASSES:
        classes = {}
        try:
            from orion.channels.discord_channel import DiscordChannel
            classes["discord"] = DiscordChannel
        except ImportError:
            pass
        try:
            from orion.channels.telegram import TelegramChannel
            classes["telegram"] = TelegramChannel
        except ImportError:
            pass
        try:
            from orion.channels.whatsapp_baileys import WhatsAppBaileysChannel
            classes["whatsapp"] = WhatsAppBaileysChannel
        except ImportError:
            pass
        _CHANNEL_CLASSES = classes
    return _CHANNEL_CLASSES


def _normalize_channel_target(platform: str, target: str) -> str:
    """Convert a human-supplied recipient into the address the channel needs.

    WhatsApp addresses users as ``<countrycode><number>@s.whatsapp.net``, but
    people (and the model relaying them) naturally write "+91 90257 00117".
    Anything already containing "@" is assumed to be a real JID and left alone.
    """
    target = (target or "").strip()
    if platform.startswith("whatsapp") and "@" not in target:
        digits = "".join(c for c in target if c.isdigit())
        if digits:
            return f"{digits}@s.whatsapp.net"
    return target


def _exec_tool_call(payload: Dict[str, Any]) -> Tuple[bool, str]:
    """Run a confirmation-required tool call the user approved.

    Only tools whose spec requires confirmation are accepted here -- the queue
    exists to put a human in front of those, not to become a side door that
    runs any tool by name.
    """
    from orion.core.registry import ToolRegistry

    name = str(payload.get("tool", ""))
    arguments = payload.get("arguments") or {}
    if not ToolRegistry.contains(name):
        return False, f"Tool '{name}' is not available."
    entry = ToolRegistry.get(name)
    tool = entry() if isinstance(entry, type) else entry
    if not getattr(tool.spec, "requires_confirmation", False):
        return False, f"Tool '{name}' does not go through the approval queue."
    try:
        result = tool.execute(**arguments)
    except Exception as exc:
        return False, f"{name} failed: {exc}"
    return bool(result.success), str(result.content)[:2000]


def _exec_channel_send(payload: Dict[str, Any]) -> Tuple[bool, str]:
    """Send a message via a chat platform channel (discord, telegram, whatsapp).

    Only called after a human has genuinely approved the queued action via
    parse_approval_response() — see routes.py's chat_completions hook.
    """
    platform = (payload.get("platform") or "").strip().lower()
    target = payload.get("target", "")
    content = payload.get("content", "")
    if not platform or not target or not content:
        return False, "Missing 'platform', 'target', or 'content' in payload"

    # Prefer the connection this process already has open. Constructing a new
    # instance works for stateless channels but cannot send on ones that own a
    # live session (WhatsApp), and connecting a second one would fight the
    # first for the single session WhatsApp allows.
    from orion.channels.live import canonical_key, get_live_channel

    live = get_live_channel(platform)
    if live is not None:
        send_target = _normalize_channel_target(platform, target)
        try:
            ok = live.send(send_target, content, conversation_id=send_target)
            if ok:
                return True, f"Sent via {platform} to {target}"
            return False, (
                f"{platform} is connected but the send failed. The recipient "
                f"'{target}' may not be reachable, or the connection dropped."
            )
        except Exception as exc:
            return False, f"{platform} send error: {exc}"

    classes = _get_channel_classes()
    channel_cls = classes.get(platform) or classes.get(canonical_key(platform))
    if channel_cls is None:
        return False, (
            f"Platform '{platform}' is not connected. Supported: {', '.join(classes) or '(none)'}."
        )

    if platform.startswith("whatsapp"):
        # Never construct-and-connect WhatsApp here: that would start a second
        # bridge against the same auth and break the running connection.
        return False, (
            "WhatsApp isn't connected in this session, so the message was not sent. "
            "Make sure the Orion app is running with the WhatsApp channel enabled, "
            "then try again."
        )

    try:
        channel = channel_cls()
        ok = channel.send(target, content)
        if ok:
            return True, f"Sent via {platform} to {target}"
        return False, (
            f"{platform} send failed — check that its credentials are configured "
            f"(e.g. {platform.upper()}_BOT_TOKEN)."
        )
    except Exception as exc:
        return False, f"{platform} send error: {exc}"


def _exec_sms_send(payload: Dict[str, Any]) -> Tuple[bool, str]:
    contact = payload.get("contact", "")
    body = payload.get("body", "")
    if not contact or not body:
        return False, "Missing contact or body in payload"
    try:
        from orion.channels.imessage_daemon import send_imessage

        send_imessage(contact, body)
        return True, f"Sent iMessage to {contact}"
    except Exception as exc:
        return False, str(exc)


def _exec_calendar_decline(payload: Dict[str, Any]) -> Tuple[bool, str]:
    event_id = payload.get("event_id", "")
    calendar_id = payload.get("calendar_id", "primary")
    if not event_id:
        return False, "Missing event_id in payload"
    try:
        from orion.connectors.gcalendar import GCalendarConnector

        conn = GCalendarConnector()
        conn.decline_event(event_id, calendar_id=calendar_id)
        return True, f"Declined calendar event {event_id}"
    except Exception as exc:
        return False, str(exc)


def _exec_calendar_accept(payload: Dict[str, Any]) -> Tuple[bool, str]:
    event_id = payload.get("event_id", "")
    calendar_id = payload.get("calendar_id", "primary")
    if not event_id:
        return False, "Missing event_id in payload"
    try:
        from orion.connectors.gcalendar import GCalendarConnector

        conn = GCalendarConnector()
        conn.accept_event(event_id, calendar_id=calendar_id)
        return True, f"Accepted calendar event {event_id}"
    except Exception as exc:
        return False, str(exc)


def _add_to_agent_tools(name: str) -> None:
    """Append `name` to agent.tools in config.toml, preserving formatting.

    Mirrors config_routes.py's ``_persist``/``_enabled_tool_list`` pattern
    exactly (including the UTF-8 read/write fix -- Windows defaults
    str.open()/read_text() to the system codepage, which fails on this
    file's non-ASCII bytes) rather than importing the server module, to
    avoid a tools -> server import cycle.
    """
    import os

    import tomlkit

    from orion.core.config import DEFAULT_CONFIG_DIR

    path = Path(os.environ.get("OPENORION_CONFIG", str(DEFAULT_CONFIG_DIR / "config.toml")))
    if path.exists():
        doc = tomlkit.parse(path.read_text(encoding="utf-8"))
    else:
        doc = tomlkit.document()
        path.parent.mkdir(parents=True, exist_ok=True)

    if "agent" not in doc:
        doc.add("agent", tomlkit.table())
    agent_table = doc["agent"]

    raw = agent_table.get("tools", "")
    # agent.tools is normally a comma-joined string, but config_routes.py's
    # own _enabled_tool_list() also accepts a native TOML array -- handle
    # both here too, since str(["a", "b"]) is "['a', 'b']" and blindly
    # splitting that on commas would silently corrupt the list.
    from orion.core.tool_names import configured_tool_list, serialize_tool_list

    current = configured_tool_list(list(raw) if isinstance(raw, list) else str(raw))
    if current is None:
        return  # every tool is enabled, the new one included
    if name not in current:
        current.append(name)
    agent_table["tools"] = serialize_tool_list(current)

    path.write_text(tomlkit.dumps(doc), encoding="utf-8")


def _exec_create_tool(payload: Dict[str, Any]) -> Tuple[bool, str]:
    """Write an approved generated tool to disk, enable it, and restart.

    Only reached from execute_pending_actions after a real human "yes" on
    the queued create_tool action (see tool_forge.py's propose_new_tool,
    which is what originally queued it). Re-validates the code here too --
    defense in depth against a stale or tampered payload, since an
    arbitrary amount of time can pass between queuing and approval.
    """
    from orion.tools.tool_forge import (
        GENERATED_DIR,
        _sandbox_smoke_test,
        _static_validate,
    )

    name = (payload.get("name") or "").strip()
    source = payload.get("implementation_code", "")
    if not name or not source:
        return False, "Payload missing 'name' or 'implementation_code'"

    if ToolRegistry.contains(name):
        return False, f"A tool named '{name}' is already registered"

    ok, reason = _static_validate(name, source)
    if not ok:
        return False, f"Re-validation failed at approval time, nothing written: {reason}"

    # The candidate code is only ever executed here, after a real human
    # "yes" -- propose_new_tool's own validation is pure AST inspection
    # (see tool_forge.py), never exec(). This is the actual approval
    # boundary: nothing the model proposes runs before this point.
    smoke_ok, smoke_detail = _sandbox_smoke_test(source)
    if not smoke_ok:
        return False, (
            f"Approved, but the smoke test failed, so nothing was written: "
            f"{smoke_detail[:300]}"
        )

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    init_file = GENERATED_DIR / "__init__.py"
    if not init_file.exists():
        init_file.write_text('"""Generated tools."""\n', encoding="utf-8")

    target = GENERATED_DIR / f"{name}.py"
    if target.exists():
        return False, f"{target.name} already exists on disk -- refusing to overwrite it"
    target.write_text(source, encoding="utf-8")

    try:
        _add_to_agent_tools(name)
    except Exception as exc:
        return False, (
            f"Wrote {target.name} but failed to enable it in config.toml: {exc}. "
            "Add it to agent.tools manually, then restart Orion."
        )

    try:
        from orion.system.self_restart import schedule_self_restart

        schedule_self_restart()
    except Exception as exc:
        return True, (
            f"Wrote {target.name} and enabled it in agent.tools, but could not "
            f"schedule the automatic restart ({exc}). Restart Orion manually "
            "to make it callable."
        )

    return True, (
        f"Wrote {target.name}, enabled it in agent.tools, and a restart is "
        "underway. It will be callable once the backend comes back up "
        "(a few seconds) -- not in this turn."
    )


# ---------------------------------------------------------------------------
# Approval response parser (for channel message handlers)
# ---------------------------------------------------------------------------

# Matches: "abc123 yes", "yes abc123", "always yes abc123", "yes all", etc.
_APPROVAL_RE = re.compile(
    r"\b(?P<always>always\s+)?(?P<decision>yes|no|approve|deny)\s+(?P<target>[a-f0-9]{12}|all)\b"
    r"|"
    r"\b(?P<target2>[a-f0-9]{12}|all)\s+(?P<always2>always\s+)?(?P<decision2>yes|no|approve|deny)\b",
    re.IGNORECASE,
)

# A bare "yes"/"no" with no id/target — the whole message, nothing else.
# Only applied when exactly one action is pending, so it can't accidentally
# resolve the wrong one of several simultaneous drafts.
# Bare replies to "reply yes to send, no to cancel". Voice transcripts arrive
# capitalised and punctuated ("Yes, send it."), so both are tolerated.
_APPROVE_WORDS = (
    r"(?:yes|yeah|yep|yup|y|sure|approve|approved|confirm|confirmed|ok|okay|"
    r"go ahead|do it|send it|send|yes please|please send it|yes send it|"
    r"yes,? send it|yes,? go ahead|go for it)"
)
_DENY_WORDS = r"(?:no|nope|n|deny|cancel|stop|don'?t|do not send|don'?t send it|cancel it)"
_BARE_RE = re.compile(
    rf"^\s*(?:{_APPROVE_WORDS}|{_DENY_WORDS})\s*[.!]*\s*$",
    re.IGNORECASE,
)
_BARE_APPROVE_RE = re.compile(rf"^\s*{_APPROVE_WORDS}\s*[.!]*\s*$", re.IGNORECASE)


def parse_approval_response(
    text: str,
    store: Optional[ApprovalStore] = None,
) -> List[Dict[str, Any]]:
    """Parse a free-text message for approval tokens and update the store.

    Returns a list of dicts describing each decision that was processed,
    for use in an acknowledgement message back to the user.

    Call this from any channel message handler before routing the message
    to the main agent, e.g. inside the iMessage daemon or Telegram bot.
    """
    s = store or get_store()
    processed: List[Dict[str, Any]] = []

    # Notification template displays ids as `[abc123]`; users naturally reply
    # with `{abc123} yes`, `(abc123) yes`, etc.  Strip those surrounding
    # brackets/braces/parens before regex matching so the word-boundary
    # check sees a clean id.
    text = re.sub(r"[\[\]\{\}\(\)]", " ", text)

    for m in _APPROVAL_RE.finditer(text):
        target = (m.group("target") or m.group("target2") or "").lower()
        raw_decision = (m.group("decision") or m.group("decision2") or "").lower()
        always = bool(m.group("always") or m.group("always2"))

        approved = raw_decision in ("yes", "approve")

        if target == "all":
            pending = s.list_pending()
            for action in pending:
                new_status = STATUS_APPROVED if approved else STATUS_DENIED
                if not s.decide_pending(action.id, new_status):
                    continue
                if always and action.tier in (TIER_LOW, TIER_MEDIUM):
                    decision = (
                        DECISION_ALWAYS_APPROVE if approved else DECISION_ALWAYS_DENY
                    )
                    s.set_permission(action.permission_key, decision, approved=approved)
                processed.append(
                    {"id": action.id, "approved": approved, "remembered": always}
                )
        else:
            action = s.get_action(target)
            if action is None:
                continue
            new_status = STATUS_APPROVED if approved else STATUS_DENIED
            # Only a still-pending, unexpired action can be decided: repeating
            # "abc123 yes" after it ran must not approve (and run) it again.
            if not s.decide_pending(target, new_status):
                continue
            remember = always and action.tier in (TIER_LOW, TIER_MEDIUM)
            if remember:
                decision = DECISION_ALWAYS_APPROVE if approved else DECISION_ALWAYS_DENY
                s.set_permission(action.permission_key, decision, approved=approved)
            processed.append(
                {"id": target, "approved": approved, "remembered": remember}
            )

    if not processed and _BARE_RE.match(text.strip()):
        pending = s.list_pending()
        if pending:
            # A bare reply answers the most recent draft -- the one the user
            # was just shown. Earlier drafts of the same kind were replaced by
            # corrections ("the domain is example.edu"), so they are withdrawn
            # rather than left pending where a later "yes" could send the
            # wrong one. list_pending() is ordered oldest first.
            action = pending[-1]
            approved = bool(_BARE_APPROVE_RE.match(text.strip()))
            new_status = STATUS_APPROVED if approved else STATUS_DENIED
            if s.decide_pending(action.id, new_status):
                processed.append(
                    {"id": action.id, "approved": approved, "remembered": False}
                )
                for older in pending[:-1]:
                    if older.action_type == action.action_type:
                        s.decide_pending(older.id, STATUS_DENIED)

    return processed


__all__ = [
    "CheckPermissionTool",
    "ExecutePendingActionsTool",
    "GetPendingActionsTool",
    "QueueActionTool",
    "RecordDecisionTool",
    "get_store",
    "parse_approval_response",
]
