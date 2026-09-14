"""Desktop control tool — wallpaper and window management.

Windows-only, implemented with pure ctypes (no extra pip dependencies),
matching the approach used in system_control.py.
"""

from __future__ import annotations

import ctypes
import platform
import shutil
import tempfile
from ctypes import wintypes
from datetime import datetime
from pathlib import Path
from typing import Any, List, Tuple

from orion.core.registry import ToolRegistry
from orion.core.types import ToolResult
from orion.tools._stubs import BaseTool, ToolSpec

_FILE_TYPE_MAP = {
    "Images": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".ico", ".heic"},
    "Documents": {".pdf", ".doc", ".docx", ".txt", ".xls", ".xlsx", ".ppt", ".pptx", ".csv"},
    "Videos": {".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm", ".m4v"},
    "Music": {".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma", ".m4a"},
    "Archives": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"},
    "Code": {".py", ".js", ".ts", ".html", ".css", ".json", ".xml", ".cpp", ".java", ".cs", ".go", ".rs"},
    "Executables": {".exe", ".msi", ".bat", ".cmd"},
}
_DESKTOP_SKIP_EXTENSIONS = {".lnk", ".url"}


_FOLDER_SHORTCUTS = {
    "desktop": "Desktop",
    "documents": "Documents",
    "downloads": "Downloads",
    "pictures": "Pictures",
    "music": "Music",
    "videos": "Videos",
}


def _resolve_folder(path_param: str) -> Path:
    """Resolve a folder shortcut ('documents', 'downloads', ...) or literal path.

    Defaults to Desktop only when nothing is given — previously list_files/
    stats/organize/clean were hardcoded to Desktop with no way to target any
    other folder, which silently answered questions about e.g. Documents
    with Desktop's stats instead.
    """
    key = (path_param or "desktop").strip().lower()
    if key in _FOLDER_SHORTCUTS:
        return Path.home() / _FOLDER_SHORTCUTS[key]
    return Path(path_param).expanduser()

_SPI_SETDESKWALLPAPER = 20
_SPIF_UPDATEINIFILE = 0x01
_SPIF_SENDCHANGE = 0x02

_SW_RESTORE = 9
_SW_MINIMIZE = 6
_SW_MAXIMIZE = 3
_WM_CLOSE = 0x0010
_VK_LWIN = 0x5B
_VK_D = 0x44
_KEYEVENTF_KEYUP = 0x0002


def _user32():
    return ctypes.windll.user32  # type: ignore[attr-defined]


def _list_top_windows() -> List[Tuple[int, str]]:
    """Return (hwnd, title) for visible, titled top-level windows."""
    user32 = _user32()
    results: List[Tuple[int, str]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value.strip()
        if title:
            results.append((hwnd, title))
        return True

    user32.EnumWindows(_callback, 0)
    return results


def _find_window(title_query: str) -> Tuple[int, str] | None:
    query = title_query.lower().strip()
    for hwnd, title in _list_top_windows():
        if query in title.lower():
            return hwnd, title
    return None


def _set_wallpaper(path: str) -> tuple[bool, str]:
    p = Path(path).expanduser()
    if not p.exists():
        return False, f"File not found: {p}"
    ok = _user32().SystemParametersInfoW(
        _SPI_SETDESKWALLPAPER, 0, str(p), _SPIF_UPDATEINIFILE | _SPIF_SENDCHANGE
    )
    if ok:
        return True, f"Wallpaper set to {p.name}."
    return False, "Failed to set wallpaper (SystemParametersInfoW rejected it)."


def _set_wallpaper_from_url(url: str) -> tuple[bool, str]:
    import urllib.request

    try:
        suffix = Path(url.split("?")[0]).suffix or ".jpg"
        tmp = Path(tempfile.mktemp(suffix=suffix))
        urllib.request.urlretrieve(url, str(tmp))  # noqa: S310 — user-provided URL, local desktop tool
        ok, msg = _set_wallpaper(str(tmp))
        try:
            tmp.unlink()
        except OSError:
            pass
        return ok, msg
    except Exception as exc:
        return False, f"Could not download wallpaper: {exc}"


def _get_current_wallpaper() -> tuple[bool, str]:
    try:
        import winreg

        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop")
        value, _ = winreg.QueryValueEx(key, "Wallpaper")
        winreg.CloseKey(key)
        return True, value or "(no wallpaper set)"
    except Exception as exc:
        return False, f"Could not read current wallpaper: {exc}"


_LIST_ITEM_CAP = 200  # avoid dumping huge folders (e.g. Documents) into one response


def _list_folder(folder: Path) -> str:
    if not folder.exists():
        return f"Folder not found: {folder}"
    items = []
    entries = sorted(folder.iterdir())
    for item in entries[:_LIST_ITEM_CAP]:
        if item.name.startswith("."):
            continue
        if item.is_dir():
            try:
                count = len(list(item.iterdir()))
            except PermissionError:
                count = "?"
            items.append(f"[folder] {item.name}/ ({count} items)")
        else:
            size = item.stat().st_size
            size_str = f"{size / 1024:.1f} KB" if size < 1024 * 1024 else f"{size / 1024 / 1024:.1f} MB"
            items.append(f"[file] {item.name} ({size_str})")
    if not items:
        return f"{folder} is empty."
    header = f"{folder} ({len(entries)} items"
    header += f", showing first {_LIST_ITEM_CAP})" if len(entries) > _LIST_ITEM_CAP else ")"
    return header + ":\n" + "\n".join(items)


def _folder_stats(folder: Path) -> str:
    if not folder.exists():
        return f"Folder not found: {folder}"
    files = [i for i in folder.iterdir() if i.is_file()]
    folders = [i for i in folder.iterdir() if i.is_dir()]
    total_size = sum(f.stat().st_size for f in files)
    size_str = f"{total_size / 1024:.1f} KB" if total_size < 1024 * 1024 else f"{total_size / 1024 / 1024:.1f} MB"
    return (
        f"Top-level only (not recursive): {len(files)} files, {len(folders)} folders, "
        f"{size_str} across those top-level files. Path: {folder}"
    )


def _organize_folder(folder: Path, mode: str) -> str:
    if not folder.exists():
        return f"Folder not found: {folder}"
    moved, skipped = [], []

    for item in folder.iterdir():
        if item.is_dir() or item.name.startswith("."):
            continue
        if item.suffix.lower() in _DESKTOP_SKIP_EXTENSIONS:
            continue

        if mode == "by_date":
            folder_name = datetime.fromtimestamp(item.stat().st_mtime).strftime("%Y-%m")
        else:
            ext = item.suffix.lower()
            folder_name = "Others"
            for fname, exts in _FILE_TYPE_MAP.items():
                if ext in exts:
                    folder_name = fname
                    break

        target_dir = folder / folder_name
        target_dir.mkdir(exist_ok=True)
        new_path = target_dir / item.name
        if new_path.exists():
            skipped.append(item.name)
            continue
        shutil.move(str(item), str(new_path))
        moved.append(f"{item.name} -> {folder_name}/")

    result = f"{folder} organized ({mode}): {len(moved)} files moved."
    if moved:
        result += "\n" + "\n".join(moved[:8])
        if len(moved) > 8:
            result += f"\n... and {len(moved) - 8} more."
    if skipped:
        result += f"\n{len(skipped)} file(s) skipped (name conflict)."
    return result


def _clean_folder(folder: Path) -> str:
    if not folder.exists():
        return f"Folder not found: {folder}"
    today = datetime.now().strftime("%Y-%m-%d")
    archive_dir = folder / f"Archive {today}"
    archive_dir.mkdir(exist_ok=True)

    moved = 0
    for item in folder.iterdir():
        if item.is_dir() or item.name.startswith("."):
            continue
        if item.suffix.lower() in _DESKTOP_SKIP_EXTENSIONS:
            continue
        new_path = archive_dir / item.name
        if not new_path.exists():
            shutil.move(str(item), str(new_path))
            moved += 1
    return f"{folder} cleaned: {moved} files archived to '{archive_dir.name}'."


def _show_desktop() -> None:
    user32 = _user32()
    user32.keybd_event(_VK_LWIN, 0, 0, 0)
    user32.keybd_event(_VK_D, 0, 0, 0)
    user32.keybd_event(_VK_D, 0, _KEYEVENTF_KEYUP, 0)
    user32.keybd_event(_VK_LWIN, 0, _KEYEVENTF_KEYUP, 0)


@ToolRegistry.register("desktop_control")
class DesktopControlTool(BaseTool):
    """Control the desktop: wallpaper, window list, focus/minimize/maximize/close."""

    tool_id = "desktop_control"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="desktop_control",
            description=(
                "Controls the desktop: set/get wallpaper (file or URL), list open windows, "
                "focus/minimize/maximize/close a window by title, show the desktop, or "
                "manage desktop files (list, stats, organize by type/date, archive/clean)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": (
                            "wallpaper_set | wallpaper_set_url | wallpaper_get | "
                            "list_windows | focus_window | minimize_window | maximize_window | "
                            "close_window | show_desktop | list_files | stats | organize | clean"
                        ),
                    },
                    "path": {
                        "type": "string",
                        "description": (
                            "For wallpaper_set: image file path. For list_files/stats/organize/clean: "
                            "which folder to target — 'desktop' (default), 'documents', 'downloads', "
                            "'pictures', 'music', 'videos', or an absolute path."
                        ),
                    },
                    "url": {"type": "string", "description": "Image URL for wallpaper_set_url."},
                    "title": {
                        "type": "string",
                        "description": "Partial window title to match, for the *_window actions.",
                    },
                    "mode": {"type": "string", "description": "'by_type' or 'by_date' for organize (default by_type)."},
                },
                "required": ["action"],
            },
            category="system",
            required_capabilities=["system:admin"],
            timeout_seconds=15.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        if platform.system() != "Windows":
            return ToolResult(
                tool_name="desktop_control",
                content="desktop_control currently only supports Windows.",
                success=False,
            )

        action = (params.get("action") or "").strip().lower()

        try:
            if action == "wallpaper_set":
                path = params.get("path", "")
                if not path:
                    return ToolResult(tool_name="desktop_control", content="'path' is required.", success=False)
                ok, msg = _set_wallpaper(path)
                return ToolResult(tool_name="desktop_control", content=msg, success=ok)

            if action == "wallpaper_set_url":
                url = params.get("url", "")
                if not url:
                    return ToolResult(tool_name="desktop_control", content="'url' is required.", success=False)
                ok, msg = _set_wallpaper_from_url(url)
                return ToolResult(tool_name="desktop_control", content=msg, success=ok)

            if action == "wallpaper_get":
                ok, msg = _get_current_wallpaper()
                return ToolResult(tool_name="desktop_control", content=msg, success=ok)

            if action == "list_files":
                folder = _resolve_folder(params.get("path", ""))
                return ToolResult(tool_name="desktop_control", content=_list_folder(folder), success=True)

            if action == "stats":
                folder = _resolve_folder(params.get("path", ""))
                return ToolResult(tool_name="desktop_control", content=_folder_stats(folder), success=True)

            if action == "organize":
                folder = _resolve_folder(params.get("path", ""))
                mode = params.get("mode", "by_type")
                return ToolResult(tool_name="desktop_control", content=_organize_folder(folder, mode), success=True)

            if action == "clean":
                folder = _resolve_folder(params.get("path", ""))
                return ToolResult(tool_name="desktop_control", content=_clean_folder(folder), success=True)

            if action == "list_windows":
                windows = _list_top_windows()
                if not windows:
                    return ToolResult(tool_name="desktop_control", content="No visible windows found.", success=True)
                titles = [t for _, t in windows]
                return ToolResult(
                    tool_name="desktop_control",
                    content="\n".join(titles),
                    success=True,
                    metadata={"windows": titles},
                )

            if action in ("focus_window", "minimize_window", "maximize_window", "close_window"):
                title_query = params.get("title", "")
                if not title_query:
                    return ToolResult(tool_name="desktop_control", content="'title' is required.", success=False)
                found = _find_window(title_query)
                if not found:
                    return ToolResult(
                        tool_name="desktop_control",
                        content=f"No window matching '{title_query}' found.",
                        success=False,
                    )
                hwnd, real_title = found
                user32 = _user32()

                if action == "focus_window":
                    user32.ShowWindow(hwnd, _SW_RESTORE)
                    user32.SetForegroundWindow(hwnd)
                    return ToolResult(tool_name="desktop_control", content=f"Focused '{real_title}'.", success=True)

                if action == "minimize_window":
                    user32.ShowWindow(hwnd, _SW_MINIMIZE)
                    return ToolResult(tool_name="desktop_control", content=f"Minimized '{real_title}'.", success=True)

                if action == "maximize_window":
                    user32.ShowWindow(hwnd, _SW_MAXIMIZE)
                    return ToolResult(tool_name="desktop_control", content=f"Maximized '{real_title}'.", success=True)

                if action == "close_window":
                    user32.PostMessageW(hwnd, _WM_CLOSE, 0, 0)
                    return ToolResult(tool_name="desktop_control", content=f"Closed '{real_title}'.", success=True)

            if action == "show_desktop":
                _show_desktop()
                return ToolResult(tool_name="desktop_control", content="Showing desktop.", success=True)

            return ToolResult(
                tool_name="desktop_control",
                content=f"Unknown action '{action}'.",
                success=False,
            )
        except Exception as exc:
            return ToolResult(
                tool_name="desktop_control",
                content=f"desktop_control error: {exc}",
                success=False,
            )


__all__ = ["DesktopControlTool"]
