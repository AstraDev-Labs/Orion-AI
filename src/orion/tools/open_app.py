"""Open-app tool — launches any application by name, optionally navigating
it straight to a URL, file, or folder.

Windows-only, dependency-free (pure ctypes + stdlib), following the same
approach as system_control.py / desktop_control.py in this package.
"""

from __future__ import annotations

import ctypes
import os
import platform
import shutil
import re
import subprocess
import time
import urllib.parse
import webbrowser
from ctypes import wintypes
from typing import Any, Optional

from orion.core.registry import ToolRegistry
from orion.core.types import ToolResult
from orion.tools._stubs import BaseTool, ToolSpec

# Websites/web services people ask for by name — these aren't local Windows
# apps, so trying to launch them as one (direct binary, then Start Menu
# search) reliably fails: there's nothing to click in the Start Menu for
# "YouTube", so that fallback just leaves the search bar open with nothing
# launched. Route these straight to the browser instead, with the target
# used as a search query when the service supports one.
_WEB_SERVICES: dict[str, tuple[str, str]] = {
    # name -> (homepage_url, search_url_template or "")
    "youtube": ("https://www.youtube.com", "https://www.youtube.com/results?search_query={q}"),
    "gmail": ("https://mail.google.com/mail/u/0/#inbox", ""),
    "google": ("https://www.google.com", "https://www.google.com/search?q={q}"),
    "netflix": ("https://www.netflix.com", "https://www.netflix.com/search?q={q}"),
    "amazon": ("https://www.amazon.com", "https://www.amazon.com/s?k={q}"),
    "facebook": ("https://www.facebook.com", ""),
    "twitter": ("https://twitter.com", ""), "x": ("https://x.com", ""),
    "instagram": ("https://www.instagram.com", ""),
    "reddit": ("https://www.reddit.com", "https://www.reddit.com/search/?q={q}"),
    "linkedin": ("https://www.linkedin.com", ""),
    "github": ("https://github.com", "https://github.com/search?q={q}"),
    "maps": ("https://maps.google.com", "https://www.google.com/maps/search/{q}"),
    "google maps": ("https://maps.google.com", "https://www.google.com/maps/search/{q}"),
}

# Common app name -> Windows executable/command. Anything not listed here
# still works via the Start Menu search fallback.
_APP_ALIASES: dict[str, str] = {
    "chrome": "chrome", "google chrome": "chrome",
    "firefox": "firefox",
    "edge": "msedge", "microsoft edge": "msedge",
    "brave": "brave",
    "opera": "opera",
    "whatsapp": "WhatsApp",
    "telegram": "Telegram",
    "discord": "Discord",
    "slack": "slack",
    "zoom": "Zoom",
    "teams": "msteams", "microsoft teams": "msteams",
    "skype": "skype",
    "spotify": "spotify",
    "vlc": "vlc",
    "vscode": "code", "visual studio code": "code", "code": "code",
    "terminal": "wt",
    "cmd": "cmd.exe", "command prompt": "cmd.exe",
    "powershell": "powershell.exe",
    "postman": "Postman",
    "figma": "Figma",
    "blender": "blender",
    "word": "winword", "microsoft word": "winword",
    "excel": "excel", "microsoft excel": "excel",
    "powerpoint": "powerpnt",
    "notepad": "notepad.exe",
    "explorer": "explorer.exe", "file explorer": "explorer.exe",
    "task manager": "taskmgr.exe",
    "settings": "ms-settings:",
    "calculator": "calc.exe",
    "paint": "mspaint.exe",
    "notion": "Notion",
    "obsidian": "Obsidian",
    "steam": "steam",
    "epic": "EpicGamesLauncher", "epic games": "EpicGamesLauncher",
}


def _first_web_result(query: str) -> Optional[str]:
    """Return the first organic result URL for a query, or None on any failure.

    Uses the `ddgs` library (already a dependency of web_search.py /
    situation_awareness.py elsewhere in this codebase) rather than scraping
    a search engine's HTML directly — hand-rolled scraping of DuckDuckGo's
    "lite" HTML endpoint was tried first and reliably returned zero results
    (likely bot-detected), whereas ddgs is a maintained library built for
    exactly this and returns real results consistently.
    """
    try:
        from ddgs import DDGS

        results = DDGS().text(query, max_results=1)
        for r in results:
            href = r.get("href", "")
            if href.startswith("http"):
                return href
        return None
    except Exception:
        return None


def _normalize(app_name: str) -> str:
    key = app_name.lower().strip()
    if key in _APP_ALIASES:
        return _APP_ALIASES[key]
    for alias, cmd in _APP_ALIASES.items():
        if alias in key or key in alias:
            return cmd
    return app_name


# Common Windows apps whose installers don't add themselves to PATH, so
# shutil.which() alone can't find them even when they're genuinely installed
# (Chrome is the classic example — this caused a real, observed 15s timeout
# cascading all the way to the network-dependent web-search fallback for an
# app that was sitting right there on disk the whole time).
def _common_install_paths(command: str) -> list[str]:
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    local_app_data = os.environ.get("LOCALAPPDATA", "")

    candidates_by_cmd = {
        "chrome": [
            rf"{program_files}\Google\Chrome\Application\chrome.exe",
            rf"{program_files_x86}\Google\Chrome\Application\chrome.exe",
            rf"{local_app_data}\Google\Chrome\Application\chrome.exe",
        ],
        "firefox": [
            rf"{program_files}\Mozilla Firefox\firefox.exe",
            rf"{program_files_x86}\Mozilla Firefox\firefox.exe",
        ],
        "brave": [
            rf"{local_app_data}\BraveSoftware\Brave-Browser\Application\brave.exe",
        ],
        "spotify": [
            rf"{local_app_data}\Microsoft\WindowsApps\Spotify.exe",
            rf"{local_app_data}\Spotify\Spotify.exe",
        ],
        "discord": [
            rf"{local_app_data}\Discord\Update.exe",
        ],
    }
    return candidates_by_cmd.get(command.lower(), [])


def _app_paths_lookup(command: str) -> Optional[str]:
    """Resolve an executable via the Windows "App Paths" registry key.

    This is how Windows itself resolves names typed into Run/Start, and it is
    the authoritative source for installed apps that never touch PATH --
    Microsoft Office being the important one here. Without it, "excel"
    resolved to nothing and fell all the way through to the web-search
    fallback, which opened the *Wikipedia article about Excel* instead of
    the Excel that was installed the whole time.
    """
    import winreg

    exe = command if command.lower().endswith(".exe") else f"{command}.exe"
    subkey = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe}"
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(root, subkey) as key:
                path, _ = winreg.QueryValueEx(key, "")
                path = os.path.expandvars((path or "").strip('"'))
                if path and os.path.isfile(path):
                    return path
        except OSError:
            continue
    return None


# Indexes are cached because rebuilding them on every call is slow, but a
# process-lifetime cache would mean software installed while Orion is running
# stays invisible until the backend restarts. Callers therefore refresh on a
# miss (see _refresh_indexes_if_stale), and this cooldown stops a genuinely
# unknown name from triggering a rebuild on every single attempt.
_INDEX_REFRESH_COOLDOWN_SECONDS = 30.0
_LAST_INDEX_REFRESH = 0.0

_START_MENU_CACHE: Optional[dict[str, str]] = None


def _refresh_indexes_if_stale() -> bool:
    """Drop cached app indexes so the next lookup re-scans. Returns True if dropped."""
    global _LAST_INDEX_REFRESH, _START_MENU_CACHE, _START_APPS_CACHE
    now = time.time()
    if now - _LAST_INDEX_REFRESH < _INDEX_REFRESH_COOLDOWN_SECONDS:
        return False
    _LAST_INDEX_REFRESH = now
    _START_MENU_CACHE = None
    _START_APPS_CACHE = None
    return True


def _start_menu_index() -> dict[str, str]:
    """Map lower-cased shortcut names to .lnk paths from both Start Menus.

    Covers the long tail of installed software (including Store/UWP apps),
    which is what makes "open <anything installed>" work without maintaining
    an alias table for it. Built once per process -- walking these trees on
    every call would add noticeable latency to a tool the user waits on.
    """
    global _START_MENU_CACHE
    if _START_MENU_CACHE is not None:
        return _START_MENU_CACHE

    index: dict[str, str] = {}
    roots = [
        os.path.join(
            os.environ.get("ProgramData", r"C:\ProgramData"),
            r"Microsoft\Windows\Start Menu\Programs",
        ),
        os.path.join(
            os.environ.get("APPDATA", ""),
            r"Microsoft\Windows\Start Menu\Programs",
        ),
    ]
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        for dirpath, _dirnames, filenames in os.walk(root):
            for fn in filenames:
                if fn.lower().endswith((".lnk", ".url")):
                    index.setdefault(os.path.splitext(fn)[0].lower(), os.path.join(dirpath, fn))

    _START_MENU_CACHE = index
    return index


def _resolve_start_menu_shortcut(app_name: str) -> Optional[str]:
    """Find a Start Menu shortcut whose name matches *app_name*."""
    index = _start_menu_index()
    key = app_name.lower().strip()
    if key in index:
        return index[key]
    # Prefer the shortest matching name so "Excel" wins over
    # "Excel Add-in Manager"-style entries.
    matches = [v for k, v in index.items() if key in k]
    if matches:
        return min(matches, key=lambda p: len(os.path.basename(p)))
    return None


_START_APPS_CACHE: Optional[dict[str, str]] = None


def _packaged_app_index() -> dict[str, str]:
    """Discover launch identities and protocol names directly from manifests.

    Get-StartApps can omit installed Store apps. Protocol names let names such
    as Clock resolve without a hardcoded executable or app identity.
    """
    import json

    script = """
    $ErrorActionPreference = 'Stop'
    $items = foreach ($p in Get-AppxPackage) {
      try {
        $m = $p | Get-AppxPackageManifest
        foreach ($a in $m.Package.Applications.Application) {
          $id = $p.PackageFamilyName + '!' + $a.Id
          foreach ($n in @($p.Name, $a.VisualElements.DisplayName)) {
            if ($n -and $n -notlike 'ms-resource:*') {
              [pscustomobject]@{Name=[string]$n; AppID=$id}
            }
          }
          foreach ($e in $a.Extensions.Extension) {
            if ($e.Category -eq 'windows.protocol' -and $e.Protocol.Name) {
              [pscustomobject]@{Name=([string]$e.Protocol.Name -replace '^ms-', ''); AppID=$id}
            }
          }
        }
      } catch { }
    }
    @($items) | ConvertTo-Json -Compress
    """
    try:
        proc = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                              capture_output=True, text=True, timeout=20,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if proc.returncode != 0:
            return {}
        rows = json.loads(proc.stdout or "[]")
        return {r["Name"].lower(): r["AppID"] for r in rows if r.get("Name") and r.get("AppID")}
    except Exception:
        return {}


def _start_apps_index() -> dict[str, str]:
    """Map lower-cased app names to AppUserModelIDs via ``Get-StartApps``.

    Store/UWP apps (WhatsApp, Spotify, Store-installed anything) have no .exe
    on disk to launch and no classic Start Menu shortcut, so every path above
    misses them. This is the shell's own list of launchable apps and is what
    makes "open <any installed app>" actually mean *any*. Shelling out to
    PowerShell costs about a second, so it runs only as a last resort and is
    cached for the life of the process.
    """
    global _START_APPS_CACHE
    if _START_APPS_CACHE is not None:
        return _START_APPS_CACHE

    index: dict[str, str] = {}
    try:
        import json

        proc = subprocess.run(
            [
                "powershell", "-NoProfile", "-NonInteractive", "-Command",
                "Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress",
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            data = json.loads(proc.stdout)
            if isinstance(data, dict):
                data = [data]
            for entry in data:
                name = (entry.get("Name") or "").strip().lower()
                app_id = (entry.get("AppID") or "").strip()
                if name and app_id:
                    index.setdefault(name, app_id)
    except Exception:
        pass  # leave the index empty; callers fall through to the web lookup

    _START_APPS_CACHE = index
    return index


def _resolve_start_app(app_name: str) -> Optional[str]:
    """Return the AppUserModelID for *app_name*, if the shell knows one."""
    index = _start_apps_index()
    key = app_name.lower().strip()
    if key in index:
        return index[key]
    matches = [(k, v) for k, v in index.items() if key in k]
    if matches:
        return min(matches, key=lambda kv: len(kv[0]))[1]
    packages = _packaged_app_index()
    index.update(packages)
    if key in packages:
        return packages[key]
    return None


def _resolve_binary(command: str) -> Optional[str]:
    found = shutil.which(command) or shutil.which(command.split(".")[0])
    if found:
        return found
    resolved = _app_paths_lookup(command)
    if resolved:
        return resolved
    for path in _common_install_paths(command):
        if path and os.path.isfile(path):
            return path
    return None


# Folders searched, in order, when the user names a file without a path.
def _user_search_roots() -> list[str]:
    home = os.path.expanduser("~")
    roots = [
        os.path.join(home, "Documents"),
        os.path.join(home, "Desktop"),
        os.path.join(home, "Downloads"),
        os.path.join(home, "OneDrive", "Documents"),
        os.path.join(home, "OneDrive", "Desktop"),
        os.path.join(home, "Pictures"),
        os.path.join(home, "Videos"),
        os.path.join(home, "Music"),
    ]
    return [r for r in roots if os.path.isdir(r)]


# Directories that hold thousands of files nobody means when they say
# "open my report" -- skipping them keeps the search fast and the hits sane.
_SKIP_DIRS = {
    "node_modules", ".git", "venv", ".venv", "__pycache__", "site-packages",
    "AppData", ".cache", "dist", "build", ".next", "target",
}

_MAX_SEARCH_DEPTH = 6


def _normalize_filename(text: str) -> str:
    """Lower-case *text* and collapse every separator run to a single space.

    Users and models rarely reproduce a filename's punctuation exactly: the
    file on disk is "Alex devops.pdf" but the request arrives as
    "Alex_devops.pdf". Underscores, hyphens, dots and spaces all mean the
    same thing to a person naming a document, so they are flattened before
    comparing rather than treated as distinguishing characters.
    """
    return " ".join("".join(c if c.isalnum() else " " for c in text.lower()).split())


_FUZZY_THRESHOLD = 0.82


def _close_enough(query_norm: str, stem_norm: str, query_tokens: set) -> bool:
    """True if *stem_norm* is a near-miss for *query_norm* (typo tolerance).

    Compares whole strings, and also token-by-token so that a single
    misspelled word inside an otherwise-matching name still counts.
    """
    from difflib import SequenceMatcher

    if not query_norm or not stem_norm:
        return False
    if SequenceMatcher(None, query_norm, stem_norm).ratio() >= _FUZZY_THRESHOLD:
        return True
    if not query_tokens:
        return False
    stem_tokens = stem_norm.split()
    for q in query_tokens:
        if not any(
            q == s or SequenceMatcher(None, q, s).ratio() >= _FUZZY_THRESHOLD
            for s in stem_tokens
        ):
            return False
    return True


def _find_user_file(name: str) -> list[str]:
    """Find files under the user's folders matching *name*, best match first.

    Matching ignores the extension and all separator punctuation, and also
    accepts a filename that merely contains every word of the request, so
    "Election_Management_System_DB_Design_v2", "alex devops" and
    "Alex_devops.pdf" all find their file without the user having to
    reproduce the exact name.
    """
    raw = name.strip()
    query_ext = os.path.splitext(raw)[1].lower()
    query_norm = _normalize_filename(os.path.splitext(raw)[0]) or _normalize_filename(raw)
    query_tokens = set(query_norm.split())

    scored: list[tuple[tuple, str]] = []

    for root_index, root in enumerate(_user_search_roots()):
        root_depth = root.rstrip(os.sep).count(os.sep)
        for dirpath, dirnames, filenames in os.walk(root):
            if dirpath.count(os.sep) - root_depth >= _MAX_SEARCH_DEPTH:
                dirnames[:] = []
                continue
            dirnames[:] = [
                d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")
            ]
            for fn in filenames:
                stem, ext = os.path.splitext(fn)
                stem_norm = _normalize_filename(stem)
                if not stem_norm:
                    continue

                if stem_norm == query_norm:
                    rank = 0
                elif query_tokens and query_tokens <= set(stem_norm.split()):
                    rank = 1
                elif query_norm and query_norm in stem_norm:
                    rank = 2
                elif _close_enough(query_norm, stem_norm, query_tokens):
                    # Last resort: tolerate misspellings on either side. Real
                    # filenames contain typos ("Week2_Deliveriable.pdf"), and
                    # so do requests -- an exact-token search finds neither.
                    rank = 3
                else:
                    continue

                # Prefer the extension the user asked for, then shorter names
                # (fewer unrelated extra words), then earlier search roots.
                ext_rank = 0 if (query_ext and ext.lower() == query_ext) else 1
                scored.append(
                    ((rank, ext_rank, len(stem_norm), root_index), os.path.join(dirpath, fn))
                )

    scored.sort(key=lambda item: item[0])
    return [path for _score, path in scored]


def _open_path_with(path: str, app_name: str = "") -> tuple[bool, str]:
    """Open *path*, either in a specific app or in its default handler."""
    if app_name:
        binary = _resolve_binary(_normalize(app_name))
        if binary:
            subprocess.Popen([binary, path])
            return True, f"Opened {os.path.basename(path)} in {app_name}.\nFull path: {path}"
        # Named app couldn't be resolved -- opening in the default handler is
        # still what the user wanted (the file open), so do that and say so.
        os.startfile(path)  # type: ignore[attr-defined]
        return True, (
            f"Couldn't find '{app_name}' installed, so opened "
            f"{os.path.basename(path)} in its default app instead.\nFull path: {path}"
        )

    os.startfile(path)  # type: ignore[attr-defined]
    return True, f"Opened {os.path.basename(path)}.\nFull path: {path}"


def _open_file_request(file_name: str, app_name: str = "") -> tuple[bool, str]:
    """Locate a file the user named and open it."""
    expanded = os.path.expandvars(os.path.expanduser(file_name))
    if os.path.isfile(expanded):
        return _open_path_with(expanded, app_name)
    if os.path.isdir(expanded):
        subprocess.Popen(["explorer.exe", expanded])
        return True, f"Opened folder {expanded} in File Explorer."

    matches = _find_user_file(file_name)
    if not matches:
        # dict.fromkeys dedupes while preserving order -- Documents and
        # OneDrive\Documents share a basename and read as a stutter otherwise.
        roots = ", ".join(dict.fromkeys(os.path.basename(r) for r in _user_search_roots()))
        return False, (
            f"Couldn't find any file named '{file_name}' in your {roots} folders. "
            "Ask the user to check the name or give the full path. "
            "This is a file on the user's own computer — do NOT run a web search "
            "for it, and do not claim it was opened."
        )

    ok, msg = _open_path_with(matches[0], app_name)
    if len(matches) > 1:
        others = "\n".join(f"  - {p}" for p in matches[1:4])
        msg += f"\n\n{len(matches)} files matched; opened the closest one. Others:\n{others}"
    return ok, msg


def _send_text(text: str) -> None:
    """Type text into the currently-focused control using SendInput (Unicode mode)."""
    user32 = ctypes.windll.user32  # type: ignore[attr-defined]

    PUL = ctypes.POINTER(ctypes.c_ulong)

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
            ("dwExtraInfo", PUL),
        ]

    class _INPUTUNION(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("union", _INPUTUNION)]

    INPUT_KEYBOARD = 1
    KEYEVENTF_UNICODE = 0x0004
    KEYEVENTF_KEYUP = 0x0002

    for ch in text:
        code = ord(ch)
        down = INPUT(type=INPUT_KEYBOARD, union=_INPUTUNION(
            ki=KEYBDINPUT(0, code, KEYEVENTF_UNICODE, 0, None)))
        up = INPUT(type=INPUT_KEYBOARD, union=_INPUTUNION(
            ki=KEYBDINPUT(0, code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, None)))
        user32.SendInput(1, ctypes.byref(down), ctypes.sizeof(INPUT))
        user32.SendInput(1, ctypes.byref(up), ctypes.sizeof(INPUT))
        time.sleep(0.01)


def _press_key(vk: int) -> None:
    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    user32.keybd_event(vk, 0, 0, 0)
    user32.keybd_event(vk, 0, 0x0002, 0)  # KEYEVENTF_KEYUP


def _snapshot_window_titles() -> set:
    """Titles of currently visible top-level windows, for before/after diffing."""
    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    titles: set = set()

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            titles.add(buf.value)
        return True

    user32.EnumWindows(_callback, 0)
    return titles


def _launch_via_start_menu(app_name: str) -> bool:
    """Press Win, type the name, press Enter — then verify a new window
    actually appeared. Pressing Enter always "succeeds" as a key sequence
    even when nothing in the Start Menu matched, which previously made this
    function unconditionally report success and silently do nothing."""
    try:
        before = _snapshot_window_titles()
        _VK_LWIN = 0x5B
        _VK_RETURN = 0x0D
        _press_key(_VK_LWIN)
        time.sleep(0.4)
        _send_text(app_name)
        time.sleep(0.6)
        _press_key(_VK_RETURN)
        time.sleep(1.5)
        after = _snapshot_window_titles()
        return bool(after - before)
    except Exception:
        return False


def _resolve_exact(name: str) -> Optional[tuple[str, str]]:
    """Resolve *name* against the live system, without alias rewriting.

    Returns ``(kind, value)`` where kind is "binary", "shortcut" or "appid",
    or None. On a miss the cached indexes are refreshed once (subject to a
    cooldown) and the lookup retried, so an app installed while Orion is
    running is found on the next request rather than after a restart.
    """
    for attempt in (0, 1):
        binary = _resolve_binary(name)
        if binary:
            return ("binary", binary)
        shortcut = _resolve_start_menu_shortcut(name)
        if shortcut:
            return ("shortcut", shortcut)
        app_id = _resolve_start_app(name)
        if app_id:
            return ("appid", app_id)
        if attempt == 0 and not _refresh_indexes_if_stale():
            break  # refreshed too recently to be worth re-scanning
    return None


def _launch_resolved(app_name: str, resolved: tuple[str, str], target: str) -> tuple[bool, str]:
    """Launch something already resolved by :func:`_resolve_exact`."""
    kind, value = resolved
    if kind == "binary":
        subprocess.Popen([value, target] if target else [value])
        suffix = f" with target {target}" if target else ""
        return True, f"Launch requested for {app_name}{suffix}. The window and target content have not been verified."
    if kind == "shortcut":
        if target:
            # `start "" "app.lnk" "arg"` forwards the argument to whatever the
            # shortcut points at, so a target still reaches the app even when
            # no executable could be resolved for it.
            subprocess.Popen(["cmd", "/c", "start", "", value, target], shell=False)
            return True, f"Launch requested for {app_name} with {target}. The window and target content have not been verified."
        os.startfile(value)  # type: ignore[attr-defined]
        return True, f"Launch requested for {app_name}. The window has not been verified."

    # Store/UWP app: the shell launches these by identity, with nowhere to put
    # an argument. A URL can still be honoured by handing it to the default
    # browser rather than dropping it silently.
    subprocess.Popen(["explorer.exe", rf"shell:AppsFolder\{value}"])
    if target:
        if target.lower().startswith(("http://", "https://")):
            webbrowser.open(target)
            return True, (
                f"Opened {app_name}. It's a Store app and can't be handed a URL, "
                f"so {target} was opened in your default browser instead."
            )
        return True, (
            f"Opened {app_name}, but '{target}' could not be passed to a Store app — "
            "open it manually once launched."
        )
    return True, f"Launch requested for {app_name}. The window has not been verified."


def _launch(app_name: str, target: str = "") -> tuple[bool, str]:
    """Try direct binary launch first (supports a target arg), then Start Menu search."""
    web_key = app_name.lower().strip()
    if web_key in _WEB_SERVICES:
        homepage, search_template = _WEB_SERVICES[web_key]
        if target and search_template:
            url = search_template.format(q=urllib.parse.quote(target))
            webbrowser.open(url)
            return True, f"Opened {app_name} in your browser, searching for {target}."
        webbrowser.open(homepage)
        suffix = f" (this site has no search — opened the homepage; target '{target}' not applied)" if target else ""
        return True, f"Opened {app_name} in your browser.{suffix}"

    normalized = _normalize(app_name)

    # The alias table is a convenience for nicknames ("vscode" -> "code"), not
    # the source of truth, and its fuzzy substring matching will happily map a
    # newly-installed app onto an old alias (e.g. "Codex" -> VS Code's "code").
    # So try the name the user actually said against the live system indexes
    # first, and only fall back to the alias interpretation if that finds
    # nothing. Everything below reads from Windows itself, which means newly
    # installed software works with no code change.
    if app_name.lower().strip() != normalized.lower().strip():
        direct = _resolve_exact(app_name)
        if direct:
            # Only a real executable can be handed an argument. If the raw name
            # matched a Start Menu shortcut or Store app but a target has to be
            # passed, look for the actual binary under the alias instead --
            # otherwise the target is silently dropped, which is what turned
            # "open Edge at <url>" into a bare browser window.
            if target and direct[0] != "binary":
                binary = _resolve_binary(normalized)
                if binary:
                    direct = ("binary", binary)
            return _launch_resolved(app_name, direct, target)

    if normalized == "ms-settings:":
        subprocess.Popen(f"start {normalized}", shell=True)
        return True, "Opened Settings."

    if normalized.lower() in ("explorer.exe", "explorer") and target:
        subprocess.Popen(["explorer.exe", target])
        return True, f"Opened File Explorer at {target}."

    # Resolution below reads live Windows state -- PATH, the App Paths
    # registry, both Start Menu trees, and the shell's app list -- so any
    # newly installed program is found without touching this file. Both the
    # alias-normalized name and the raw name are tried.
    resolved = _resolve_exact(normalized) or _resolve_exact(app_name)
    if resolved:
        if target and resolved[0] != "binary":
            binary = _resolve_binary(normalized) or _resolve_binary(app_name)
            if binary:
                resolved = ("binary", binary)
        return _launch_resolved(app_name, resolved, target)

    if _launch_via_start_menu(normalized):
        note = " (target could not be passed via Start Menu search — open it manually once launched)" if target else ""
        return True, f"Opened {app_name} via Start Menu search.{note}"

    # Nothing local matched. Rather than give up (or, as before, falsely
    # claim success), assume this is a website/service we don't have a
    # dedicated entry for. Look up its actual site and open THAT directly —
    # not just a page of search results — so this covers anything not in
    # _WEB_SERVICES or _APP_ALIASES without needing to hand-maintain an
    # ever-growing list.
    lookup_query = f"{app_name} official site" if not target else f"{app_name} {target}"
    result_url = _first_web_result(lookup_query)
    # Only open a search hit that is plausibly the service itself. Opening
    # whatever ranked first sent a made-up app name to an APK download site.
    if result_url and _domain_matches_name(result_url, app_name):
        webbrowser.open(result_url)
        return True, f"Couldn't find '{app_name}' as an installed app — opened its website {result_url} instead."

    return False, (
        f"Could not resolve or verify a launch for '{app_name}'. Nothing was opened by this method. "
        "This does not prove it is uninstalled. Inspect installed packages or protocols with "
        "an available execution tool and try a discovered launch identity; verify the result. "
        "Only offer installation if discovery confirms it is missing."
    )


def _domain_matches_name(url: str, app_name: str) -> bool:
    """True when a distinctive word of *app_name* appears in the URL's domain."""
    host = (urllib.parse.urlparse(url).hostname or "").lower().replace("-", "")
    words = [w for w in re.findall(r"[a-z0-9]+", app_name.lower()) if len(w) >= 3]
    generic = {"app", "the", "official", "site", "desktop", "online", "web"}
    return any(w in host for w in words if w not in generic)


@ToolRegistry.register("open_app")
class OpenAppTool(BaseTool):
    """Launch any application by name, optionally navigating it to a URL/file/folder."""

    tool_id = "open_app"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="open_app",
            # Kept short: this description is re-read with every request that
            # offers the tool (it was ~500 tokens, about half a second each time).
            description=(
                "Open an app, website or web service by name (Chrome, VS Code, YouTube, "
                "Gmail...). Unknown names fall back to a web search. 'target' is a search "
                "query for sites that support one, or a path/URL for local apps.\n"
                "'Open <browser> and search <site> for <query>': build the site's search URL "
                "yourself and pass it as target, e.g. app_name='Chrome', "
                "target='https://www.youtube.com/results?search_query=YR+RootX'.\n"
                "A specific file or document: pass its name as file_name (extension and path "
                "optional); it opens in its default app.\n"
                "To PLAY a song or video use play_music or play_video instead."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "app_name": {"type": "string", "description": "Name of the application, e.g. 'Chrome', 'Spotify', 'Notepad'."},
                    "file_name": {
                        "type": "string",
                        "description": (
                            "Name of a file/document to find and open, e.g. 'budget_2026' or "
                            "'report.pdf', or a full path. Extension optional. Use this instead "
                            "of app_name whenever the user wants to open a specific document."
                        ),
                    },
                    "target": {
                        "type": "string",
                        "description": (
                            "Optional URL, file path, or folder path to open the app with/at. "
                            "For a browser + a search request, this MUST be the target site's full "
                            "search-results URL, not just the raw query text."
                        ),
                    },
                },
                "required": ["app_name"],
            },
            category="system",
            required_capabilities=["system:admin"],
            timeout_seconds=25.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        if platform.system() != "Windows":
            return ToolResult(tool_name="open_app", content="open_app currently only supports Windows.", success=False)

        app_name = (params.get("app_name") or "").strip()
        target = (params.get("target") or "").strip()
        file_name = (params.get("file_name") or "").strip()

        if not app_name and not file_name:
            return ToolResult(
                tool_name="open_app",
                content="Provide 'app_name' (to open an app/site) or 'file_name' (to open a document).",
                success=False,
            )

        try:
            if file_name:
                ok, msg = _open_file_request(file_name, app_name)
                return ToolResult(tool_name="open_app", content=msg, success=ok)

            ok, msg = _launch(app_name, target)
            if ok and msg.startswith("Launch requested"):
                # Shell activation returning successfully is only an accepted
                # request. Read visible window titles before claiming opened.
                names = {app_name.casefold().strip(), os.path.splitext(_normalize(app_name))[0].casefold()}
                visible = False
                for _ in range(3):
                    try:
                        visible = any(name and name in title.casefold() for name in names for title in _snapshot_window_titles())
                    except Exception:
                        break
                    if visible:
                        break
                    time.sleep(0.5)
                if not visible:
                    return ToolResult(tool_name="open_app", success=False,
                        content=msg + " No matching visible window was observed yet. The app may use a different title or still be starting. Inspect desktop state before retrying; do not assume it is missing.",
                        metadata={"launch_requested": True, "window_verified": False})
                return ToolResult(tool_name="open_app", success=True,
                    content=f"A visible window matching {app_name} was observed. " + ("The target content inside the window has not been verified." if target else ""),
                    metadata={"launch_requested": True, "window_verified": True})
            return ToolResult(tool_name="open_app", content=msg, success=ok)
        except Exception as exc:
            label = file_name or app_name
            return ToolResult(tool_name="open_app", content=f"Failed to open {label}: {exc}", success=False)


__all__ = ["OpenAppTool"]
