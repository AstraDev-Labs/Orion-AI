"""Obsidian search tool."""

from __future__ import annotations

from typing import Any

from orion.connectors.obsidian import ObsidianConnector
from orion.core.registry import ToolRegistry
from orion.core.types import ToolResult
from orion.tools._stubs import BaseTool, ToolSpec


@ToolRegistry.register("obsidian_search_notes")
class ObsidianSearchNotesTool(BaseTool):
    """Tool to search notes in the local Obsidian vault."""

    tool_id = "obsidian_search_notes"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="obsidian_search_notes",
            description=(
                "Search notes in the local Obsidian vault by keyword. "
                "Returns matching note titles and snippets."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query string",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Maximum number of results to return",
                        "default": 10,
                    },
                },
                "required": ["query"],
            },
            category="knowledge",
        )

    def execute(self, **params: Any) -> ToolResult:
        query = params.get("query", "")
        top_k = int(params.get("top_k", 10))

        if not query:
            return ToolResult(tool_name="obsidian_search_notes", content="No query provided.", success=False)

        try:
            import json

            from orion.core.config import DEFAULT_CONFIG_DIR

            config_path = DEFAULT_CONFIG_DIR / "connectors" / "obsidian.json"
            if not config_path.exists():
                return ToolResult(
                    tool_name="obsidian_search_notes",
                    content="Obsidian connector not configured. No vault path found. Link your vault in Connections (HUD, key C) → Obsidian vault.",
                    success=False
                )

            cfg = json.loads(config_path.read_text())
            vault_path = cfg.get("path") or cfg.get("vault_path")
            if not vault_path:
                return ToolResult(tool_name="obsidian_search_notes", content="Obsidian vault path is missing in configuration.", success=False)

            connector = ObsidianConnector(vault_path)
            if not connector.is_connected():
                 return ToolResult(tool_name="obsidian_search_notes", content="Obsidian connector path is invalid.", success=False)

            results = []
            q_lower = query.lower()

            # Simple keyword search through the vault files
            for doc in connector.sync():
                if q_lower in doc.content.lower() or q_lower in doc.title.lower():
                    results.append(doc)

            results.sort(key=lambda d: d.timestamp, reverse=True)
            results = results[:top_k]

            if not results:
                return ToolResult(tool_name="obsidian_search_notes", content="No matching notes found.", success=True)

            lines = []
            for i, res in enumerate(results, 1):
                lines.append(f"**Result {i}:** [{res.title}]({res.url})")
                snippet = res.content[:500] + ("..." if len(res.content) > 500 else "")
                lines.append(snippet)
                lines.append("")

            return ToolResult(tool_name="obsidian_search_notes", content="\n".join(lines).rstrip(), success=True)

        except Exception as e:
            import traceback
            traceback.print_exc()
            return ToolResult(tool_name="obsidian_search_notes", content=f"Error reading obsidian vault: {e}", success=False)
