"""install_app -- resolve, verify, and install a desktop application by name.

Three stages, deliberately separated so nothing is installed on the strength
of the model's own judgement:

1. **Resolve** the spoken name ("install vlc") to an exact package identity
   via the Windows Package Manager. An ambiguous name comes back as a
   candidate list rather than a guess, because picking the wrong one of
   several similarly-named packages is the typosquatting failure mode.
2. **Verify** the actual installer bytes -- download them (winget checks the
   manifest SHA256 while doing so), then check the Authenticode signature and
   run an on-demand Microsoft Defender scan over the file. This is the only
   part of the pipeline that says anything evidence-based about safety.
3. **Approve** -- the install is queued through the existing queue_action /
   execute_pending_actions lifecycle at TIER_HIGH, with the verification
   report embedded in the approval text so the human sees the findings at
   decision time.

On what "safe" can honestly mean here: none of these checks prove an
application is benign. A valid signature proves who published the bytes and
that they were not altered in transit; a clean Defender scan proves only that
nothing matched today's definitions. The report therefore states what was
checked and what each check found, and ``risk_level`` summarises those
findings rather than rendering a verdict.

Risky packages are not blocked. An elevated risk level requires the caller to
come back with ``accept_risks=true`` after relaying the findings -- informed
consent, not a refusal. The human approval gate still applies on top of that,
and because the report travels into the approval description, a model that
sets ``accept_risks`` on its own cannot hide the findings from the person
saying yes.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from orion.core.registry import ToolRegistry
from orion.core.types import ToolResult
from orion.tools._stubs import BaseTool, ToolSpec
from orion.tools.approval_store import TIER_HIGH
from orion.tools.proactive_tools import get_store

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Risk levels
# ---------------------------------------------------------------------------

RISK_CLEAN = "clean"  # every check we could run passed
RISK_CAUTION = "caution"  # nothing alarming, but some evidence was missing
RISK_RISKY = "risky"  # at least one real red flag -- needs accept_risks
RISK_DANGEROUS = "dangerous"  # malware detected, or integrity could not hold

_RISK_ORDER = {RISK_CLEAN: 0, RISK_CAUTION: 1, RISK_RISKY: 2, RISK_DANGEROUS: 3}

# Levels at or above this need explicit, informed risk acceptance before the
# install is even queued for approval.
_ACCEPTANCE_THRESHOLD = RISK_RISKY

# winget's two default sources. `winget` is Microsoft's community repository
# (manifests are PR-reviewed and machine-validated); `msstore` is the Store,
# whose packages go through Store certification. Anything else is a source
# somebody added by hand, carrying no such review.
_TRUSTED_SOURCES = {"winget", "msstore"}

# Multi-part public suffixes common enough to matter for the publisher-vs-
# installer host comparison below.
_TWO_PART_SUFFIXES = {"co", "com", "org", "net", "ac", "gov", "edu"}

_INSTALLER_SUFFIXES = {
    ".exe", ".msi", ".msix", ".appx", ".msixbundle", ".appxbundle", ".zip",
}

_DOWNLOAD_TIMEOUT = 900.0
_SCAN_TIMEOUT = 300.0
_METADATA_TIMEOUT = 120.0


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class Candidate:
    """One package the user's spoken name might have meant."""

    name: str
    package_id: str
    version: str = ""
    source: str = ""

    def to_dict(self) -> Dict[str, str]:
        return {
            "name": self.name,
            "package_id": self.package_id,
            "version": self.version,
            "source": self.source,
        }


@dataclass
class Finding:
    """A single verification observation, good or bad."""

    check: str
    level: str  # one of the RISK_* constants
    detail: str

    def to_dict(self) -> Dict[str, str]:
        return {"check": self.check, "level": self.level, "detail": self.detail}


@dataclass
class Report:
    """The full verification result for one resolved package."""

    candidate: Candidate
    findings: List[Finding] = field(default_factory=list)
    metadata: Dict[str, str] = field(default_factory=dict)
    installer_path: Optional[str] = None

    def add(self, check: str, level: str, detail: str) -> None:
        self.findings.append(Finding(check=check, level=level, detail=detail))

    @property
    def level(self) -> str:
        worst = RISK_CLEAN
        for f in self.findings:
            if _RISK_ORDER.get(f.level, 0) > _RISK_ORDER.get(worst, 0):
                worst = f.level
        return worst

    @property
    def needs_acceptance(self) -> bool:
        return _RISK_ORDER[self.level] >= _RISK_ORDER[_ACCEPTANCE_THRESHOLD]

    def concerns(self) -> List[Finding]:
        return [f for f in self.findings if f.level != RISK_CLEAN]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "package": self.candidate.to_dict(),
            "risk_level": self.level,
            "requires_risk_acceptance": self.needs_acceptance,
            "findings": [f.to_dict() for f in self.findings],
            "publisher": self.metadata.get("publisher", ""),
            "homepage": self.metadata.get("homepage", ""),
            "license": self.metadata.get("license", ""),
            "installer_url": self.metadata.get("installer.installer url", ""),
        }

    def summary(self) -> str:
        """Plain-text report. Also embedded in the approval prompt, so the
        person approving sees the same findings the model saw."""
        c = self.candidate
        lines = [
            f"{c.name}  [{c.package_id}]  version {c.version or 'latest'}"
            f"  (source: {c.source or 'unknown'})"
        ]
        publisher = self.metadata.get("publisher", "")
        if publisher:
            lines.append(f"Publisher: {publisher}")
        url = self.metadata.get("installer.installer url", "")
        if url:
            lines.append(f"Installer: {url}")
        lines.append("")
        lines.append(f"Risk level: {self.level.upper()}")
        lines.append("")
        lines.append("Checks performed:")
        for f in self.findings:
            marker = "ok " if f.level == RISK_CLEAN else "!! "
            lines.append(f"  {marker}{f.check}: {f.detail}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# winget plumbing
# ---------------------------------------------------------------------------


def _is_windows() -> bool:
    return platform.system() == "Windows"


def _winget_path() -> Optional[str]:
    return shutil.which("winget")


def _run(cmd: List[str], timeout: float) -> Tuple[int, str]:
    """Run a command, returning (returncode, combined output).

    Decoding is forced to UTF-8 with replacement: winget and MpCmdRun both
    emit text carrying characters the console codepage cannot round-trip, and
    a UnicodeDecodeError here would masquerade as a verification failure.
    """
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return 124, f"Timed out after {timeout:.0f}s running {' '.join(cmd[:2])}"
    except OSError as exc:
        return 127, str(exc)
    return proc.returncode, f"{proc.stdout}\n{proc.stderr}".strip()


def _parse_table(text: str) -> List[Dict[str, str]]:
    """Parse winget's column-aligned result table.

    Columns are sliced at the offsets of the header words rather than split on
    whitespace: package names legitimately contain spaces ("VLC media player")
    and splitting would shred them across fields.
    """
    lines = [ln.rstrip() for ln in text.splitlines()]
    header_idx = None
    for i in range(len(lines) - 1):
        nxt = lines[i + 1].strip()
        if nxt and set(nxt) == {"-"} and lines[i].strip():
            header_idx = i
            break
    if header_idx is None:
        return []

    header = lines[header_idx]
    cols = [(m.start(), m.group().strip().lower()) for m in re.finditer(r"\S+", header)]
    if not cols:
        return []

    rows: List[Dict[str, str]] = []
    for line in lines[header_idx + 2 :]:
        if not line.strip():
            continue
        row: Dict[str, str] = {}
        for idx, (start, key) in enumerate(cols):
            end = cols[idx + 1][0] if idx + 1 < len(cols) else len(line)
            row[key] = line[start:end].strip()
        if row.get("id"):
            rows.append(row)
    return rows


def _parse_show(text: str) -> Dict[str, str]:
    """Flatten ``winget show`` output into a key -> value map.

    Nested blocks (notably ``Installer:``) are namespaced with a dotted prefix,
    so ``Installer Url`` inside ``Installer:`` becomes
    ``installer.installer url``.
    """
    fields: Dict[str, str] = {}
    section = ""
    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        indent = len(line) - len(line.lstrip())
        if stripped.endswith(":") and stripped.count(":") == 1:
            if indent == 0:
                section = stripped[:-1].strip().lower()
            continue
        if ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        key = key.strip().lower()
        value = value.strip()
        if not key or not value:
            continue
        if indent == 0:
            section = ""
            fields[key] = value
        elif section:
            fields.setdefault(f"{section}.{key}", value)
    return fields


_FOUND_RE = re.compile(r"^Found\s+(?P<name>.+?)\s*\[(?P<id>[^\]]+)\]\s*$", re.MULTILINE)


def _winget_search(query: str) -> List[Candidate]:
    code, out = _run(
        [
            "winget", "search", "--name", query,
            "--disable-interactivity", "--accept-source-agreements",
        ],
        _METADATA_TIMEOUT,
    )
    rows = _parse_table(out) if out else []
    if not rows:
        # `--name` misses packages whose moniker or id matches but whose
        # display name does not, so retry as a free-text query.
        _code2, out2 = _run(
            [
                "winget", "search", query,
                "--disable-interactivity", "--accept-source-agreements",
            ],
            _METADATA_TIMEOUT,
        )
        rows = _parse_table(out2) if out2 else []
    if not rows and code == 124:
        logger.warning("winget search timed out for %r", query)
    return [
        Candidate(
            name=r.get("name", ""),
            package_id=r.get("id", ""),
            version=r.get("version", ""),
            source=r.get("source", ""),
        )
        for r in rows
        if r.get("id")
    ]


def _winget_show(
    package_id: str, source: str = ""
) -> Tuple[Optional[Candidate], Dict[str, str]]:
    cmd = [
        "winget", "show", "--id", package_id, "--exact",
        "--disable-interactivity", "--accept-source-agreements",
    ]
    if source:
        cmd += ["--source", source]
    code, out = _run(cmd, _METADATA_TIMEOUT)
    if code != 0:
        return None, {}
    fields = _parse_show(out)
    match = _FOUND_RE.search(out)
    candidate = Candidate(
        name=match.group("name").strip() if match else package_id,
        package_id=match.group("id").strip() if match else package_id,
        version=fields.get("version", ""),
        source=source,
    )
    return candidate, fields


# ---------------------------------------------------------------------------
# Evidence gathering
# ---------------------------------------------------------------------------


def _host(url: str) -> str:
    match = re.match(r"^https?://([^/]+)", (url or "").strip(), re.IGNORECASE)
    return match.group(1).lower().split(":")[0] if match else ""


def _registrable(host: str) -> str:
    """Crude eTLD+1. Good enough to *flag* a publisher/installer host mismatch
    for human review; nothing decides automatically on it."""
    parts = [p for p in host.split(".") if p]
    if len(parts) < 2:
        return host
    if len(parts) >= 3 and parts[-2] in _TWO_PART_SUFFIXES and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _ps_quote(value: str) -> str:
    return value.replace("'", "''")


def _authenticode(path: Path) -> Dict[str, str]:
    """Authenticode status and signer for a downloaded installer."""
    script = (
        "$ErrorActionPreference='Stop';"
        f"$s = Get-AuthenticodeSignature -LiteralPath '{_ps_quote(str(path))}';"
        "$o = [ordered]@{status=[string]$s.Status;"
        "message=[string]$s.StatusMessage;signer='';issuer=''};"
        "if ($s.SignerCertificate) {"
        "$o.signer=[string]$s.SignerCertificate.Subject;"
        "$o.issuer=[string]$s.SignerCertificate.Issuer};"
        "$o | ConvertTo-Json -Compress"
    )
    code, out = _run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        _METADATA_TIMEOUT,
    )
    if code != 0:
        return {"status": "CheckFailed", "message": out[:300]}
    try:
        return json.loads(out[out.index("{") : out.rindex("}") + 1])
    except (ValueError, json.JSONDecodeError):
        return {"status": "CheckFailed", "message": out[:300]}


def _mpcmdrun() -> Optional[str]:
    """Newest Defender platform build, falling back to the stable path."""
    root = (
        Path(os.environ.get("ProgramData", r"C:\ProgramData"))
        / "Microsoft" / "Windows Defender" / "Platform"
    )
    if root.is_dir():
        builds = sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.name)
        for build in reversed(builds):
            exe = build / "MpCmdRun.exe"
            if exe.exists():
                return str(exe)
    fallback = (
        Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        / "Windows Defender" / "MpCmdRun.exe"
    )
    return str(fallback) if fallback.exists() else None


def _defender_scan(path: Path) -> Tuple[str, str]:
    """Scan one file on demand. Returns (verdict, detail).

    Verdicts are ``clean`` | ``threat`` | ``unavailable``. Remediation is
    disabled so a detection is reported to the user rather than quarantined
    out from under the report we are about to show them.
    """
    exe = _mpcmdrun()
    if not exe:
        return "unavailable", "Microsoft Defender's command-line scanner was not found."
    code, out = _run(
        [exe, "-Scan", "-ScanType", "3", "-File", str(path), "-DisableRemediation"],
        _SCAN_TIMEOUT,
    )
    if code == 0:
        return "clean", "Microsoft Defender found no threats in the installer."
    if code == 2:
        return "threat", f"Microsoft Defender flagged this file. {out[:400]}"
    return "unavailable", f"The Defender scan did not complete (exit {code}). {out[:300]}"


def _download_installer(
    package_id: str, version: str, source: str, dest: Path
) -> Tuple[bool, str, Optional[Path]]:
    """Download the installer so it can be signature-checked and scanned.

    ``--ignore-security-hash`` is deliberately never passed: winget verifies
    the downloaded bytes against the manifest's published SHA256, and a
    mismatch has to surface as a failure rather than be waved through.
    """
    cmd = [
        "winget", "download", "--id", package_id, "--exact",
        "--download-directory", str(dest),
        "--disable-interactivity", "--accept-source-agreements",
        "--accept-package-agreements", "--skip-dependencies",
    ]
    if version:
        cmd += ["--version", version]
    if source:
        cmd += ["--source", source]

    code, out = _run(cmd, _DOWNLOAD_TIMEOUT)
    if code != 0:
        return False, out[:500], None
    installers = [
        p
        for p in dest.rglob("*")
        if p.is_file() and p.suffix.lower() in _INSTALLER_SUFFIXES
    ]
    if not installers:
        return False, "winget reported success but produced no installer file.", None
    return True, out[:500], max(installers, key=lambda p: p.stat().st_size)


# ---------------------------------------------------------------------------
# Risk assessment
# ---------------------------------------------------------------------------


def assess_package(
    candidate: Candidate,
    fields: Dict[str, str],
    requested_name: str,
    *,
    verify_bytes: bool = True,
) -> Report:
    """Build the verification report for one resolved package."""
    report = Report(candidate=candidate, metadata=dict(fields))

    # --- provenance -------------------------------------------------------
    source = (candidate.source or "").lower()
    if source in _TRUSTED_SOURCES:
        report.add(
            "source",
            RISK_CLEAN,
            f"Comes from the '{source}' repository, whose manifests are reviewed by Microsoft.",
        )
    elif not source:
        report.add("source", RISK_CAUTION, "The package source could not be determined.")
    else:
        report.add(
            "source",
            RISK_RISKY,
            f"Comes from '{source}', a non-default source carrying no Microsoft review.",
        )

    # --- name match: the typosquatting signal -----------------------------
    asked = requested_name.strip().lower()
    display = (candidate.name or "").lower()
    moniker = (fields.get("moniker", "") or "").lower()
    tail = (candidate.package_id or "").lower().split(".")[-1]
    if asked and asked in {display, moniker, tail}:
        report.add("name match", RISK_CLEAN, f"'{requested_name}' matches this package exactly.")
    elif asked and asked in display:
        report.add(
            "name match",
            RISK_CAUTION,
            f"'{requested_name}' is a partial match for '{candidate.name}'. Worth confirming "
            "this is the one you meant.",
        )
    else:
        report.add(
            "name match",
            RISK_CAUTION,
            f"You asked for '{requested_name}' but this package is '{candidate.name}'. "
            "Loosely-matching names are how look-alike packages get installed.",
        )

    # --- publisher --------------------------------------------------------
    publisher = fields.get("publisher", "")
    if publisher:
        report.add("publisher", RISK_CLEAN, f"Published by {publisher}.")
    else:
        report.add("publisher", RISK_CAUTION, "The manifest names no publisher.")

    # --- installer origin -------------------------------------------------
    installer_url = fields.get("installer.installer url", "")
    if not installer_url:
        report.add("installer url", RISK_CAUTION, "The manifest publishes no installer URL.")
    elif not installer_url.lower().startswith("https://"):
        report.add(
            "installer url",
            RISK_RISKY,
            f"The installer is served over plain HTTP ({installer_url}), so it can be "
            "tampered with in transit.",
        )
    else:
        installer_host = _host(installer_url)
        publisher_host = _host(fields.get("publisher url", "") or fields.get("homepage", ""))
        if publisher_host and _registrable(installer_host) != _registrable(publisher_host):
            report.add(
                "installer url",
                RISK_CAUTION,
                f"The installer is hosted on {installer_host}, a different domain from the "
                f"publisher's site ({publisher_host}). Normal for CDNs and code forges, "
                "but worth a look.",
            )
        else:
            report.add(
                "installer url",
                RISK_CLEAN,
                f"The installer is served over HTTPS from {installer_host}.",
            )

    if fields.get("installer.installer sha256"):
        report.add(
            "manifest hash",
            RISK_CLEAN,
            "The manifest publishes a SHA256 for the installer, so the download is "
            "integrity-checked against it.",
        )
    else:
        report.add(
            "manifest hash",
            RISK_CAUTION,
            "The manifest publishes no installer SHA256, so the download cannot be "
            "integrity-checked.",
        )

    # --- release channel --------------------------------------------------
    haystack = f"{candidate.name} {candidate.package_id} {candidate.version}".lower()
    if any(word in haystack for word in ("nightly", "beta", "alpha", "preview", "insider")):
        report.add(
            "release channel",
            RISK_CAUTION,
            "This is a pre-release build, less tested than the stable channel.",
        )

    if not verify_bytes:
        report.add(
            "installer bytes",
            RISK_CAUTION,
            "The installer was not downloaded, so its signature was not checked and it was "
            "not scanned for malware. Only manifest metadata was reviewed.",
        )
        return report

    # --- the evidence-based checks ----------------------------------------
    tmpdir = Path(tempfile.mkdtemp(prefix="orion-install-"))
    ok, detail, installer = _download_installer(
        candidate.package_id, candidate.version, candidate.source, tmpdir
    )
    if not ok or installer is None:
        report.add(
            "installer bytes",
            RISK_RISKY,
            "The installer could not be downloaded for inspection, so it was neither "
            f"signature-checked nor malware-scanned: {detail}",
        )
        return report

    report.installer_path = str(installer)
    report.add(
        "download integrity",
        RISK_CLEAN,
        f"Downloaded {installer.name} ({installer.stat().st_size // 1024} KB); winget "
        "verified it against the manifest's published hash.",
    )

    signature = _authenticode(installer)
    status = (signature.get("status") or "").lower()
    signer = signature.get("signer", "")
    if status == "valid":
        report.add(
            "code signature",
            RISK_CLEAN,
            f"Validly signed by {signer or 'an unnamed signer'}.",
        )
    elif status == "notsigned":
        report.add(
            "code signature",
            RISK_RISKY,
            "The installer carries no code signature, so there is no cryptographic proof "
            "of who produced it or that it arrived unaltered.",
        )
    elif status == "checkfailed":
        report.add(
            "code signature",
            RISK_CAUTION,
            f"The signature check could not be completed: {signature.get('message', '')[:200]}",
        )
    else:
        report.add(
            "code signature",
            RISK_RISKY,
            f"Signature status is '{signature.get('status')}' -- "
            f"{signature.get('message', '')[:200]}",
        )

    verdict, scan_detail = _defender_scan(installer)
    if verdict == "clean":
        report.add("malware scan", RISK_CLEAN, scan_detail)
    elif verdict == "threat":
        report.add("malware scan", RISK_DANGEROUS, scan_detail)
    else:
        report.add("malware scan", RISK_CAUTION, scan_detail)

    return report


# ---------------------------------------------------------------------------
# install_app
# ---------------------------------------------------------------------------


def _no_winget_guidance(name: str) -> str:
    """Never a dead end -- always hand back a route forward."""
    if not _is_windows():
        return (
            f"Automated installation of '{name}' is not wired up for "
            f"{platform.system()} yet -- install_app drives the Windows Package "
            "Manager. Two ways forward: I can look up the correct install command "
            "for this platform and put it through shell_exec for you to approve, or "
            "use propose_new_tool to build a proper package-manager tool for this OS "
            "so it works natively from here on."
        )
    return (
        f"The Windows Package Manager (winget) is not available, so I cannot resolve "
        f"and verify '{name}' automatically. Options: install 'App Installer' from the "
        "Microsoft Store to enable winget, or I can find the vendor's official "
        "download, verify its signature before anything runs, and walk you through it. "
        "Say which you prefer."
    )


@ToolRegistry.register("install_app")
class InstallAppTool(BaseTool):
    """Resolve, verify, and queue installation of a desktop application."""

    tool_id = "install_app"

    def __init__(self, store: Any = None) -> None:
        self._store = store

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="install_app",
            description=(
                "Install a desktop application by name. Resolves the name to an exact "
                "package, downloads the installer, verifies its code signature, scans it "
                "with Microsoft Defender, then queues the install for the user's approval.\n"
                "The 'status' field gives one of four outcomes:\n"
                "  'ambiguous' - several packages match; show the candidate list, ask which "
                "one, then call again with package_id set.\n"
                "  'needs_risk_acceptance' - verification found real concerns. Relay every "
                "item in 'concerns' to the user in plain language, then call again with "
                "accept_risks=true only if they explicitly accept those risks.\n"
                "  'queued' - verification passed; the install now awaits the user's approval.\n"
                "  'unavailable' - no package manager; the message explains the alternatives.\n"
                "Never set accept_risks=true on your own initiative: it asserts that the user "
                "was told the specific risks and agreed to them."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": (
                            "Application name as the user said it, e.g. 'vlc', 'notepad++'."
                        ),
                    },
                    "package_id": {
                        "type": "string",
                        "description": (
                            "Exact package id, e.g. 'VideoLAN.VLC'. Set this when resolving "
                            "an earlier 'ambiguous' result."
                        ),
                    },
                    "source": {
                        "type": "string",
                        "description": "Package source, e.g. 'winget' or 'msstore'. Usually omitted.",
                    },
                    "version": {
                        "type": "string",
                        "description": "Specific version to install. Defaults to the latest.",
                    },
                    "accept_risks": {
                        "type": "boolean",
                        "description": (
                            "Set true ONLY after the user has been shown the specific risk "
                            "findings and has explicitly agreed to proceed anyway."
                        ),
                    },
                    "skip_deep_verification": {
                        "type": "boolean",
                        "description": (
                            "Skip downloading the installer for signature and malware checks. "
                            "Faster, but the result is metadata-only and is reported as such. "
                            "Defaults to false."
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
            timeout_seconds=1200.0,
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
                {"status": "error", "message": "Tell me which application to install."},
                success=False,
            )

        package_id = (params.get("package_id") or "").strip()
        source = (params.get("source") or "").strip()
        version = (params.get("version") or "").strip()
        accept_risks = bool(params.get("accept_risks"))
        verify_bytes = not bool(params.get("skip_deep_verification"))

        if not _is_windows() or not _winget_path():
            return self._result(
                {"status": "unavailable", "message": _no_winget_guidance(name)}
            )

        # --- resolve ------------------------------------------------------
        if not package_id:
            candidates = _winget_search(name)
            if not candidates:
                return self._result(
                    {
                        "status": "unavailable",
                        "message": (
                            f"No package matching '{name}' exists in the configured winget "
                            "sources. That usually means it ships as a direct download rather "
                            "than through a package manager. I can find the vendor's official "
                            "installer and verify its signature before anything runs, or -- if "
                            "you install this kind of thing often -- use propose_new_tool to "
                            "build a dedicated installer tool for it. Which would you like?"
                        ),
                    }
                )
            exact = [
                c
                for c in candidates
                if name.lower() in {c.name.lower(), c.package_id.lower().split(".")[-1]}
            ]
            if len(candidates) > 1 and len(exact) != 1:
                return self._result(
                    {
                        "status": "ambiguous",
                        "message": (
                            f"{len(candidates)} packages match '{name}'. Ask the user which "
                            "one they meant, then call install_app again with that package_id."
                        ),
                        "candidates": [c.to_dict() for c in candidates[:10]],
                    }
                )
            chosen = exact[0] if len(exact) == 1 else candidates[0]
            package_id = chosen.package_id
            source = source or chosen.source

        detailed, fields = _winget_show(package_id, source)
        if detailed is None:
            return self._result(
                {
                    "status": "unavailable",
                    "message": (
                        f"'{package_id}' did not resolve to a package whose manifest I can "
                        "read. Let me re-run the search by name so we can pick from the real "
                        "candidate list."
                    ),
                }
            )
        detailed.source = source or detailed.source
        if version:
            detailed.version = version

        # --- verify -------------------------------------------------------
        report = assess_package(detailed, fields, name, verify_bytes=verify_bytes)
        payload = report.to_dict()
        payload["report"] = report.summary()

        # --- informed-consent gate ----------------------------------------
        if report.needs_acceptance and not accept_risks:
            payload["status"] = "needs_risk_acceptance"
            payload["concerns"] = [f.to_dict() for f in report.concerns()]
            payload["message"] = (
                f"Verification of {detailed.name} came back {report.level.upper()}. Nothing "
                "has been installed or queued. Tell the user exactly what was found, then "
                "call install_app again with accept_risks=true only if they say to proceed "
                "anyway.\n\n" + report.summary()
            )
            return self._result(payload)

        # --- queue for human approval -------------------------------------
        store = self._store or get_store()
        risk_banner = ""
        if report.needs_acceptance:
            risk_banner = (
                f"\n\nRISKS ACCEPTED: this install was flagged {report.level.upper()} and is "
                "proceeding on explicitly accepted risk. Concerns found:\n"
                + "\n".join(f"  - {f.check}: {f.detail}" for f in report.concerns())
            )
        action = store.queue_action(
            action_type="install_app",
            description=(
                f"Install {detailed.name} ({detailed.package_id}) version "
                f"{detailed.version or 'latest'} from {detailed.source or 'winget'}."
                f"\n\n{report.summary()}{risk_banner}"
            ),
            payload={
                "package_id": detailed.package_id,
                "name": detailed.name,
                "version": detailed.version,
                "source": detailed.source,
                "risk_level": report.level,
                "risks_accepted": bool(accept_risks and report.needs_acceptance),
                "concerns": [f.to_dict() for f in report.concerns()],
            },
            permission_key=f"install_app:{detailed.package_id}",
            tier=TIER_HIGH,
        )
        payload["status"] = "queued"
        payload["action_id"] = action.id
        payload["message"] = (
            f"{detailed.name} verified ({report.level.upper()}) and queued for your approval "
            f"as action {action.id}. Nothing is installed until you approve it.\n\n"
            + report.summary()
        )
        return self._result(payload)


# ---------------------------------------------------------------------------
# Post-approval executor (dispatched from proactive_tools._run_action)
# ---------------------------------------------------------------------------


def exec_install_app(payload: Dict[str, Any]) -> Tuple[bool, str]:
    """Actually install the package. Only reached after a human approval.

    winget re-fetches the installer here rather than reusing the copy verified
    earlier, and checks it against the same pinned manifest hash -- so the
    bytes that run are the bytes that were inspected.
    """
    package_id = (payload.get("package_id") or "").strip()
    if not package_id:
        return False, "The payload is missing 'package_id'."
    if not _is_windows() or not _winget_path():
        return False, "winget is not available on this machine, so the install cannot run."

    cmd = [
        "winget", "install", "--id", package_id, "--exact",
        "--disable-interactivity", "--accept-source-agreements",
        "--accept-package-agreements",
    ]
    version = (payload.get("version") or "").strip()
    if version:
        cmd += ["--version", version]
    source = (payload.get("source") or "").strip()
    if source:
        cmd += ["--source", source]

    code, out = _run(cmd, _DOWNLOAD_TIMEOUT)
    name = payload.get("name") or package_id
    note = ""
    if payload.get("risks_accepted"):
        note = f" (installed on accepted risk; verification was {payload.get('risk_level')})"
    if code == 0:
        return True, f"Installed {name}{note}."
    lines = [ln for ln in out.strip().splitlines() if ln.strip()]
    detail = lines[-1] if lines else f"exit code {code}"
    return False, f"Installing {name} failed: {detail}"


__all__ = [
    "InstallAppTool",
    "Candidate",
    "Finding",
    "Report",
    "assess_package",
    "exec_install_app",
    "RISK_CLEAN",
    "RISK_CAUTION",
    "RISK_RISKY",
    "RISK_DANGEROUS",
]
