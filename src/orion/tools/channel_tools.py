"""Channel MCP tools — expose channel operations as BaseTool instances.

These tools wrap the ``BaseChannel`` ABC so that channel operations
(send, list, status) are discoverable and callable via MCP.
"""

from __future__ import annotations

from typing import Any

from orion.channels._stubs import BaseChannel
from orion.core.registry import ToolRegistry
from orion.core.types import ToolResult
from orion.tools._stubs import BaseTool, ToolSpec


def _live_channel_names() -> list[str]:
    from orion.channels.live import get_live_channel

    return [n for n in ("whatsapp", "telegram", "discord", "slack") if get_live_channel(n) is not None]


@ToolRegistry.register("channel_send")
class ChannelSendTool(BaseTool):
    """Draft a message to a contact on a connected channel, sent after approval.

    Messages go out on the user's behalf, so nothing is sent directly: the
    message is queued and only sent when the user answers yes (see
    proactive_tools.parse_approval_response and _exec_channel_send). It used
    to call channel.send() straight away -- and in the app it had no channel
    at all, so it could only ever fail.
    """

    tool_id = "channel_send"
    is_local = False

    def __init__(self, channel: BaseChannel | None = None) -> None:
        self._channel = channel

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="channel_send",
            description=(
                "Draft a message to someone on WhatsApp, Telegram, Discord or Slack. The user "
                "must approve before it is sent; tell them exactly what was drafted."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "platform": {
                        "type": "string",
                        "enum": ["whatsapp", "telegram", "discord", "slack"],
                        "description": "Which app to send with. Defaults to the connected one.",
                    },
                    "channel": {
                        "type": "string",
                        "description": "Recipient: phone number with country code (WhatsApp), or chat/channel ID.",
                    },
                    "content": {
                        "type": "string",
                        "description": "The message text.",
                    },
                },
                "required": ["channel", "content"],
            },
            category="channel",
        )

    @staticmethod
    def _default_platform() -> str:
        from orion.channels.live import get_live_channel

        for name in ("whatsapp", "telegram", "discord", "slack"):
            if get_live_channel(name) is not None:
                return name
        return "whatsapp"

    def execute(self, **params: Any) -> ToolResult:
        target = str(params.get("channel", "")).strip()
        content = str(params.get("content", "")).strip()
        if not target or not content:
            return ToolResult(
                tool_name="channel_send",
                content="Both 'channel' (the recipient) and 'content' are required.",
                success=False,
            )
        platform = str(params.get("platform") or self._default_platform()).strip().lower()
        try:
            from orion.tools.proactive_tools import TIER_HIGH, get_store

            action = get_store().queue_action(
                action_type="channel_send",
                description=f"Send to {target} on {platform}: {content[:120]}",
                payload={"platform": platform, "target": target, "content": content},
                permission_key=f"channel_send:{platform}:{target}",
                tier=TIER_HIGH,
            )
        except Exception as exc:
            return ToolResult(
                tool_name="channel_send",
                content=f"Could not draft the message: {exc}",
                success=False,
            )
        return ToolResult(
            tool_name="channel_send",
            content=(
                f"Nothing sent yet. Drafted (id {action.id}): send to {target} on {platform}: "
                f"'{content}'. Tell the user this in one line and ask them to say yes to send "
                "or no to cancel."
            ),
            success=True,
            metadata={"action_id": action.id, "status": "pending_approval"},
        )


@ToolRegistry.register("channel_list")
class ChannelListTool(BaseTool):
    """MCP-exposed tool: list available channels."""

    tool_id = "channel_list"

    def __init__(self, channel: BaseChannel | None = None) -> None:
        self._channel = channel

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="channel_list",
            description="List available messaging channels.",
            parameters={
                "type": "object",
                "properties": {},
            },
            category="channel",
        )

    def execute(self, **params: Any) -> ToolResult:
        if self._channel is None:
            names = _live_channel_names()
            return ToolResult(
                tool_name="channel_list",
                content="\n".join(names) if names else "No messaging app is connected. Link one in Connections.",
                success=True,
            )
        try:
            channels = self._channel.list_channels()
            if not channels:
                return ToolResult(
                    tool_name="channel_list",
                    content="No channels available.",
                    success=True,
                )
            return ToolResult(
                tool_name="channel_list",
                content="\n".join(channels),
                success=True,
            )
        except Exception as exc:
            return ToolResult(
                tool_name="channel_list",
                content=f"List error: {exc}",
                success=False,
            )


@ToolRegistry.register("channel_status")
class ChannelStatusTool(BaseTool):
    """MCP-exposed tool: check channel connection status."""

    tool_id = "channel_status"

    def __init__(self, channel: BaseChannel | None = None) -> None:
        self._channel = channel

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="channel_status",
            description="Check the connection status of the messaging channel.",
            parameters={
                "type": "object",
                "properties": {},
            },
            category="channel",
        )

    def execute(self, **params: Any) -> ToolResult:
        if self._channel is None:
            from orion.channels.live import get_live_channel

            lines = []
            for name in _live_channel_names():
                try:
                    lines.append(f"{name}: {get_live_channel(name).status().value}")
                except Exception as exc:
                    lines.append(f"{name}: unknown ({exc})")
            return ToolResult(
                tool_name="channel_status",
                content="\n".join(lines) if lines else "No messaging app is connected. Link one in Connections.",
                success=True,
            )
        try:
            st = self._channel.status()
            return ToolResult(
                tool_name="channel_status",
                content=f"Channel status: {st.value}",
                success=True,
            )
        except Exception as exc:
            return ToolResult(
                tool_name="channel_status",
                content=f"Status error: {exc}",
                success=False,
            )


__all__ = [
    "ChannelListTool",
    "ChannelSendTool",
    "ChannelStatusTool",
]
