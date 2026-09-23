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
import xml.etree.ElementTree as ET
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


def _verify_task(task_name: str, when: str) -> tuple[bool, str]:
    ok, xml = _run(["schtasks", "/query", "/tn", task_name, "/xml"])
    if not ok:
        return False, f"Task could not be read: {xml}"
    try:
        root = ET.fromstring(xml)
        enabled = root.findtext(".//{*}Settings/{*}Enabled", "true").lower() != "false"
        triggers = root.findall(".//{*}TimeTrigger")
        matches = any(
            t.findtext("{*}StartBoundary", "")[:19] == when[:19]
            and t.findtext("{*}Enabled", "true").lower() != "false"
            for t in triggers
        )
        if not enabled or not matches:
            return False, "The task is disabled or its trigger does not match the requested time."
        return True, "Enabled task and matching scheduled time read back from Windows Task Scheduler."
    except ET.ParseError:
        return False, "Windows returned an unreadable task definition."


@ToolRegistry.register("reminder")
class ReminderTool(BaseTool):
    """Create, list, and cancel scheduled reminders."""

    tool_id = "reminder"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="reminder",
            description=(
                "Set, list, or cancel a timed reminder. The reminder launches an "
                "Orion popup at the given date/time via the OS task scheduler. "
                "It needs a signed-in Windows session and is not guaranteed while "
                "the computer sleeps or is powered off. This creates an Orion popup reminder, "
                "NOT a Windows Clock alarm. It will not appear in Clock. List reads back the "
                "real scheduled tasks to verify them; never claim a Clock alarm was created."
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
        if when <= datetime.now():
            return ToolResult(tool_name="reminder", content="The requested time is in the past. No reminder was created.", success=False)
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
            "$ErrorActionPreference = 'Stop'; "
            "$action = New-ScheduledTaskAction -Execute 'powershell.exe' "
            f'-Argument \'-WindowStyle Hidden -ExecutionPolicy Bypass -File "{_escape_ps(str(script_path))}"\'; '
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

        verified, evidence = _verify_task(task_name, when.isoformat())

        return ToolResult(
            tool_name="reminder",
            content=(f"Orion popup reminder for {when.strftime('%Y-%m-%d %H:%M')}: {message}. "
                     f"{evidence} This is a Task Scheduler reminder, not a Windows Clock alarm. "
                     "It requires a running, signed-in Windows session to display the popup; delivery is not guaranteed while asleep or powered off."),
            success=verified,
            metadata={"reminder_id": reminder_id, "backend": "windows_task_scheduler", "verified": verified},
        )

    def _list(self) -> ToolResult:
        reminders = _load()
        if not reminders:
            return ToolResult(tool_name="reminder", content="No reminders set.", success=True)
        lines = ["Orion Task Scheduler reminders (not Windows Clock alarms):"]
        for rid, r in sorted(reminders.items(), key=lambda kv: kv[1]["when"]):
            verified, evidence = _verify_task(r["task_name"], r["when"])
            r["verified"] = verified
            lines.append(f"[{rid}] {r['when']} — {r['message']}. {evidence} A registered trigger is not proof that a popup was delivered.")
        all_verified = all(r.get("verified", False) for r in reminders.values())
        return ToolResult(
            tool_name="reminder",
            content="\n".join(lines),
            success=all_verified,
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
        ok, detail = _run(["schtasks", "/delete", "/tn", entry["task_name"], "/f"])
        if not ok:
            return ToolResult(tool_name="reminder", content=f"Could not cancel reminder: {detail}", success=False)
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
