"""SkillManageTool — create, list, load, or delete agent-authored skills."""

from __future__ import annotations

import json
import re

from pathlib import Path
from typing import Any, List

from orion.core.registry import ToolRegistry
from orion.core.types import ToolResult
from orion.tools._stubs import BaseTool, ToolSpec


@ToolRegistry.register("skill_manage")
class SkillManageTool(BaseTool):
    """Manage agent-authored procedural skills."""

    def __init__(self, skills_dir: Path | str = "~/.orion/skills/") -> None:
        self._skills_dir = Path(skills_dir).expanduser()

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="skill_manage",
            description="Create, list, load, or delete agent-authored skills.",
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["create", "list", "load", "delete"],
                        "description": "Action to perform.",
                    },
                    "name": {
                        "type": "string",
                        "description": "Skill name (for create/load/delete).",
                    },
                    "description": {
                        "type": "string",
                        "description": "Skill description (for create).",
                    },
                    "steps": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "tool_name": {"type": "string"},
                                "arguments_template": {"type": "string"},
                                "output_key": {"type": "string"},
                            },
                            "required": ["tool_name"],
                        },
                        "description": (
                            "List of step dicts with tool_name and optional"
                            " arguments_template (for create)."
                        ),
                    },
                },
                "required": ["action"],
            },
            category="skill",
        )

    def execute(self, **params: Any) -> ToolResult:
        action = params.get("action", "list")
        name = params.get("name", "")
        if action == "create":
            return self._create(
                name, params.get("description", ""), params.get("steps", [])
            )
        elif action == "list":
            return self._list()
        elif action == "load":
            return self._load(name)
        elif action == "delete":
            return self._delete(name)
        return ToolResult(
            tool_name=self.spec.name,
            success=False,
            content=f"Unknown action: {action}",
        )

    def _create(self, name: str, description: str, steps: List[dict]) -> ToolResult:
        if not name:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content="Skill name is required.",
            )
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name):
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content="Skill name may only use letters, digits, '-' and '_' (max 64).",
            )
        self._skills_dir.mkdir(parents=True, exist_ok=True)
        path = self._skills_dir / f"{name}.toml"
        # json.dumps yields valid TOML basic strings; the old f-strings broke
        # the file on any quote, and plain-string steps crashed with
        # "'str' object has no attribute 'get'".
        lines = [
            "[skill]",
            f"name = {json.dumps(name)}",
            f"description = {json.dumps(description or '')}",
            "",
        ]
        for step in steps or []:
            if isinstance(step, str):
                step = {"tool_name": step}
            if not isinstance(step, dict) or not step.get("tool_name"):
                continue
            lines.append("[[skill.steps]]")
            lines.append(f"tool_name = {json.dumps(str(step['tool_name']))}")
            for key in ("arguments_template", "output_key"):
                if key in step:
                    lines.append(f"{key} = {json.dumps(str(step[key]))}")
            lines.append("")
        path.write_text("\n".join(lines), encoding="utf-8")
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=f"Created skill: {name}",
        )

    def _list(self) -> ToolResult:
        if not self._skills_dir.exists():
            return ToolResult(
                tool_name=self.spec.name,
                success=True,
                content="No skills directory found.",
            )
        skills = []
        for f in sorted(self._skills_dir.glob("*.toml")):
            skills.append(f.stem)
        if not skills:
            return ToolResult(
                tool_name=self.spec.name,
                success=True,
                content="No skills found.",
            )
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content="Available skills:\n" + "\n".join(f"- {s}" for s in skills),
        )

    def _load(self, name: str) -> ToolResult:
        path = self._skills_dir / f"{name}.toml"
        if not path.exists():
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content=f"Skill not found: {name}",
            )
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=path.read_text(),
        )

    def _delete(self, name: str) -> ToolResult:
        path = self._skills_dir / f"{name}.toml"
        if not path.exists():
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content=f"Skill not found: {name}",
            )
        path.unlink()
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=f"Deleted skill: {name}",
        )
