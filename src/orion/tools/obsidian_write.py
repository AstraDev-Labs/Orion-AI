"""Obsidian write tool."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from orion.core.registry import ToolRegistry
from orion.core.types import ToolResult
from orion.tools._stubs import BaseTool, ToolSpec


@ToolRegistry.register("obsidian_write_note")
class ObsidianWriteNoteTool(BaseTool):
    """Tool to create or update notes in the local Obsidian vault."""

    tool_id = "obsidian_write_note"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="obsidian_write_note",
            description=(
                "Create a new note or append to an existing note in the local Obsidian vault. "
                "Use this to store memories, facts, user preferences, and long-term knowledge as your 'Brain'."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Title of the note (e.g., 'User Preferences' or 'Project Ideas').",
                    },
                    "content": {
                        "type": "string",
                        "description": "The markdown content to store in the note.",
                    },
                    "mode": {
                        "type": "string",
                        "description": "Either 'overwrite' or 'append'. Defaults to 'append'.",
                        "enum": ["overwrite", "append"],
                        "default": "append",
                    },
                },
                "required": ["title", "content"],
            },
            category="knowledge",
        )

    def execute(self, **params: Any) -> ToolResult:
        title = params.get("title", "").strip()
        content = params.get("content", "")
        mode = params.get("mode", "append")

        if not title or not content:
            return ToolResult(
                tool_name="obsidian_write_note",
                content="Both title and content are required.",
                success=False
            )

        try:
            from orion.core.config import DEFAULT_CONFIG_DIR

            config_path = DEFAULT_CONFIG_DIR / "connectors" / "obsidian.json"
            vault_path = None
            if config_path.exists():
                cfg = json.loads(config_path.read_text(encoding="utf-8"))
                vault_path = cfg.get("path") or cfg.get("vault_path")

            if not vault_path:
                # Fallback to a hardcoded path if connector is not configured
                vault_path = "C:/Users/Tharun/Documents/Orion AI/ObsidianVault"

            vault_dir = Path(vault_path)
            if not vault_dir.exists():
                vault_dir.mkdir(parents=True, exist_ok=True)

            # Clean filename
            safe_title = "".join(c for c in title if c.isalnum() or c in (" ", "-", "_")).strip()
            if not safe_title:
                safe_title = "Untitled_Memory"

            note_path = vault_dir / f"{safe_title}.md"

            if mode == "append" and note_path.exists():
                with open(note_path, "a", encoding="utf-8") as f:
                    f.write(f"\n\n{content}\n")
                msg = f"Appended memory to Obsidian note: {safe_title}.md"
            else:
                with open(note_path, "w", encoding="utf-8") as f:
                    f.write(f"# {title}\n\n{content}\n")
                msg = f"Created new Obsidian memory note: {safe_title}.md"

            return ToolResult(tool_name="obsidian_write_note", content=msg, success=True)

        except Exception as e:
            import traceback
            traceback.print_exc()
            return ToolResult(tool_name="obsidian_write_note", content=f"Error writing to obsidian vault: {e}", success=False)
