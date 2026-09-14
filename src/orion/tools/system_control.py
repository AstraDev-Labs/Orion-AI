"""System control tool — volume, brightness, power, and WiFi control.

Windows-only for now (matches this deployment). Uses native OS commands
rather than extra pip dependencies, so it works with no extra install step.
"""

from __future__ import annotations

import ctypes
import platform
import subprocess
from typing import Any

from orion.core.registry import ToolRegistry
from orion.core.types import ToolResult
from orion.tools._stubs import BaseTool, ToolSpec

# shutdown/restart are intentionally NOT exposed here. This app has no real
# human-in-the-loop confirmation mechanism wired up for the live chat agent
# (the only confirm_callback found in this codebase unconditionally returns
# True), so a `confirm` tool parameter is not a safety gate — the same model
# deciding to shut down the machine also gets to set confirm=true itself.
# A live incident confirmed this: the agent called shutdown with confirm=false,
# was "refused", then simply retried with confirm=true on its own and the
# machine actually powered off. Do not re-add destructive power actions here
# without a real confirmation flow (see orion.tools.approval_store.ApprovalStore
# for the queue-and-wait-for-real-approval pattern already used by the
# proactive agent) that a human explicitly approves through the UI.

# Windows virtual key codes for media keys.
_VK_VOLUME_MUTE = 0xAD
_VK_VOLUME_DOWN = 0xAE
_VK_VOLUME_UP = 0xAF


def _press_media_key(vk: int, times: int = 1) -> None:
    for _ in range(times):
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        ctypes.windll.user32.keybd_event(vk, 0, 2, 0)  # KEYEVENTF_KEYUP


def _set_volume(percent: int) -> tuple[bool, str]:
    """Set the exact master volume level via the Windows Core Audio API.

    Every tool call runs in a freshly created worker thread (see
    ToolExecutor.execute()'s per-call ThreadPoolExecutor), and COM requires
    each thread to initialize it before use — hence the explicit
    CoInitialize/CoUninitialize pair rather than relying on pycaw to have
    done it already, which only holds by accident on some threads.
    """
    import comtypes

    percent = max(0, min(100, percent))
    initialized = False
    try:
        comtypes.CoInitialize()
        initialized = True
    except OSError:
        pass  # already initialized on this thread — fine, proceed

    try:
        from pycaw.pycaw import AudioUtilities

        speakers = AudioUtilities.GetSpeakers()
        endpoint = speakers.EndpointVolume
        # Mute is a separate flag from the volume level in this API — asking
        # to set a specific volume implies wanting audible sound, so clear
        # mute too rather than silently leaving it engaged.
        was_muted = bool(endpoint.GetMute())
        endpoint.SetMasterVolumeLevelScalar(percent / 100.0, None)
        if was_muted:
            endpoint.SetMute(0, None)
        suffix = " (was muted — unmuted too)" if was_muted else ""
        return True, f"Volume set to {percent}%.{suffix}"
    except Exception as exc:
        return False, f"Could not set volume: {exc}"
    finally:
        if initialized:
            comtypes.CoUninitialize()


def _get_volume() -> tuple[bool, str]:
    """Read the current master volume and mute state."""
    import comtypes

    initialized = False
    try:
        comtypes.CoInitialize()
        initialized = True
    except OSError:
        pass
    try:
        from pycaw.pycaw import AudioUtilities

        endpoint = AudioUtilities.GetSpeakers().EndpointVolume
        level = round(endpoint.GetMasterVolumeLevelScalar() * 100)
        muted = bool(endpoint.GetMute())
        return True, f"Volume is {level}%{' (muted)' if muted else ''}."
    except Exception as exc:
        return False, f"Could not read volume: {exc}"
    finally:
        if initialized:
            comtypes.CoUninitialize()


def _run(cmd: list[str]) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0,
        )
        ok = proc.returncode == 0
        return ok, (proc.stdout or proc.stderr or "").strip()
    except Exception as exc:
        return False, str(exc)


def _set_brightness(level: int) -> tuple[bool, str]:
    level = max(0, min(100, level))
    ps_cmd = (
        "(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods)"
        f".WmiSetBrightness(1,{level})"
    )
    ok, out = _run(["powershell", "-NoProfile", "-Command", ps_cmd])
    if ok:
        return True, f"Brightness set to {level}%."
    return False, f"Could not set brightness (unsupported display?): {out}"


def _get_brightness() -> tuple[bool, str]:
    ok, out = _run([
        "powershell", "-NoProfile", "-Command",
        "(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness).CurrentBrightness",
    ])
    level = out.strip().splitlines()[0].strip() if ok and out.strip() else ""
    if level.isdigit():
        return True, f"Brightness is {level}%."
    return False, "Could not read brightness (external monitors usually don't expose it)."


def _sleep() -> tuple[bool, str]:
    """Sleep (not hibernate).

    ``rundll32 powrprof.dll,SetSuspendState 0,1,0`` does not pass those
    arguments as the function's parameters, so on machines with hibernation
    enabled it hibernated instead. Calling the API directly passes them.
    """
    try:
        ok = ctypes.windll.powrprof.SetSuspendState(False, True, False)
    except Exception as exc:
        return False, f"Could not put the computer to sleep: {exc}"
    return (True, "Putting the computer to sleep.") if ok else (False, "Windows refused the sleep request.")


def _wifi_interface_name() -> str:
    """The wireless adapter's real name (it is not always "Wi-Fi")."""
    ok, out = _run(["netsh", "wlan", "show", "interfaces"])
    if ok:
        for line in out.splitlines():
            key, _, val = line.partition(":")
            if key.strip().lower() == "name" and val.strip():
                return val.strip()
    return "Wi-Fi"


def _get_wifi_status() -> tuple[bool, str]:
    ok, out = _run(["netsh", "wlan", "show", "interfaces"])
    if not ok:
        return False, out
    for line in out.splitlines():
        if "State" in line and ":" in line:
            return True, line.split(":", 1)[1].strip()
    return True, "unknown"


def _set_wifi(enabled: bool) -> tuple[bool, str]:
    name = _wifi_interface_name()
    state = "enabled" if enabled else "disabled"
    ok, out = _run(["netsh", "interface", "set", "interface", name, state])
    if ok:
        return True, f"Wi-Fi {state}."
    # Turning the adapter on/off needs administrator rights. Without them,
    # disconnecting from / reconnecting to the network still works.
    if enabled:
        ok2, out2 = _run(["netsh", "wlan", "connect", f"interface={name}", f"name={_last_wifi_profile(name)}"])
        if ok2:
            return True, "Reconnected to Wi-Fi."
        return False, f"Could not turn Wi-Fi on (needs administrator rights): {out or out2}"
    ok2, out2 = _run(["netsh", "wlan", "disconnect", f"interface={name}"])
    if ok2:
        return True, "Disconnected from Wi-Fi (turning the adapter fully off needs administrator rights)."
    return False, f"Could not turn Wi-Fi off: {out or out2}"


def _last_wifi_profile(interface: str) -> str:
    ok, out = _run(["netsh", "wlan", "show", "profiles", f"interface={interface}"])
    if ok:
        for line in out.splitlines():
            if ":" in line and "profile" in line.lower():
                name = line.split(":", 1)[1].strip()
                if name:
                    return name
    return ""


@ToolRegistry.register("system_control")
class SystemControlTool(BaseTool):
    """Control volume, brightness, power state, and WiFi on the user's machine."""

    tool_id = "system_control"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="system_control",
            description=(
                "Control the computer: volume up/down/mute/set-exact, screen brightness, "
                "lock screen, sleep, or WiFi on/off. Does NOT support shutdown or "
                "restart — those require a human to act directly, not an AI agent."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": (
                            "volume_up | volume_down | volume_mute | volume_set | volume_get | "
                            "brightness_set | brightness_get | lock | sleep | wifi_on | wifi_off | wifi_status"
                        ),
                    },
                    "value": {
                        "type": "integer",
                        "description": "Brightness/volume percent (0-100) for brightness_set/volume_set, or step count for volume_up/volume_down.",
                    },
                },
                "required": ["action"],
            },
            category="system",
            required_capabilities=["system:admin"],
            timeout_seconds=20.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        if platform.system() != "Windows":
            return ToolResult(
                tool_name="system_control",
                content="system_control currently only supports Windows.",
                success=False,
            )

        action = (params.get("action") or "").strip().lower()
        value = params.get("value")

        if action in ("shutdown", "restart"):
            return ToolResult(
                tool_name="system_control",
                content=(
                    f"I can't {action} the computer myself — there's no safe way for an "
                    "AI agent to confirm this with you in the moment. Please do it "
                    "directly from the Start menu or Alt+F4 on the desktop."
                ),
                success=False,
            )

        try:
            if action == "volume_up":
                _press_media_key(_VK_VOLUME_UP, times=int(value) if value else 2)
                return ToolResult(tool_name="system_control", content="Volume increased.", success=True)

            if action == "volume_down":
                _press_media_key(_VK_VOLUME_DOWN, times=int(value) if value else 2)
                return ToolResult(tool_name="system_control", content="Volume decreased.", success=True)

            if action == "volume_mute":
                _press_media_key(_VK_VOLUME_MUTE)
                return ToolResult(tool_name="system_control", content="Volume muted/unmuted.", success=True)

            if action == "volume_set":
                if value is None:
                    return ToolResult(
                        tool_name="system_control",
                        content="volume_set requires a 'value' (0-100).",
                        success=False,
                    )
                ok, msg = _set_volume(int(value))
                return ToolResult(tool_name="system_control", content=msg, success=ok)

            if action == "volume_get":
                ok, msg = _get_volume()
                return ToolResult(tool_name="system_control", content=msg, success=ok)

            if action == "brightness_get":
                ok, msg = _get_brightness()
                return ToolResult(tool_name="system_control", content=msg, success=ok)

            if action == "brightness_set":
                if value is None:
                    return ToolResult(
                        tool_name="system_control",
                        content="brightness_set requires a 'value' (0-100).",
                        success=False,
                    )
                ok, msg = _set_brightness(int(value))
                return ToolResult(tool_name="system_control", content=msg, success=ok)

            if action == "lock":
                subprocess.Popen(
                    ["rundll32.exe", "user32.dll,LockWorkStation"],
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                return ToolResult(tool_name="system_control", content="Screen locked.", success=True)

            if action == "sleep":
                ok, msg = _sleep()
                return ToolResult(tool_name="system_control", content=msg, success=ok)

            if action == "wifi_on":
                ok, msg = _set_wifi(True)
                return ToolResult(tool_name="system_control", content=msg, success=ok)

            if action == "wifi_off":
                ok, msg = _set_wifi(False)
                return ToolResult(tool_name="system_control", content=msg, success=ok)

            if action == "wifi_status":
                ok, msg = _get_wifi_status()
                return ToolResult(tool_name="system_control", content=f"WiFi state: {msg}", success=ok)

            return ToolResult(
                tool_name="system_control",
                content=f"Unknown action '{action}'.",
                success=False,
            )
        except Exception as exc:
            return ToolResult(
                tool_name="system_control",
                content=f"system_control error: {exc}",
                success=False,
            )


__all__ = ["SystemControlTool"]
