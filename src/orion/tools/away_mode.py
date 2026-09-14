"""away_mode tool — lets the agent set/clear the user's manual away flag.

Used when the user says something like "I'm stepping out" or "I'm back" so
the channel auto-reply pipeline (see ``orion.system.core.OrionSystem.wire_channel``)
knows whether to answer incoming messages on the user's behalf.
"""

from __future__ import annotations

from typing import Any

from orion.core.activity import get_manual_away, set_manual_away
from orion.core.registry import ToolRegistry
from orion.core.types import ToolResult
from orion.tools._stubs import BaseTool, ToolSpec


@ToolRegistry.register("away_mode")
class AwayModeTool(BaseTool):
    """Set or check whether the user is manually marked as away."""

    tool_id = "away_mode"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="away_mode",
            description=(
                "Mark the user as away or back, or check current away status. "
                "Call with action='away' when the user says something like "
                "'I'm stepping out', 'I'll be away', or 'go quiet for a bit'. "
                "Call with action='back' when they say 'I'm back' or similar. "
                "While away, incoming channel messages (WhatsApp, etc.) are "
                "answered automatically on the user's behalf; while back, they "
                "are not."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "away | back | status",
                    },
                },
                "required": ["action"],
            },
            category="system",
            timeout_seconds=5.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        action = (params.get("action") or "").strip().lower()

        # Report no-ops explicitly, and tell the model the work is finished.
        # Setting a flag that is already set looks identical to a failed call
        # from the model's side, which invited it to "try again" -- observed
        # live: it called away_mode(back) twice and then apologised to the user
        # instead of confirming, having burned a turn on a redundant call.
        if action == "away":
            if get_manual_away():
                return ToolResult(
                    tool_name="away_mode",
                    content=(
                        "Already marked as away — nothing changed. This is done; "
                        "tell the user and do not call away_mode again."
                    ),
                    success=True,
                )
            set_manual_away(True)
            return ToolResult(
                tool_name="away_mode",
                content=(
                    "Done — marked as away, and I'll auto-reply to incoming messages "
                    "until you're back. Tell the user and do not call away_mode again."
                ),
                success=True,
            )
        if action == "back":
            if not get_manual_away():
                return ToolResult(
                    tool_name="away_mode",
                    content=(
                        "Already marked as back — nothing changed. This is done; "
                        "tell the user and do not call away_mode again."
                    ),
                    success=True,
                )
            set_manual_away(False)
            return ToolResult(
                tool_name="away_mode",
                content=(
                    "Done — welcome back, and I've stopped auto-replying to incoming "
                    "messages. Tell the user and do not call away_mode again."
                ),
                success=True,
            )
        if action == "status":
            away = get_manual_away()
            return ToolResult(
                tool_name="away_mode",
                content=f"Manual away flag is currently {'on' if away else 'off'}.",
                success=True,
            )

        return ToolResult(
            tool_name="away_mode",
            content=f"Unknown action '{action}'. Use away, back, or status.",
            success=False,
        )


__all__ = ["AwayModeTool"]
