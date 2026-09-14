"""Smart reminders tool — OS-native scheduled notifications.

Creates a one-shot Windows Task Scheduler task that pops up a message box
at the requested date/time, so the reminder fires even if ORION isn't
running. Reminder metadata is tracked in ~/.orion/reminders.json so they
can be listed and cancelled.
"""

from __future__ import annotations

import json
import platform
import subprocess
import uuid
from datetime import datetime
from typing import Any

from orion.core.config import DEFAULT_CONFIG_DIR
from orion.core.registry import ToolRegistry
from orion.core.types import ToolResult
from orion.tools._stubs import BaseTool, ToolSpec

_STORE_PATH = DEFAULT_CONFIG_DIR / "reminders.json"
_SCRIPTS_DIR = DEFAULT_CONFIG_DIR / "reminders"
_TASK_PREFIX = "Orion_Reminder_"


def _load() -> dict[str, dict[str, Any]]:
    if not _STORE_PATH.exists():
        return {}
    try:
        return json.loads(_STORE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(reminders: dict[str, dict[str, Any]]) -> None:
    DEFAULT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _STORE_PATH.write_text(json.dumps(reminders, indent=2), encoding="utf-8")


def _run(cmd: list[str]) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0,
        )
        return proc.returncode == 0, (proc.stdout or proc.stderr or "").strip()
    except Exception as exc:
        return False, str(exc)


def _escape_ps(text: str) -> str:
    return text.replace("'", "''")


@ToolRegistry.register("reminder")
class ReminderTool(BaseTool):
    """Create, list, and cancel scheduled reminders."""

    tool_id = "reminder"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="reminder",
            description=(
                "Set, list, or cancel a timed reminder. The reminder fires as a "
                "desktop notification at the given date/time even if ORION isn't "
                "running, via the OS task scheduler."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "'create' (default), 'list', or 'cancel'.",
                    },
                    "date": {
                        "type": "string",
                        "description": "Date in YYYY-MM-DD format (create only).",
                    },
                    "time": {
                        "type": "string",
                        "description": "Time in HH:MM 24h format (create only).",
                    },
                    "message": {
                        "type": "string",
                        "description": "The reminder text (create only).",
                    },
                    "reminder_id": {
                        "type": "string",
                        "description": "ID of the reminder to cancel (cancel only, from 'list').",
                    },
                },
                "required": [],
            },
            category="productivity",
            required_capabilities=["system:admin"],
            timeout_seconds=20.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        if platform.system() != "Windows":
            return ToolResult(
                tool_name="reminder",
                content="reminder currently only supports Windows.",
                success=False,
            )

        action = (params.get("action") or "create").strip().lower()

        if action == "list":
            return self._list()
        if action == "cancel":
            return self._cancel(params.get("reminder_id", ""))
        if action == "create":
            return self._create(
                params.get("date", ""), params.get("time", ""), params.get("message", "")
            )
        return ToolResult(
            tool_name="reminder",
            content=f"Unknown action '{action}'. Use create, list, or cancel.",
            success=False,
        )

    def _create(self, date: str, time: str, message: str) -> ToolResult:
        if not (date and time and message):
            return ToolResult(
                tool_name="reminder",
                content="create requires 'date' (YYYY-MM-DD), 'time' (HH:MM), and 'message'.",
                success=False,
            )
        try:
            when = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
        except ValueError:
            return ToolResult(
                tool_name="reminder",
                content="Invalid date/time. Use YYYY-MM-DD for date and HH:MM (24h) for time.",
                success=False,
            )

        reminder_id = uuid.uuid4().hex[:8]
        task_name = f"{_TASK_PREFIX}{reminder_id}"

        # Write the popup as its own .ps1 file rather than inlining it into the
        # scheduled task's -Argument string: nesting a PowerShell string literal
        # (for the message) inside a quoted -Command inside a quoted -Argument
        # runs into unresolvable quote-escaping conflicts. A file avoids all of it.
        _SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
        script_path = _SCRIPTS_DIR / f"{reminder_id}.ps1"
        script_path.write_text(
            "Add-Type -AssemblyName System.Windows.Forms\n"
            f"[System.Windows.Forms.MessageBox]::Show('{_escape_ps(message)}', 'ORION Reminder')\n",
            encoding="utf-8",
        )

        # Trigger built from a real DateTime object rather than a locale-formatted
        # string, so this works regardless of the machine's short date pattern
        # (schtasks /sd is locale-sensitive and was failing on en-IN).
        iso_when = when.strftime("%Y-%m-%dT%H:%M:%S")
        register_cmd = (
            "$action = New-ScheduledTaskAction -Execute 'powershell.exe' "
            f'-Argument \'-WindowStyle Hidden -ExecutionPolicy Bypass -File "{script_path}"\'; '
            f"$trigger = New-ScheduledTaskTrigger -Once -At ([datetime]'{iso_when}'); "
            f"Register-ScheduledTask -TaskName '{task_name}' -Action $action "
            "-Trigger $trigger -Force | Out-Null"
        )

        ok, out = _run(["powershell", "-NoProfile", "-Command", register_cmd])
        if not ok:
            return ToolResult(
                tool_name="reminder",
                content=f"Failed to schedule reminder: {out}",
                success=False,
            )

        reminders = _load()
        reminders[reminder_id] = {
            "task_name": task_name,
            "when": when.isoformat(),
            "message": message,
        }
        _save(reminders)

        return ToolResult(
            tool_name="reminder",
            content=f"Reminder set for {when.strftime('%Y-%m-%d %H:%M')}: {message}",
            success=True,
            metadata={"reminder_id": reminder_id},
        )

    def _list(self) -> ToolResult:
        reminders = _load()
        if not reminders:
            return ToolResult(tool_name="reminder", content="No reminders set.", success=True)
        lines = [
            f"[{rid}] {r['when']} — {r['message']}"
            for rid, r in sorted(reminders.items(), key=lambda kv: kv[1]["when"])
        ]
        return ToolResult(
            tool_name="reminder",
            content="\n".join(lines),
            success=True,
            metadata={"reminders": reminders},
        )

    def _cancel(self, reminder_id: str) -> ToolResult:
        reminders = _load()
        entry = reminders.get(reminder_id)
        if not entry:
            return ToolResult(
                tool_name="reminder",
                content=f"No reminder found with id '{reminder_id}'.",
                success=False,
            )
        _run(["schtasks", "/delete", "/tn", entry["task_name"], "/f"])
        script_path = _SCRIPTS_DIR / f"{reminder_id}.ps1"
        script_path.unlink(missing_ok=True)
        del reminders[reminder_id]
        _save(reminders)
        return ToolResult(
            tool_name="reminder",
            content=f"Cancelled reminder: {entry['message']}",
            success=True,
        )


__all__ = ["ReminderTool"]
