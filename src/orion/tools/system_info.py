"""System info tool — real-time answers about the machine and the moment.

Covers the everyday questions a person actually asks an assistant: what time
is it, how much battery is left, is the disk filling up, what wifi am I on.

None of this is knowable to the model on its own. A language model has no
clock, no battery gauge and no filesystem: asked for the time it will either
refuse or invent one, because its only sense of "now" is whatever text is in
its context. Every value here is read at call time.

Windows-first and dependency-free (ctypes + stdlib), matching system_control.py
and desktop_control.py in this package. That is deliberate: ``vision_capture``
shipped with four unlisted imports, registered fine, and then failed on every
single call. A tool answering "what time is it" must never fail that way.
"""

from __future__ import annotations

import ctypes
import os
import platform
import shutil
import socket
import subprocess
import time
from ctypes import wintypes
from datetime import datetime, timezone
from typing import Any

from orion.core.registry import ToolRegistry
from orion.core.types import ToolResult
from orion.tools._stubs import BaseTool, ToolSpec

_IS_WINDOWS = platform.system() == "Windows"


# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------


def _time_info() -> str:
    now = datetime.now().astimezone()
    utc = datetime.now(timezone.utc)
    return (
        f"Local time: {now.strftime('%I:%M %p').lstrip('0')} "
        f"({now.strftime('%H:%M:%S')})\n"
        f"Date: {now.strftime('%A, %d %B %Y')}\n"
        f"Timezone: {now.tzname()} (UTC{now.strftime('%z')[:3]}:{now.strftime('%z')[3:]})\n"
        f"UTC: {utc.strftime('%Y-%m-%d %H:%M:%S')}"
    )


# ---------------------------------------------------------------------------
# Power
# ---------------------------------------------------------------------------


class _SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [
        ("ACLineStatus", wintypes.BYTE),
        ("BatteryFlag", wintypes.BYTE),
        ("BatteryLifePercent", wintypes.BYTE),
        ("SystemStatusFlag", wintypes.BYTE),
        ("BatteryLifeTime", wintypes.DWORD),
        ("BatteryFullLifeTime", wintypes.DWORD),
    ]


def _battery_info() -> str:
    if not _IS_WINDOWS:
        return "Battery info is only available on Windows."
    status = _SYSTEM_POWER_STATUS()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
        return "Could not read battery status."

    percent = status.BatteryLifePercent
    if percent == 255:
        return "No battery detected (desktop machine or driver reports none)."

    plugged = status.ACLineStatus == 1
    lines = [f"Battery: {percent}%", f"Power: {'plugged in' if plugged else 'on battery'}"]

    # 0xFFFFFFFF means "unknown", which is normal while charging.
    secs = status.BatteryLifeTime
    if not plugged and secs not in (0xFFFFFFFF, 0):
        lines.append(f"Estimated remaining: {secs // 3600}h {(secs % 3600) // 60}m")
    if percent <= 20 and not plugged:
        lines.append("Warning: battery is low.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Memory / disk / uptime / cpu
# ---------------------------------------------------------------------------


class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", wintypes.DWORD),
        ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _gb(n: int) -> str:
    return f"{n / (1024 ** 3):.1f} GB"


def _memory_info() -> str:
    if not _IS_WINDOWS:
        return "Memory info is only available on Windows."
    stat = _MEMORYSTATUSEX()
    stat.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
        return "Could not read memory status."
    used = stat.ullTotalPhys - stat.ullAvailPhys
    return (
        f"RAM: {_gb(used)} used of {_gb(stat.ullTotalPhys)} "
        f"({stat.dwMemoryLoad}% in use)\n"
        f"Available: {_gb(stat.ullAvailPhys)}"
    )


def _disk_info() -> str:
    lines = []
    drive = os.path.splitdrive(os.path.expanduser("~"))[0] or "C:"
    for path in [drive + "\\"] if _IS_WINDOWS else ["/"]:
        try:
            total, used, free = shutil.disk_usage(path)
        except OSError:
            continue
        pct = (used / total * 100) if total else 0
        lines.append(
            f"{path}  {_gb(used)} used of {_gb(total)} ({pct:.0f}%), {_gb(free)} free"
        )
        if free < 5 * 1024 ** 3:
            lines.append("Warning: less than 5 GB free.")
    return "\n".join(lines) if lines else "Could not read disk usage."


def _uptime_info() -> str:
    if not _IS_WINDOWS:
        return "Uptime is only available on Windows."
    ms = ctypes.windll.kernel32.GetTickCount64()
    secs = int(ms // 1000)
    days, rem = divmod(secs, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    parts = ([f"{days}d"] if days else []) + ([f"{hours}h"] if hours else []) + [f"{minutes}m"]
    booted = datetime.now().astimezone().timestamp() - secs
    return (
        f"Uptime: {' '.join(parts)}\n"
        f"Booted: {datetime.fromtimestamp(booted).strftime('%a %d %b, %I:%M %p').replace(' 0', ' ')}"
    )


class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]


def _ft(ft: _FILETIME) -> int:
    return (ft.dwHighDateTime << 32) | ft.dwLowDateTime


def _cpu_info() -> str:
    """CPU load, sampled over a short interval via GetSystemTimes."""
    if not _IS_WINDOWS:
        return "CPU info is only available on Windows."

    def sample():
        idle, kern, user = _FILETIME(), _FILETIME(), _FILETIME()
        ok = ctypes.windll.kernel32.GetSystemTimes(
            ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user)
        )
        return (_ft(idle), _ft(kern), _ft(user)) if ok else None

    first = sample()
    if first is None:
        return "Could not read CPU times."
    time.sleep(0.35)
    second = sample()
    if second is None:
        return "Could not read CPU times."

    idle_d = second[0] - first[0]
    total_d = (second[1] - first[1]) + (second[2] - first[2])
    if total_d <= 0:
        return "CPU load: unavailable (no measurable delta)."
    usage = max(0.0, min(100.0, (1 - idle_d / total_d) * 100))
    return f"CPU load: {usage:.0f}%\nLogical cores: {os.cpu_count()}"


# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------


def _network_info() -> str:
    lines = []
    try:
        hostname = socket.gethostname()
        lines.append(f"Hostname: {hostname}")
        # Connecting a UDP socket sends nothing but reveals the interface that
        # would be used for outbound traffic -- the LAN IP the user cares about.
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.settimeout(0.5)
            sock.connect(("8.8.8.8", 80))
            lines.append(f"Local IP: {sock.getsockname()[0]}")
            lines.append("Internet: connected")
        except OSError:
            lines.append("Internet: no route (likely offline)")
        finally:
            sock.close()
    except Exception:
        lines.append("Could not determine network address.")

    if _IS_WINDOWS:
        try:
            out = subprocess.run(
                ["netsh", "wlan", "show", "interfaces"],
                capture_output=True, text=True, timeout=8,
                encoding="utf-8", errors="replace",
            ).stdout
            ssid = signal = ""
            for line in out.splitlines():
                stripped = line.strip()
                # "BSSID" also starts with "SSID" once stripped of its prefix,
                # so match on the exact key before the colon.
                key = stripped.split(":", 1)[0].strip().lower()
                if key == "ssid":
                    ssid = stripped.split(":", 1)[1].strip()
                elif key == "signal":
                    signal = stripped.split(":", 1)[1].strip()
            if ssid:
                lines.append(f"Wi-Fi: {ssid}" + (f" (signal {signal})" if signal else ""))
        except Exception:
            pass
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Clipboard
# ---------------------------------------------------------------------------


def _clipboard_info() -> str:
    if not _IS_WINDOWS:
        return "Clipboard reading is only available on Windows."
    CF_UNICODETEXT = 13
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    if not user32.OpenClipboard(0):
        return "Could not open the clipboard (another app may be holding it)."
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return "Clipboard is empty, or holds something that isn't text."
        kernel32.GlobalLock.restype = ctypes.c_void_p
        ptr = kernel32.GlobalLock(ctypes.c_void_p(handle))
        if not ptr:
            return "Could not read the clipboard contents."
        try:
            text = ctypes.c_wchar_p(ptr).value or ""
        finally:
            kernel32.GlobalUnlock(ctypes.c_void_p(handle))
    finally:
        user32.CloseClipboard()

    if len(text) > 800:
        return f"Clipboard ({len(text)} chars, showing first 800):\n{text[:800]}…"
    return f"Clipboard:\n{text}"


_SECTIONS = {
    "time": _time_info,
    "battery": _battery_info,
    "memory": _memory_info,
    "disk": _disk_info,
    "cpu": _cpu_info,
    "uptime": _uptime_info,
    "network": _network_info,
    "clipboard": _clipboard_info,
}

# Everything cheap enough to gather for a general "how's my machine" question.
# Clipboard is excluded: its contents are private and often irrelevant, so it
# is only read when explicitly asked for.
_SUMMARY_ORDER = ["time", "battery", "cpu", "memory", "disk", "uptime", "network"]


@ToolRegistry.register("system_info")
class SystemInfoTool(BaseTool):
    """Answer real-time questions about the machine: time, battery, resources."""

    tool_id = "system_info"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="system_info",
            description=(
                "Read live information about the computer and the current moment. "
                "USE THIS WHENEVER the user asks the time, the date, what day it is, "
                "battery level, whether they're charging, CPU or memory usage, free "
                "disk space, how long the machine has been on, network/Wi-Fi status, "
                "or what's on the clipboard.\n"
                "You do NOT know the current time, date, or any machine state on your "
                "own — you have no clock and no sensors. Never guess or state a time "
                "from memory; call this tool and report exactly what it returns.\n"
                "Options for 'what': time, battery, cpu, memory, disk, uptime, network, "
                "clipboard, or all (a summary of everything except clipboard)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "what": {
                        "type": "string",
                        "description": (
                            "time | battery | cpu | memory | disk | uptime | network | "
                            "clipboard | all  (defaults to 'all')"
                        ),
                    },
                },
                "required": [],
            },
            category="system",
            timeout_seconds=20.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        what = (params.get("what") or "all").strip().lower()

        try:
            if what in ("all", "", "summary"):
                blocks = []
                for key in _SUMMARY_ORDER:
                    try:
                        blocks.append(_SECTIONS[key]())
                    except Exception as exc:  # one bad reading must not sink the rest
                        blocks.append(f"({key} unavailable: {exc})")
                return ToolResult(
                    tool_name="system_info", content="\n\n".join(blocks), success=True
                )

            fn = _SECTIONS.get(what)
            if fn is None:
                return ToolResult(
                    tool_name="system_info",
                    content=(
                        f"Unknown option '{what}'. Use one of: "
                        + ", ".join(_SECTIONS) + ", all."
                    ),
                    success=False,
                )
            return ToolResult(tool_name="system_info", content=fn(), success=True)
        except Exception as exc:
            return ToolResult(
                tool_name="system_info",
                content=f"system_info failed: {exc}",
                success=False,
            )


__all__ = ["SystemInfoTool"]
