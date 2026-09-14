"""Which tools the chat agent is given, from ``[agent] tools`` in config.toml.

- unset / empty: every tool. A fresh install used to get only calculator and
  web_search, so a new user's Orion could not play music, change the volume,
  open apps or draft messages until they found the Tools panel.
- ``"none"``: no tools (what switching off the last tool writes).
- a comma-separated list (or TOML array): exactly those tools.

No imports from orion.tools or orion.server here, so both can use it.
"""

from __future__ import annotations

from typing import Iterable, List

# Registered for internal use only, never offered to the chat agent:
# docker_shell_exec runs inside a TerminalBench task container and nowhere
# else; record_decision would let the model approve its own queued actions.
INTERNAL_TOOLS = frozenset({"docker_shell_exec", "record_decision"})

NO_TOOLS = "none"


def configured_tool_list(raw: object) -> List[str] | None:
    """The explicit list in config, or None when every tool is enabled."""
    if isinstance(raw, (list, tuple)):
        names = [t.strip() for t in raw if isinstance(t, str) and t.strip()]
    else:
        names = [t.strip() for t in str(raw or "").split(",") if t.strip()]
    if not names:
        return None
    if names == [NO_TOOLS]:
        return []
    return [n for n in names if n != NO_TOOLS]


def enabled_tool_names(raw: object, registered: Iterable[str]) -> List[str]:
    """Tool names the agent gets, in registry order, never internal ones."""
    available = [n for n in registered if n not in INTERNAL_TOOLS]
    configured = configured_tool_list(raw)
    if configured is None:
        return available
    wanted = set(configured)
    return [n for n in available if n in wanted]


def serialize_tool_list(names: Iterable[str]) -> str:
    """Config value for an explicit selection (``"none"`` when it is empty)."""
    joined = ",".join(n for n in names if n)
    return joined or NO_TOOLS


__all__ = [
    "INTERNAL_TOOLS",
    "NO_TOOLS",
    "configured_tool_list",
    "enabled_tool_names",
    "serialize_tool_list",
]
