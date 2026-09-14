"""Computer control tool — mouse and keyboard control of native desktop apps.

Fills the gap between ``open_app`` (which can launch an app but not use it) and
the browser tools (which can drive web apps fully): this lets the agent click,
type, and scroll in any Windows application.

Windows-only and dependency-free (pure ctypes), matching system_control.py and
desktop_control.py in this package. That matters here specifically because
``vision_capture`` -- the tool for *seeing* the screen -- is currently broken at
runtime for want of ``mss``/``Pillow`` in the venv, and a control tool that
failed the same way would be worse than useless.

SAFETY
------
A tool that can click anywhere can click "Send", "Delete", or "Confirm
purchase". That cuts against this codebase's rule that consequential actions are
queued via ``queue_action`` and wait for the user's own literal approval (see
orion.tools.proactive_tools), so this tool refuses rather than performs anything
that looks irreversible:

* input is blocked entirely while a sensitive window (banking, payments,
  password managers) is in the foreground;
* before clicking, the caption of the control under the cursor is read, and the
  click is refused if it reads as destructive or transactional.

Both checks are best-effort, not a security boundary -- Win32 control text is
simply unavailable in many modern (Electron/UWP) apps, where this is clicking
blind. They exist to catch plausible mistakes by a small local model, not a
determined adversary.
"""

from __future__ import annotations

import ctypes
import platform
import re
import time
from ctypes import wintypes
from typing import Any, Optional

from orion.core.registry import ToolRegistry
from orion.core.types import ToolResult
from orion.tools._stubs import BaseTool, ToolSpec

# Foreground windows in which no input will be synthesised at all.
_SENSITIVE_WINDOW_RE = re.compile(
    r"\b(bank|banking|paypal|stripe|checkout|payment|billing|wallet|"
    r"bitwarden|1password|lastpass|keepass|dashlane|credential|"
    r"sign in|log in|login|password)\b",
    re.IGNORECASE,
)

# Control captions that indicate an irreversible or outward-facing action.
_DESTRUCTIVE_CONTROL_RE = re.compile(
    r"\b(send|delete|remove|erase|discard|buy|purchase|pay|order|checkout|"
    r"transfer|withdraw|confirm|submit|publish|post|share|uninstall|"
    r"format|wipe|reset|shut ?down|restart)\b",
    re.IGNORECASE,
)

_MOUSEEVENTF_LEFTDOWN = 0x0002
_MOUSEEVENTF_LEFTUP = 0x0004
_MOUSEEVENTF_RIGHTDOWN = 0x0008
_MOUSEEVENTF_RIGHTUP = 0x0010
_MOUSEEVENTF_WHEEL = 0x0800

_VK_MAP = {
    "enter": 0x0D, "return": 0x0D, "tab": 0x09, "esc": 0x1B, "escape": 0x1B,
    "space": 0x20, "backspace": 0x08, "delete": 0x2E, "up": 0x26, "down": 0x28,
    "left": 0x25, "right": 0x27, "home": 0x24, "end": 0x23,
    "pageup": 0x21, "pagedown": 0x22,
    "ctrl": 0x11, "control": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B,
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74, "f6": 0x75,
    "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
}


def _ensure_dpi_aware() -> None:
    """Report true pixel coordinates on scaled displays.

    Without this, a click at (1000, 500) lands somewhere else entirely on any
    display scaled above 100%, which is the default on most laptops.
    """
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _screen_size() -> tuple[int, int]:
    user32 = ctypes.windll.user32
    return int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1))


def _foreground_window_title() -> str:
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return ""
    length = user32.GetWindowTextLengthW(hwnd)
    if not length:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def _control_text_at(x: int, y: int) -> str:
    """Best-effort caption of the control at screen point (x, y).

    Returns "" for apps that don't expose Win32 control text (Electron, UWP,
    most browsers), so callers must treat an empty result as "unknown" -- never
    as "safe".
    """
    try:
        user32 = ctypes.windll.user32
        point = wintypes.POINT(x, y)
        hwnd = user32.WindowFromPoint(point)
        if not hwnd:
            return ""
        length = user32.GetWindowTextLengthW(hwnd)
        if not length:
            return ""
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value
    except Exception:
        return ""


def _guard_click(x: int, y: int) -> Optional[str]:
    """Return a refusal reason if clicking (x, y) looks unsafe, else None."""
    title = _foreground_window_title()
    if title and _SENSITIVE_WINDOW_RE.search(title):
        return (
            f"Refused: the active window ('{title}') looks like a banking, "
            "payment, or credential screen. Ask the user to do this themselves."
        )

    caption = _control_text_at(x, y)
    if caption and _DESTRUCTIVE_CONTROL_RE.search(caption):
        return (
            f"Refused: the control at ({x}, {y}) is labelled '{caption}', which "
            "looks irreversible or outward-facing. Do not click it. If the user "
            "asked for this, queue it with queue_action so they can approve it "
            "explicitly."
        )
    return None


def _glide_to(x: int, y: int, duration: float = 0.35) -> None:
    """Move the pointer to (x, y) as a visible sweep rather than a jump.

    ``SetCursorPos`` teleports, so an automated click looks like the UI
    reacting to nothing -- the user cannot see what the assistant is doing or
    interrupt it. Interpolating the path makes the action legible, and the
    ease-in-out curve reads as deliberate rather than mechanical.
    """
    user32 = ctypes.windll.user32
    point = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(point))
    start_x, start_y = point.x, point.y
    dx, dy = x - start_x, y - start_y

    steps = max(1, int(duration / 0.012))
    if abs(dx) + abs(dy) < 4:
        user32.SetCursorPos(int(x), int(y))
        return

    for i in range(1, steps + 1):
        t = i / steps
        # Smoothstep: accelerate away, decelerate in.
        eased = t * t * (3 - 2 * t)
        user32.SetCursorPos(int(start_x + dx * eased), int(start_y + dy * eased))
        time.sleep(duration / steps)


def _click(x: int, y: int, button: str = "left", double: bool = False,
           smooth: bool = True) -> None:
    user32 = ctypes.windll.user32
    if smooth:
        _glide_to(int(x), int(y))
    else:
        user32.SetCursorPos(int(x), int(y))
    time.sleep(0.05)
    if button == "right":
        down, up = _MOUSEEVENTF_RIGHTDOWN, _MOUSEEVENTF_RIGHTUP
    else:
        down, up = _MOUSEEVENTF_LEFTDOWN, _MOUSEEVENTF_LEFTUP
    for _ in range(2 if double else 1):
        user32.mouse_event(down, 0, 0, 0, 0)
        user32.mouse_event(up, 0, 0, 0, 0)
        if double:
            time.sleep(0.05)


def _scroll(amount: int) -> None:
    """Scroll by *amount* notches; positive scrolls up, negative down."""
    ctypes.windll.user32.mouse_event(_MOUSEEVENTF_WHEEL, 0, 0, int(amount) * 120, 0)


def _type_text(text: str) -> None:
    """Type *text* as Unicode, so it works regardless of keyboard layout."""
    user32 = ctypes.windll.user32
    PUL = ctypes.POINTER(ctypes.c_ulong)

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
            ("dwExtraInfo", PUL),
        ]

    class _UNION(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("union", _UNION)]

    INPUT_KEYBOARD = 1
    KEYEVENTF_UNICODE = 0x0004
    KEYEVENTF_KEYUP = 0x0002

    for ch in text:
        code = ord(ch)
        down = INPUT(type=INPUT_KEYBOARD, union=_UNION(
            ki=KEYBDINPUT(0, code, KEYEVENTF_UNICODE, 0, None)))
        up = INPUT(type=INPUT_KEYBOARD, union=_UNION(
            ki=KEYBDINPUT(0, code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, None)))
        user32.SendInput(1, ctypes.byref(down), ctypes.sizeof(INPUT))
        user32.SendInput(1, ctypes.byref(up), ctypes.sizeof(INPUT))
        time.sleep(0.005)


def _press_combo(keys: str) -> str:
    """Press a key or combo like 'ctrl+s'. Returns an error string, or ""."""
    user32 = ctypes.windll.user32
    parts = [k.strip().lower() for k in keys.split("+") if k.strip()]
    codes = []
    for part in parts:
        if part in _VK_MAP:
            codes.append(_VK_MAP[part])
        elif len(part) == 1:
            codes.append(ord(part.upper()))
        else:
            return f"Unknown key '{part}'."

    for code in codes:
        user32.keybd_event(code, 0, 0, 0)
    for code in reversed(codes):
        user32.keybd_event(code, 0, 2, 0)  # KEYEVENTF_KEYUP
    return ""


@ToolRegistry.register("computer_control")
class ComputerControlTool(BaseTool):
    """Click, type, and scroll in native desktop applications."""

    tool_id = "computer_control"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="computer_control",
            description=(
                "Control the mouse and keyboard to operate native desktop apps "
                "(Excel, Word, Notepad, settings dialogs — anything not in a browser). "
                "Actions: click, double_click, right_click, move, type, key, scroll, "
                "screen_info.\n"
                "WORKFLOW: call vision_capture first to SEE the screen and work out "
                "where things are, then click/type using those coordinates. Coordinates "
                "are absolute screen pixels with (0,0) at the top-left; call screen_info "
                "for the screen dimensions.\n"
                "FOR WEB PAGES USE THE BROWSER TOOLS INSTEAD (browser_click, "
                "browser_type): they target elements directly and are far more reliable "
                "than clicking pixels.\n"
                "This tool refuses to click buttons that look irreversible (Send, "
                "Delete, Buy, Confirm) or to act on banking/password windows. If the "
                "user genuinely wants such an action, use queue_action so they can "
                "approve it themselves."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": (
                            "click | double_click | right_click | move | type | key | "
                            "scroll | screen_info"
                        ),
                    },
                    "x": {"type": "integer", "description": "Screen X for click/move."},
                    "y": {"type": "integer", "description": "Screen Y for click/move."},
                    "text": {"type": "string", "description": "Text to type (action='type')."},
                    "keys": {
                        "type": "string",
                        "description": "Key or combo for action='key', e.g. 'enter', 'ctrl+s'.",
                    },
                    "amount": {
                        "type": "integer",
                        "description": "Scroll notches; positive scrolls up, negative down.",
                    },
                    "smooth": {
                        "type": "boolean",
                        "description": (
                            "Glide the pointer to the target instead of teleporting "
                            "(default true). Keeps the action visible so the user can "
                            "follow along. Set false only when speed matters more."
                        ),
                    },
                    "expect_window": {
                        "type": "string",
                        "description": (
                            "Substring the active window's title must contain for this "
                            "action to run, e.g. 'Untitled - Notepad'. STRONGLY "
                            "RECOMMENDED for type/key: without it, keystrokes go to "
                            "whatever happens to be focused, which may not be the app "
                            "you opened. Be specific — 'Notepad' also matches an "
                            "already-open document you did not intend to edit."
                        ),
                    },
                },
                "required": ["action"],
            },
            category="system",
            required_capabilities=["system:admin"],
            timeout_seconds=30.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        if platform.system() != "Windows":
            return ToolResult(
                tool_name="computer_control",
                content="computer_control currently only supports Windows.",
                success=False,
            )

        _ensure_dpi_aware()
        action = (params.get("action") or "").strip().lower()
        x, y = params.get("x"), params.get("y")
        expect_window = (params.get("expect_window") or "").strip()

        # Synthetic input always goes to whatever is focused *now*, which is not
        # necessarily the app the caller just launched: opening "notepad" may
        # surface an already-running Notepad holding an unrelated document. That
        # happened on this tool's first live run and typed into a file the user
        # was editing. When the caller states which window it expects, verify it
        # before sending anything.
        if expect_window:
            actual = _foreground_window_title()
            if expect_window.lower() not in actual.lower():
                return ToolResult(
                    tool_name="computer_control",
                    content=(
                        f"Refused: expected a window matching '{expect_window}' but the "
                        f"active window is '{actual}'. Nothing was sent. Focus the right "
                        "window first, then retry."
                    ),
                    success=False,
                )

        def fail(msg: str) -> ToolResult:
            return ToolResult(tool_name="computer_control", content=msg, success=False)

        def ok(msg: str) -> ToolResult:
            window = _foreground_window_title()
            suffix = f"\nActive window: {window}" if window else ""
            return ToolResult(
                tool_name="computer_control", content=msg + suffix, success=True
            )

        try:
            if action == "screen_info":
                w, h = _screen_size()
                return ok(f"Screen is {w}x{h} pixels. Origin (0,0) is top-left.")

            if action in ("click", "double_click", "right_click", "move"):
                if x is None or y is None:
                    return fail(f"'x' and 'y' are required for action '{action}'.")
                w, h = _screen_size()
                if not (0 <= int(x) < w and 0 <= int(y) < h):
                    return fail(
                        f"({x}, {y}) is outside the {w}x{h} screen. "
                        "Call screen_info, or vision_capture to see the layout."
                    )

                smooth = params.get("smooth")
                smooth = True if smooth is None else bool(smooth)

                if action == "move":
                    if smooth:
                        _glide_to(int(x), int(y))
                    else:
                        ctypes.windll.user32.SetCursorPos(int(x), int(y))
                    return ok(f"Moved the pointer to ({x}, {y}).")

                refusal = _guard_click(int(x), int(y))
                if refusal:
                    return fail(refusal)

                _click(
                    int(x), int(y),
                    button="right" if action == "right_click" else "left",
                    double=(action == "double_click"),
                    smooth=smooth,
                )
                label = _control_text_at(int(x), int(y))
                detail = f" on '{label}'" if label else ""
                return ok(f"{action.replace('_', ' ').title()} at ({x}, {y}){detail}.")

            if action == "type":
                text = params.get("text") or ""
                if not text:
                    return fail("'text' is required for action='type'.")
                _type_text(text)
                return ok(f"Typed {len(text)} characters into the active window.")

            if action == "key":
                keys = params.get("keys") or ""
                if not keys:
                    return fail("'keys' is required for action='key'.")
                err = _press_combo(keys)
                if err:
                    return fail(err)
                return ok(f"Pressed {keys}.")

            if action == "scroll":
                amount = params.get("amount")
                if amount is None:
                    return fail("'amount' is required for action='scroll'.")
                _scroll(int(amount))
                direction = "up" if int(amount) > 0 else "down"
                return ok(f"Scrolled {direction} by {abs(int(amount))} notches.")

            return fail(
                f"Unknown action '{action}'. Use click, double_click, right_click, "
                "move, type, key, scroll, or screen_info."
            )
        except Exception as exc:
            return fail(f"computer_control failed: {exc}")


__all__ = ["ComputerControlTool"]
