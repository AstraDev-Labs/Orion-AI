"""install_game -- install a game from Steam, Epic, EA, or Ubisoft Connect.

Unlike install_app, none of these platforms expose a package manager. Each one
ships a launcher that owns the download pipeline and gates it on library
ownership, so the job here is:

1. **Detect** which launchers are actually on this machine.
2. **Resolve** the spoken title to a platform-specific app id.
3. **Establish ownership**, and say honestly how confident that answer is.
4. **Check the machine against the game's stated requirements**.
5. **Queue** the install for approval; on approval, hand the launcher a
   protocol URL (``steam://install/<appid>`` and friends) and let it download.

What ownership can honestly mean here
-------------------------------------
Only two sources are authoritative. A game already present in the local
manifests is definitely owned, and Steam's Web API returns a real library list
when the user has configured an API key. Everything else is a guess, so it is
reported as ``unverified`` rather than dressed up as a yes. Epic, EA, and
Ubisoft publish no unauthenticated ownership endpoint at all; their local
files list installed titles only.

Firing an install URL for a game the user does not own cannot buy anything --
the launcher opens its store page and waits for a human. That makes proceeding
under uncertainty safe, but the user is told which case they are in rather
than finding out when a store page appears.

What the requirements check can honestly compare
------------------------------------------------
Memory, storage, VRAM, and OS version are numbers, and they are compared
properly -- including against free space on the drive the game would actually
land on. CPU and GPU requirements are model names ("Intel i5-8600 / AMD Ryzen 5
1600x"), and ranking two arbitrary part numbers is not something this code can
do truthfully, so those are reported side by side and marked as needing a human
eye. A shortfall never blocks the install on its own; it is surfaced, and
``ignore_requirements`` carries it forward.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import re
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from orion.core.registry import ToolRegistry
from orion.core.types import ToolResult
from orion.tools._stubs import BaseTool, ToolSpec
from orion.tools.approval_store import TIER_HIGH, TIER_MEDIUM
from orion.tools.proactive_tools import get_store

logger = logging.getLogger(__name__)

PLATFORM_STEAM = "steam"
PLATFORM_EPIC = "epic"
PLATFORM_EA = "ea"
PLATFORM_UBISOFT = "ubisoft"

_PLATFORM_LABELS = {
    PLATFORM_STEAM: "Steam",
    PLATFORM_EPIC: "Epic Games",
    PLATFORM_EA: "EA app",
    PLATFORM_UBISOFT: "Ubisoft Connect",
}

# Ownership confidence
OWNED_INSTALLED = "installed"  # present in local manifests -- certain
OWNED_CONFIRMED = "owned"  # Steam Web API confirmed it -- certain
OWNED_NOT = "not_owned"  # Steam Web API says it is not in the library
OWNED_UNVERIFIED = "unverified"  # no credentials; genuinely unknown

# Requirement verdicts
REQ_PASS = "pass"
REQ_FAIL = "fail"
REQ_MANUAL = "manual"  # not machine-comparable; shown for a human to judge
REQ_UNKNOWN = "unknown"  # the game did not state it

_HTTP_TIMEOUT = 25.0
_CMD_TIMEOUT = 60.0

# WMI reports slightly less physical memory than is installed (firmware
# reserves some), so a 16 GB machine reads as ~15.7 GB. Without this
# tolerance every 16 GB requirement would read as a failure on a 16 GB box.
_RAM_TOLERANCE_GB = 0.6

_USER_AGENT = "Orion-AI/1.0 (+local assistant)"

# Steam ships runtimes and tools through the same appmanifest mechanism as
# games, with nothing in the manifest to tell them apart -- "Steamworks Common
# Redistributables" carries a name, an installdir and a SizeOnDisk exactly like
# a real title. These are the well-known infrastructure appids, excluded so
# they never surface as something the user could ask to play.
_STEAM_NON_GAME_APPIDS = frozenset(
    {
        "228980",   # Steamworks Common Redistributables
        "1070560",  # Steam Linux Runtime 1.0 (scout)
        "1391110",  # Steam Linux Runtime 2.0 (soldier)
        "1628350",  # Steam Linux Runtime 3.0 (sniper)
        "1493710",  # Proton Experimental
        "858280",   # Proton 3.7
        "961940",   # Proton 3.16
        "1054830",  # Proton 5.0
        "1245040",  # Proton 5.13
        "1420170",  # Proton 6.3
        "1580130",  # Proton 7.0
        "2180100",  # Proton 8.0
        "2805730",  # Proton 9.0
    }
)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class GameRef:
    """One game on one platform."""

    platform: str
    app_id: str
    title: str
    install_dir: str = ""
    size_bytes: int = 0

    @property
    def platform_label(self) -> str:
        return _PLATFORM_LABELS.get(self.platform, self.platform)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "platform": self.platform,
            "platform_label": self.platform_label,
            "app_id": self.app_id,
            "title": self.title,
            "install_dir": self.install_dir,
            "size_bytes": self.size_bytes,
        }


@dataclass
class Specs:
    """What this machine actually has."""

    cpu: str = ""
    cores: int = 0
    ram_gb: float = 0.0
    gpu: str = ""
    vram_gb: float = 0.0
    os_caption: str = ""
    os_build: str = ""
    arch: str = ""
    free_disk_gb: float = 0.0
    disk_target: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cpu": self.cpu,
            "cores": self.cores,
            "ram_gb": self.ram_gb,
            "gpu": self.gpu,
            "vram_gb": self.vram_gb,
            "os": self.os_caption,
            "os_build": self.os_build,
            "arch": self.arch,
            "free_disk_gb": self.free_disk_gb,
            "disk_target": self.disk_target,
        }


@dataclass
class Check:
    """One requirement compared against the machine."""

    item: str
    required: str
    actual: str
    verdict: str
    note: str = ""

    def to_dict(self) -> Dict[str, str]:
        return {
            "item": self.item,
            "required": self.required,
            "actual": self.actual,
            "verdict": self.verdict,
            "note": self.note,
        }


@dataclass
class GameReport:
    game: GameRef
    ownership: str
    checks: List[Check] = field(default_factory=list)
    specs: Optional[Specs] = None
    requirements_source: str = ""
    notes: List[str] = field(default_factory=list)

    @property
    def failures(self) -> List[Check]:
        return [c for c in self.checks if c.verdict == REQ_FAIL]

    @property
    def meets_requirements(self) -> bool:
        return not self.failures

    def to_dict(self) -> Dict[str, Any]:
        return {
            "game": self.game.to_dict(),
            "ownership": self.ownership,
            "meets_requirements": self.meets_requirements,
            "checks": [c.to_dict() for c in self.checks],
            "specs": self.specs.to_dict() if self.specs else {},
            "requirements_source": self.requirements_source,
            "notes": self.notes,
        }

    def summary(self) -> str:
        g = self.game
        lines = [f"{g.title}  ({g.platform_label}, app id {g.app_id})"]
        lines.append(
            {
                OWNED_INSTALLED: "Library: already installed on this machine.",
                OWNED_CONFIRMED: "Library: confirmed in your library.",
                OWNED_NOT: "Library: NOT in your library.",
                OWNED_UNVERIFIED: (
                    "Library: could not be verified -- no credentials for this platform."
                ),
            }.get(self.ownership, f"Library: {self.ownership}")
        )
        if self.checks:
            lines.append("")
            lines.append(
                f"System requirements ({self.requirements_source or 'source unknown'}):"
            )
            marker = {REQ_PASS: "ok  ", REQ_FAIL: "FAIL", REQ_MANUAL: "  ? ", REQ_UNKNOWN: "  - "}
            for c in self.checks:
                lines.append(
                    f"  {marker.get(c.verdict, '    ')} {c.item}: needs {c.required or 'unstated'}"
                    f" | you have {c.actual or 'unknown'}"
                    + (f"  ({c.note})" if c.note else "")
                )
        for note in self.notes:
            lines.append(f"Note: {note}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _is_windows() -> bool:
    return platform.system() == "Windows"


def _run_ps(script: str, timeout: float = _CMD_TIMEOUT) -> str:
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.debug("powershell call failed: %s", exc)
        return ""
    return proc.stdout.strip()


def _get_json(url: str) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=_HTTP_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


# ---------------------------------------------------------------------------
# Valve Data Format (libraryfolders.vdf, appmanifest_*.acf)
# ---------------------------------------------------------------------------

_VDF_TOKEN = re.compile(r'"((?:[^"\\]|\\.)*)"|([{}])')


def _vdf_loads(text: str) -> Dict[str, Any]:
    """Minimal VDF reader -- enough for Steam's library and app manifests."""
    tokens: List[Tuple[str, str]] = []
    for match in _VDF_TOKEN.finditer(text):
        if match.group(1) is not None:
            tokens.append(("s", match.group(1).replace("\\\\", "\\").replace('\\"', '"')))
        else:
            tokens.append(("b", match.group(2)))

    pos = 0

    def parse_block() -> Dict[str, Any]:
        nonlocal pos
        block: Dict[str, Any] = {}
        while pos < len(tokens):
            kind, value = tokens[pos]
            if kind == "b":
                pos += 1
                if value == "}":
                    return block
                continue
            key = value
            pos += 1
            if pos >= len(tokens):
                break
            next_kind, next_value = tokens[pos]
            if next_kind == "b" and next_value == "{":
                pos += 1
                block[key] = parse_block()
            else:
                block[key] = next_value
                pos += 1
        return block

    root: Dict[str, Any] = {}
    while pos < len(tokens):
        kind, value = tokens[pos]
        if kind != "s":
            pos += 1
            continue
        key = value
        pos += 1
        if pos < len(tokens) and tokens[pos] == ("b", "{"):
            pos += 1
            root[key] = parse_block()
        else:
            pos += 1
    return root


# ---------------------------------------------------------------------------
# Platform discovery
# ---------------------------------------------------------------------------


def _steam_root() -> Optional[Path]:
    if not _is_windows():
        return None
    out = _run_ps(
        "(Get-ItemProperty 'HKCU:\\Software\\Valve\\Steam' -ErrorAction SilentlyContinue).SteamPath"
    )
    if not out:
        out = _run_ps(
            "(Get-ItemProperty 'HKLM:\\SOFTWARE\\WOW6432Node\\Valve\\Steam' "
            "-ErrorAction SilentlyContinue).InstallPath"
        )
    path = Path(out.strip()) if out.strip() else None
    return path if path and path.is_dir() else None


def _steam_libraries(root: Path) -> List[Path]:
    """Every Steam library folder, not just the default one -- games routinely
    live on a second drive, and that drive is what free space must be measured
    against."""
    vdf = root / "steamapps" / "libraryfolders.vdf"
    libraries: List[Path] = []
    if vdf.exists():
        try:
            data = _vdf_loads(vdf.read_text(encoding="utf-8", errors="replace"))
            folders = data.get("libraryfolders", {})
            for entry in folders.values():
                if isinstance(entry, dict) and entry.get("path"):
                    candidate = Path(entry["path"]) / "steamapps"
                    if candidate.is_dir():
                        libraries.append(candidate)
        except Exception as exc:
            logger.debug("could not parse libraryfolders.vdf: %s", exc)
    default = root / "steamapps"
    if default.is_dir() and default not in libraries:
        libraries.append(default)
    return libraries


def _steam_installed() -> List[GameRef]:
    root = _steam_root()
    if not root:
        return []
    games: List[GameRef] = []
    for library in _steam_libraries(root):
        for manifest in library.glob("appmanifest_*.acf"):
            try:
                state = _vdf_loads(
                    manifest.read_text(encoding="utf-8", errors="replace")
                ).get("AppState", {})
            except Exception:
                continue
            app_id = str(state.get("appid", "")).strip()
            name = str(state.get("name", "")).strip()
            if not app_id or not name or app_id in _STEAM_NON_GAME_APPIDS:
                continue
            games.append(
                GameRef(
                    platform=PLATFORM_STEAM,
                    app_id=app_id,
                    title=name,
                    install_dir=str(library / "common" / str(state.get("installdir", ""))),
                    size_bytes=int(str(state.get("SizeOnDisk", "0")) or 0),
                )
            )
    return games


def _epic_installed() -> List[GameRef]:
    root = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests"
    if not root.is_dir():
        return []
    games: List[GameRef] = []
    for item in root.glob("*.item"):
        try:
            data = json.loads(item.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        title = (data.get("DisplayName") or "").strip()
        app_name = (data.get("AppName") or "").strip()
        if not title or not app_name:
            continue
        # Engine plugins and SDKs share this manifest store with real games;
        # only entries with a launch executable are actually playable titles.
        if not (data.get("LaunchExecutable") or "").strip():
            continue
        namespace = (data.get("CatalogNamespace") or "").strip()
        catalog_id = (data.get("CatalogItemId") or "").strip()
        games.append(
            GameRef(
                platform=PLATFORM_EPIC,
                app_id=f"{namespace}:{catalog_id}:{app_name}" if namespace else app_name,
                title=title,
                install_dir=(data.get("InstallLocation") or "").strip(),
                size_bytes=int(data.get("InstallSize") or 0),
            )
        )
    return games


def _ubisoft_installed() -> List[GameRef]:
    if not _is_windows():
        return []
    out = _run_ps(
        "Get-ChildItem 'HKLM:\\SOFTWARE\\WOW6432Node\\Ubisoft\\Launcher\\Installs' "
        "-ErrorAction SilentlyContinue | ForEach-Object { "
        "$p = Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue; "
        "[pscustomobject]@{ id = $_.PSChildName; dir = [string]$p.InstallDir } } "
        "| ConvertTo-Json -Compress"
    )
    entries = _as_list(out)
    games: List[GameRef] = []
    for entry in entries:
        app_id = str(entry.get("id", "")).strip()
        install_dir = str(entry.get("dir", "")).strip()
        if not app_id:
            continue
        title = Path(install_dir.rstrip("/\\")).name if install_dir else f"Ubisoft app {app_id}"
        games.append(
            GameRef(
                platform=PLATFORM_UBISOFT,
                app_id=app_id,
                title=title,
                install_dir=install_dir,
            )
        )
    return games


def _ea_installed() -> List[GameRef]:
    """EA's local content index. EA has moved this between Origin and the EA
    app across versions, so both known locations are read and neither is
    assumed to exist."""
    games: List[GameRef] = []
    roots = [
        Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "EA Desktop" / "InstallData",
        Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Origin" / "LocalContent",
    ]
    for root in roots:
        if not root.is_dir():
            continue
        for entry in root.iterdir():
            if not entry.is_dir():
                continue
            games.append(
                GameRef(
                    platform=PLATFORM_EA,
                    app_id=entry.name,
                    title=entry.name,
                    install_dir=str(entry),
                )
            )
    return games


def _as_list(json_text: str) -> List[Dict[str, Any]]:
    """PowerShell's ConvertTo-Json emits a bare object for a single result and
    an array for several; normalise both to a list."""
    if not json_text.strip():
        return []
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        return [data]
    return [d for d in data if isinstance(d, dict)]


def detect_platforms() -> Dict[str, bool]:
    """Which launchers this machine can actually drive."""
    if not _is_windows():
        return {p: False for p in _PLATFORM_LABELS}
    out = _run_ps(
        "@('steam','com.epicgames.launcher','uplay','link2ea') | ForEach-Object { "
        "[pscustomobject]@{ scheme = $_; present = "
        "(Test-Path ('Registry::HKEY_CLASSES_ROOT\\' + $_)) } } | ConvertTo-Json -Compress"
    )
    present = {e.get("scheme"): bool(e.get("present")) for e in _as_list(out)}
    return {
        PLATFORM_STEAM: bool(present.get("steam")),
        PLATFORM_EPIC: bool(present.get("com.epicgames.launcher")),
        PLATFORM_UBISOFT: bool(present.get("uplay")),
        PLATFORM_EA: bool(present.get("link2ea")),
    }


def installed_games() -> List[GameRef]:
    games: List[GameRef] = []
    for loader in (_steam_installed, _epic_installed, _ubisoft_installed, _ea_installed):
        try:
            games.extend(loader())
        except Exception as exc:  # a broken manifest must not sink the lookup
            logger.debug("%s failed: %s", getattr(loader, "__name__", loader), exc)
    return games


# ---------------------------------------------------------------------------
# Steam catalogue + ownership
# ---------------------------------------------------------------------------


def _steam_search(title: str) -> List[Dict[str, Any]]:
    url = (
        "https://store.steampowered.com/api/storesearch/?term="
        + urllib.parse.quote(title)
        + "&l=english&cc=US"
    )
    try:
        data = _get_json(url)
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
        logger.debug("steam search failed: %s", exc)
        return []
    return [i for i in (data or {}).get("items", []) if i.get("id")]


def _steam_appdetails(app_id: str) -> Dict[str, Any]:
    url = f"https://store.steampowered.com/api/appdetails?appids={app_id}&l=english"
    try:
        data = _get_json(url)
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
        logger.debug("steam appdetails failed: %s", exc)
        return {}
    entry = (data or {}).get(str(app_id)) or {}
    return entry.get("data", {}) if entry.get("success") else {}


def _steam_api_key() -> str:
    return (os.environ.get("STEAM_API_KEY") or "").strip()


def _steam_id() -> str:
    """The logged-in SteamID64, read from Steam's own login records."""
    explicit = (os.environ.get("STEAM_ID") or "").strip()
    if explicit:
        return explicit
    root = _steam_root()
    if not root:
        return ""
    login = root / "config" / "loginusers.vdf"
    if login.exists():
        try:
            users = _vdf_loads(login.read_text(encoding="utf-8", errors="replace")).get("users", {})
            for steam_id, info in users.items():
                if str(info.get("MostRecent", "0")) == "1":
                    return steam_id
            if users:
                return next(iter(users))
        except Exception as exc:
            logger.debug("could not read loginusers.vdf: %s", exc)
    return ""


def _steam_owns(app_id: str) -> Tuple[str, str]:
    """Ownership via Steam's Web API. Returns (ownership, explanation).

    Requires STEAM_API_KEY. Steam has no unauthenticated ownership endpoint --
    the public profile route returns a sign-in page for anything but a fully
    public profile -- so without a key this reports UNVERIFIED rather than
    guessing.
    """
    key = _steam_api_key()
    if not key:
        return OWNED_UNVERIFIED, (
            "No STEAM_API_KEY is set, so your Steam library cannot be read. Get a free "
            "key at steamcommunity.com/dev/apikey and set STEAM_API_KEY to have Orion "
            "check ownership before installing."
        )
    steam_id = _steam_id()
    if not steam_id:
        return OWNED_UNVERIFIED, "Could not determine which Steam account is signed in."
    url = (
        "https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/"
        f"?key={urllib.parse.quote(key)}&steamid={urllib.parse.quote(steam_id)}"
        "&include_played_free_games=1&format=json"
    )
    try:
        data = _get_json(url)
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
        return OWNED_UNVERIFIED, f"The Steam library lookup failed: {exc}"
    games = ((data or {}).get("response") or {}).get("games")
    if games is None:
        return OWNED_UNVERIFIED, (
            "Steam returned no library data -- the account's game details may be private."
        )
    if any(str(g.get("appid")) == str(app_id) for g in games):
        return OWNED_CONFIRMED, f"Found in your Steam library ({len(games)} games)."
    return OWNED_NOT, (
        f"Not present in your Steam library ({len(games)} games checked)."
    )


# ---------------------------------------------------------------------------
# Requirements
# ---------------------------------------------------------------------------

_REQ_ITEM_RE = re.compile(r"<strong>\s*([^<:]+?)\s*:?\s*</strong>\s*([^<]*)", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")


def parse_requirements(html: str) -> Dict[str, str]:
    """Pull labelled requirement lines out of Steam's HTML blob."""
    fields: Dict[str, str] = {}
    for label, value in _REQ_ITEM_RE.findall(html or ""):
        key = label.strip().lower()
        text = _TAG_RE.sub("", value).replace("&nbsp;", " ").strip()
        if key in {"minimum", "recommended"} or not text:
            continue
        fields.setdefault(key, text)
    return fields


def _first_gb(text: str) -> Optional[float]:
    match = re.search(r"(\d+(?:\.\d+)?)\s*(gb|mb)\b", text or "", re.IGNORECASE)
    if not match:
        return None
    value = float(match.group(1))
    return value / 1024.0 if match.group(2).lower() == "mb" else value


def _windows_major(text: str) -> Optional[int]:
    match = re.search(r"windows\s*(?:®\s*)?(\d{1,2})", text or "", re.IGNORECASE)
    return int(match.group(1)) if match else None


def read_specs(target_dir: str = "") -> Specs:
    """Read this machine's hardware.

    VRAM comes from the display driver's registry entry rather than WMI's
    AdapterRAM, which is a 32-bit field and silently reports 4 GB for any
    larger card.
    """
    specs = Specs()
    if _is_windows():
        out = _run_ps(
            "$cs=Get-CimInstance Win32_ComputerSystem;"
            "$cpu=Get-CimInstance Win32_Processor | Select-Object -First 1;"
            "$os=Get-CimInstance Win32_OperatingSystem;"
            "$gpu=Get-CimInstance Win32_VideoController | "
            "Sort-Object AdapterRAM -Descending | Select-Object -First 1;"
            "$vram=0;"
            "Get-ChildItem 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Class\\"
            "{4d36e968-e325-11ce-bfc1-08002be10318}' -ErrorAction SilentlyContinue | "
            "ForEach-Object { $p=Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue;"
            "if ($p.'HardwareInformation.qwMemorySize' -gt $vram) "
            "{ $vram=$p.'HardwareInformation.qwMemorySize' } };"
            "if ($vram -eq 0) { $vram = $gpu.AdapterRAM };"
            "[pscustomobject]@{ cpu=[string]$cpu.Name; cores=[int]$cpu.NumberOfCores;"
            "ramGB=[math]::Round($cs.TotalPhysicalMemory/1GB,1); gpu=[string]$gpu.Name;"
            "vramGB=[math]::Round($vram/1GB,1); os=[string]$os.Caption;"
            "build=[string]$os.BuildNumber; arch=[string]$os.OSArchitecture } "
            "| ConvertTo-Json -Compress"
        )
        entries = _as_list(out)
        if entries:
            data = entries[0]
            specs.cpu = str(data.get("cpu", "")).strip()
            specs.cores = int(data.get("cores") or 0)
            specs.ram_gb = float(data.get("ramGB") or 0)
            specs.gpu = str(data.get("gpu", "")).strip()
            specs.vram_gb = float(data.get("vramGB") or 0)
            specs.os_caption = str(data.get("os", "")).strip()
            specs.os_build = str(data.get("build", "")).strip()
            specs.arch = str(data.get("arch", "")).strip()

    target = target_dir or os.environ.get("SystemDrive", "C:") + "\\"
    try:
        specs.free_disk_gb = round(shutil.disk_usage(target).free / (1024**3), 1)
        specs.disk_target = str(target)
    except OSError:
        pass
    return specs


def check_requirements(required: Dict[str, str], specs: Specs) -> List[Check]:
    """Compare stated requirements against the machine.

    Only genuinely numeric fields get a pass/fail. CPU and GPU requirements are
    model names, and ranking arbitrary part numbers is not something this code
    can do truthfully, so they are marked REQ_MANUAL and shown side by side.
    """
    checks: List[Check] = []

    # --- OS ---------------------------------------------------------------
    os_req = required.get("os") or required.get("os *") or ""
    need_major = _windows_major(os_req)
    have_major = _windows_major(specs.os_caption)
    if not os_req:
        checks.append(Check("OS", "", specs.os_caption, REQ_UNKNOWN))
    elif need_major and have_major:
        checks.append(
            Check(
                "OS",
                os_req,
                specs.os_caption,
                REQ_PASS if have_major >= need_major else REQ_FAIL,
            )
        )
    else:
        checks.append(Check("OS", os_req, specs.os_caption, REQ_MANUAL))

    if "64-bit" in os_req.lower() or "64 bit" in os_req.lower():
        checks.append(
            Check(
                "Architecture",
                "64-bit",
                specs.arch or "unknown",
                REQ_PASS if "64" in specs.arch else REQ_FAIL,
            )
        )

    # --- CPU: reported, not ranked ---------------------------------------
    cpu_req = required.get("processor", "")
    checks.append(
        Check(
            "Processor",
            cpu_req,
            specs.cpu,
            REQ_MANUAL if cpu_req else REQ_UNKNOWN,
            "CPU models can't be ranked automatically -- compare these yourself"
            if cpu_req
            else "",
        )
    )

    # --- RAM --------------------------------------------------------------
    ram_req = required.get("memory", "")
    need_ram = _first_gb(ram_req)
    if need_ram is None:
        checks.append(Check("Memory", ram_req, f"{specs.ram_gb} GB", REQ_UNKNOWN))
    else:
        checks.append(
            Check(
                "Memory",
                f"{need_ram:g} GB",
                f"{specs.ram_gb} GB",
                REQ_PASS if specs.ram_gb + _RAM_TOLERANCE_GB >= need_ram else REQ_FAIL,
            )
        )

    # --- GPU: model reported, VRAM compared when stated -------------------
    gpu_req = required.get("graphics", "")
    checks.append(
        Check(
            "Graphics",
            gpu_req,
            specs.gpu,
            REQ_MANUAL if gpu_req else REQ_UNKNOWN,
            "GPU models can't be ranked automatically -- compare these yourself"
            if gpu_req
            else "",
        )
    )
    need_vram = _first_gb(gpu_req) if gpu_req else None
    if need_vram is not None and specs.vram_gb:
        checks.append(
            Check(
                "VRAM",
                f"{need_vram:g} GB",
                f"{specs.vram_gb} GB",
                REQ_PASS if specs.vram_gb >= need_vram else REQ_FAIL,
                "read from the figure quoted in the graphics requirement",
            )
        )

    # --- Storage ----------------------------------------------------------
    storage_req = required.get("storage", "") or required.get("hard drive", "")
    need_disk = _first_gb(storage_req)
    have_disk = f"{specs.free_disk_gb} GB free on {specs.disk_target}"
    if need_disk is None:
        checks.append(Check("Storage", storage_req, have_disk, REQ_UNKNOWN))
    else:
        checks.append(
            Check(
                "Storage",
                f"{need_disk:g} GB",
                have_disk,
                REQ_PASS if specs.free_disk_gb >= need_disk else REQ_FAIL,
            )
        )

    return checks


# ---------------------------------------------------------------------------
# Install URLs
# ---------------------------------------------------------------------------


def install_url(game: GameRef) -> str:
    """The launcher protocol URL that starts the download.

    None of these can purchase anything: handed a game the user does not own,
    every one of these launchers opens its store page and waits for a human.
    """
    if game.platform == PLATFORM_STEAM:
        return f"steam://install/{game.app_id}"
    if game.platform == PLATFORM_EPIC:
        return (
            "com.epicgames.launcher://apps/"
            + urllib.parse.quote(game.app_id, safe="")
            + "?action=install"
        )
    if game.platform == PLATFORM_UBISOFT:
        return f"uplay://install/{game.app_id}"
    if game.platform == PLATFORM_EA:
        return f"link2ea://launchgame/{game.app_id}"
    return ""


# ---------------------------------------------------------------------------
# install_game
# ---------------------------------------------------------------------------


def _match(title: str, games: List[GameRef]) -> List[GameRef]:
    needle = title.strip().lower()
    if not needle:
        return []
    exact = [g for g in games if g.title.lower() == needle]
    return exact or [g for g in games if needle in g.title.lower()]


@ToolRegistry.register("install_game")
class InstallGameTool(BaseTool):
    """Install a game from Steam, Epic, EA, or Ubisoft Connect."""

    tool_id = "install_game"

    def __init__(self, store: Any = None) -> None:
        self._store = store

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="install_game",
            description=(
                "Install a game from Steam, Epic Games, EA, or Ubisoft Connect. Finds the "
                "game, checks whether it is in the user's library, compares the machine "
                "against the game's system requirements, and queues the download for the "
                "user's approval.\n"
                "The 'status' field gives the outcome:\n"
                "  'already_installed' - nothing to do; it is on the machine already.\n"
                "  'not_owned' - confirmed absent from the library. Tell the user; never "
                "attempt to buy it.\n"
                "  'requirements_not_met' - the machine falls short. Report exactly which "
                "checks failed, then call again with ignore_requirements=true only if the "
                "user says to install anyway.\n"
                "  'ambiguous' - several titles match; ask which, then pass app_id.\n"
                "  'queued' - ready; awaiting the user's approval.\n"
                "  'unavailable' - the platform or title could not be resolved; the message "
                "explains what to do instead.\n"
                "Ownership may come back 'unverified' for platforms with no readable "
                "library. Say so plainly rather than implying the game is owned."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Game title as the user said it, e.g. 'Elden Ring'.",
                    },
                    "platform": {
                        "type": "string",
                        "enum": [PLATFORM_STEAM, PLATFORM_EPIC, PLATFORM_EA, PLATFORM_UBISOFT],
                        "description": "Platform to install from. Omit to search all of them.",
                    },
                    "app_id": {
                        "type": "string",
                        "description": (
                            "Exact platform app id (Steam appid, Epic namespace:catalog:app). "
                            "Set this when resolving an earlier 'ambiguous' result."
                        ),
                    },
                    "ignore_requirements": {
                        "type": "boolean",
                        "description": (
                            "Proceed even though the machine fails a stated requirement. Set "
                            "true ONLY after telling the user which checks failed and hearing "
                            "them agree."
                        ),
                    },
                },
                "required": ["name"],
            },
            category="system",
            # Deliberately NOT requires_confirmation. That flag is enforced in
            # tools/_stubs.py by refusing the call outright whenever there is no
            # interactive confirm callback -- which is always true on the
            # server, so the tool could never run at all. This tool installs
            # nothing by itself: execute() only verifies and queues a TIER_HIGH
            # action, and the install happens post-approval in the executor.
            # The approval queue is the real gate, and a better one, because it
            # shows the human the full verification report before they decide.
            timeout_seconds=180.0,
            required_capabilities=["code:execute", "network:fetch"],
        )

    def _result(self, payload: Dict[str, Any], *, success: bool = True) -> ToolResult:
        return ToolResult(
            tool_name=self.spec.name,
            success=success,
            content=payload.get("message", ""),
            metadata=payload,
        )

    def execute(self, **params: Any) -> ToolResult:
        name = (params.get("name") or "").strip()
        if not name:
            return self._result(
                {"status": "error", "message": "Tell me which game to install."},
                success=False,
            )
        wanted_platform = (params.get("platform") or "").strip().lower()
        app_id = (params.get("app_id") or "").strip()
        ignore_requirements = bool(params.get("ignore_requirements"))

        if not _is_windows():
            return self._result(
                {
                    "status": "unavailable",
                    "message": (
                        f"Game-launcher installs are wired up for Windows only, and this is "
                        f"{platform.system()}. I can still look up '{name}' and its system "
                        "requirements, or use propose_new_tool to build launcher support for "
                        "this platform. Which would you like?"
                    ),
                }
            )

        platforms = detect_platforms()
        available = [p for p, ok in platforms.items() if ok]
        if not available:
            return self._result(
                {
                    "status": "unavailable",
                    "message": (
                        "No game launcher is installed on this machine -- I looked for Steam, "
                        "Epic Games, the EA app, and Ubisoft Connect. Install the one that "
                        f"has '{name}' in its library and ask me again, or tell me which "
                        "platform you use and I'll walk you through setting it up."
                    ),
                    "platforms": platforms,
                }
            )

        # --- already installed? -------------------------------------------
        local = installed_games()
        if wanted_platform:
            local = [g for g in local if g.platform == wanted_platform]
        for game in _match(name, local):
            if not app_id or game.app_id == app_id:
                return self._result(
                    {
                        "status": "already_installed",
                        "game": game.to_dict(),
                        "message": (
                            f"{game.title} is already installed via {game.platform_label}"
                            + (f" at {game.install_dir}" if game.install_dir else "")
                            + ". Want me to launch it instead?"
                        ),
                    }
                )

        # --- resolve ------------------------------------------------------
        target_platform = wanted_platform or PLATFORM_STEAM
        if target_platform != PLATFORM_STEAM:
            return self._result(
                {
                    "status": "unavailable",
                    "message": (
                        f"'{name}' isn't installed, and {_PLATFORM_LABELS[target_platform]} "
                        "publishes no catalogue I can search without signing in -- I can only "
                        "see titles already on this machine. Open its library, and if you "
                        "give me the app id I can queue the install; otherwise starting it "
                        "from the launcher is the quickest route."
                    ),
                }
            )
        if not platforms.get(PLATFORM_STEAM):
            return self._result(
                {
                    "status": "unavailable",
                    "message": (
                        f"Steam isn't installed, so I can't resolve '{name}' there. Installed "
                        f"launchers: {', '.join(_PLATFORM_LABELS[p] for p in available)}. Tell "
                        "me which one owns the game and I'll work from that."
                    ),
                }
            )

        title = name
        if not app_id:
            matches = _steam_search(name)
            if not matches:
                return self._result(
                    {
                        "status": "unavailable",
                        "message": (
                            f"Steam's store has no match for '{name}'. Check the spelling, or "
                            "tell me which platform it's on -- if it's an Epic, EA, or Ubisoft "
                            "title I can work from the app id instead."
                        ),
                    }
                )
            if len(matches) > 1 and matches[0].get("name", "").lower() != name.lower():
                return self._result(
                    {
                        "status": "ambiguous",
                        "message": (
                            f"{len(matches)} Steam titles match '{name}' -- base games and DLC "
                            "look alike here. Ask which one, then call again with its app_id."
                        ),
                        "candidates": [
                            {"app_id": str(m["id"]), "title": m.get("name", "")}
                            for m in matches[:8]
                        ],
                    }
                )
            app_id = str(matches[0]["id"])
            title = matches[0].get("name", name)

        details = _steam_appdetails(app_id)
        if details.get("name"):
            title = details["name"]
        game = GameRef(platform=PLATFORM_STEAM, app_id=app_id, title=title)

        # --- ownership ----------------------------------------------------
        ownership, ownership_note = _steam_owns(app_id)
        report = GameReport(game=game, ownership=ownership, notes=[ownership_note])

        if ownership == OWNED_NOT:
            price = (details.get("price_overview") or {}).get("final_formatted", "")
            return self._result(
                {
                    "status": "not_owned",
                    "game": game.to_dict(),
                    "ownership": ownership,
                    "message": (
                        f"{title} is not in your Steam library, so there's nothing to "
                        "download. I won't buy it for you"
                        + (f" -- the store lists it at {price}" if price else "")
                        + f". Its store page is https://store.steampowered.com/app/{app_id}/ "
                        "if you want to pick it up yourself."
                    ),
                }
            )

        # --- requirements -------------------------------------------------
        root = _steam_root()
        libraries = _steam_libraries(root) if root else []
        target_dir = str(libraries[0]) if libraries else ""
        specs = read_specs(target_dir)
        required = parse_requirements((details.get("pc_requirements") or {}).get("minimum", ""))
        report.specs = specs
        report.requirements_source = "Steam store, minimum spec" if required else ""
        if required:
            report.checks = check_requirements(required, specs)
        else:
            report.notes.append(
                "Steam publishes no machine-readable minimum spec for this title, so the "
                "hardware check was skipped."
            )

        if report.failures and not ignore_requirements:
            payload = report.to_dict()
            payload["status"] = "requirements_not_met"
            payload["failures"] = [c.to_dict() for c in report.failures]
            payload["message"] = (
                f"This machine falls short of {title}'s minimum spec on "
                f"{len(report.failures)} point(s), so nothing has been queued. Tell the user "
                "exactly which, then call again with ignore_requirements=true only if they "
                "want it anyway.\n\n" + report.summary()
            )
            return self._result(payload)

        # --- queue --------------------------------------------------------
        confident = ownership in (OWNED_CONFIRMED, OWNED_INSTALLED)
        store = self._store or get_store()
        shortfall = ""
        if report.failures:
            shortfall = "\n\nPROCEEDING BELOW MINIMUM SPEC. Failing checks:\n" + "\n".join(
                f"  - {c.item}: needs {c.required}, this machine has {c.actual}"
                for c in report.failures
            )
        action = store.queue_action(
            action_type="install_game",
            description=(
                f"Install {title} from {game.platform_label} (app id {app_id})."
                f"\n\n{report.summary()}{shortfall}"
            ),
            payload={
                "platform": game.platform,
                "app_id": app_id,
                "title": title,
                "ownership": ownership,
                "requirements_met": report.meets_requirements,
                "requirements_overridden": bool(report.failures and ignore_requirements),
            },
            permission_key=(
                f"install_game:{game.platform}"
                if confident
                else f"install_game:{game.platform}:unverified"
            ),
            # A confirmed-owned game is a routine re-download and can be
            # remembered per platform; an unverified one always asks.
            tier=TIER_MEDIUM if confident else TIER_HIGH,
        )

        payload = report.to_dict()
        payload["status"] = "queued"
        payload["action_id"] = action.id
        unverified_note = ""
        if ownership == OWNED_UNVERIFIED:
            unverified_note = (
                " I could not confirm you own it; if you don't, Steam will just open the "
                "store page rather than downloading, and it cannot buy anything on its own."
            )
        payload["message"] = (
            f"{title} is ready to install and queued for your approval as action "
            f"{action.id}. Steam will do the downloading once you approve.{unverified_note}"
            "\n\n" + report.summary()
        )
        return self._result(payload)


# ---------------------------------------------------------------------------
# Post-approval executor (dispatched from proactive_tools._run_action)
# ---------------------------------------------------------------------------


def exec_install_game(payload: Dict[str, Any]) -> Tuple[bool, str]:
    """Hand the launcher the install request. Only reached after approval."""
    game = GameRef(
        platform=(payload.get("platform") or "").strip(),
        app_id=(payload.get("app_id") or "").strip(),
        title=(payload.get("title") or "").strip(),
    )
    if not game.platform or not game.app_id:
        return False, "The payload is missing 'platform' or 'app_id'."
    url = install_url(game)
    if not url:
        return False, f"No install URL scheme is known for platform '{game.platform}'."
    if not _is_windows():
        return False, "Game launchers can only be driven on Windows."

    try:
        os.startfile(url)  # noqa: S606 -- a registered launcher protocol, not a shell string
    except OSError as exc:
        return False, f"Could not hand the install to {game.platform_label}: {exc}"

    label = game.title or game.app_id
    note = ""
    if payload.get("requirements_overridden"):
        note = " Note: this machine is below the game's stated minimum spec."
    if payload.get("ownership") == OWNED_UNVERIFIED:
        note += (
            " Ownership was never confirmed, so if it isn't in your library the launcher "
            "will show its store page instead of downloading."
        )
    return True, (
        f"Handed {label} to {game.platform_label}, which is now downloading it. "
        f"Progress shows in the launcher.{note}"
    )


__all__ = [
    "InstallGameTool",
    "GameRef",
    "Specs",
    "Check",
    "GameReport",
    "detect_platforms",
    "installed_games",
    "parse_requirements",
    "check_requirements",
    "read_specs",
    "install_url",
    "exec_install_game",
    "PLATFORM_STEAM",
    "PLATFORM_EPIC",
    "PLATFORM_EA",
    "PLATFORM_UBISOFT",
    "OWNED_INSTALLED",
    "OWNED_CONFIRMED",
    "OWNED_NOT",
    "OWNED_UNVERIFIED",
    "REQ_PASS",
    "REQ_FAIL",
    "REQ_MANUAL",
    "REQ_UNKNOWN",
]
