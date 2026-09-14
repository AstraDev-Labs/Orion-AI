"""Tests for install_app -- resolution, risk assessment, and the consent gate.

The winget helpers are monkeypatched throughout: these tests are about the
decision logic (what gets flagged, what needs acceptance, what reaches the
approval queue), not about winget's own behaviour.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from orion.tools import app_install as ai
from orion.tools.app_install import (
    RISK_CAUTION,
    RISK_CLEAN,
    RISK_DANGEROUS,
    RISK_RISKY,
    Candidate,
    InstallAppTool,
    Report,
    assess_package,
    exec_install_app,
)
from orion.tools.approval_store import TIER_HIGH, ApprovalStore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SEARCH_OUTPUT = """Name                       Id                         Version                 Source
--------------------------------------------------------------------------------------
VLC                        XPDM1ZW6815MQM             Unknown                 msstore
Jellyfin VLC Bridge        CrySer66.JellyfinVlcBridge 1.18.0                  winget
VLC media player           VideoLAN.VLC               3.0.23                  winget
"""

SHOW_OUTPUT = """Found VLC media player [VideoLAN.VLC]
Version: 3.0.23
Publisher: VideoLAN
Publisher Url: https://www.videolan.org/
Moniker: vlc
Description:
  VLC is a free and open source cross-platform multimedia player.
Homepage: https://www.videolan.org/vlc/
License: GPL-2.0
Installer:
  Installer Type: wix
  Installer Url: https://download.videolan.org/pub/videolan/vlc/3.0.23/win64/vlc.msi
  Installer SHA256: bc4b902a480b98a4a5479327a7f210f06369a59bf727649e320faba5b4ef1f5e
"""

CLEAN_FIELDS = {
    "publisher": "VideoLAN",
    "publisher url": "https://www.videolan.org/",
    "homepage": "https://www.videolan.org/vlc/",
    "moniker": "vlc",
    "installer.installer url": "https://download.videolan.org/pub/vlc.msi",
    "installer.installer sha256": "bc4b902a480b98a4",
}

VLC = Candidate(name="VLC media player", package_id="VideoLAN.VLC", version="3.0.23", source="winget")


@pytest.fixture
def store() -> ApprovalStore:
    return ApprovalStore(str(Path(tempfile.mkdtemp()) / "approvals.db"))


@pytest.fixture
def on_windows(monkeypatch):
    """Pretend winget is present, so tests run identically on any platform."""
    monkeypatch.setattr(ai, "_is_windows", lambda: True)
    monkeypatch.setattr(ai, "_winget_path", lambda: r"C:\winget.exe")


# ---------------------------------------------------------------------------
# Output parsing
# ---------------------------------------------------------------------------


def test_parse_table_keeps_names_containing_spaces():
    rows = ai._parse_table(SEARCH_OUTPUT)
    names = [r["name"] for r in rows]
    assert "VLC media player" in names
    assert "Jellyfin VLC Bridge" in names


def test_parse_table_maps_every_column():
    rows = ai._parse_table(SEARCH_OUTPUT)
    row = next(r for r in rows if r["id"] == "VideoLAN.VLC")
    assert row["version"] == "3.0.23"
    assert row["source"] == "winget"


def test_parse_table_on_no_results_is_empty():
    assert ai._parse_table("No package found matching input criteria.") == []


def test_parse_show_reads_top_level_and_nested_fields():
    fields = ai._parse_show(SHOW_OUTPUT)
    assert fields["publisher"] == "VideoLAN"
    assert fields["version"] == "3.0.23"
    assert fields["installer.installer url"].endswith("vlc.msi")
    assert fields["installer.installer sha256"].startswith("bc4b902a")


def test_parse_show_keeps_urls_intact():
    """The value is split on the first colon only -- 'https://' must survive."""
    fields = ai._parse_show(SHOW_OUTPUT)
    assert fields["publisher url"] == "https://www.videolan.org/"


def test_registrable_domain():
    assert ai._registrable("download.videolan.org") == "videolan.org"
    assert ai._registrable("www.example.co.uk") == "example.co.uk"
    assert ai._host("https://download.videolan.org/pub/x.msi") == "download.videolan.org"


# ---------------------------------------------------------------------------
# Risk assessment
# ---------------------------------------------------------------------------


def test_trusted_source_and_matching_publisher_is_clean():
    report = assess_package(VLC, CLEAN_FIELDS, "vlc", verify_bytes=False)
    by_check = {f.check: f for f in report.findings}
    assert by_check["source"].level == RISK_CLEAN
    assert by_check["name match"].level == RISK_CLEAN
    assert by_check["installer url"].level == RISK_CLEAN
    assert by_check["manifest hash"].level == RISK_CLEAN


def test_untrusted_source_is_risky():
    candidate = Candidate(name="Thing", package_id="X.Thing", version="1", source="randomrepo")
    report = assess_package(candidate, CLEAN_FIELDS, "thing", verify_bytes=False)
    source = next(f for f in report.findings if f.check == "source")
    assert source.level == RISK_RISKY
    assert report.needs_acceptance


def test_plain_http_installer_is_risky():
    fields = dict(CLEAN_FIELDS, **{"installer.installer url": "http://cdn.example.com/x.exe"})
    report = assess_package(VLC, fields, "vlc", verify_bytes=False)
    finding = next(f for f in report.findings if f.check == "installer url")
    assert finding.level == RISK_RISKY
    assert report.needs_acceptance


def test_host_mismatch_is_flagged_but_not_blocking():
    fields = dict(CLEAN_FIELDS, **{"installer.installer url": "https://files.cdn77.net/x.msi"})
    report = assess_package(VLC, fields, "vlc", verify_bytes=False)
    finding = next(f for f in report.findings if f.check == "installer url")
    assert finding.level == RISK_CAUTION
    assert not report.needs_acceptance


def test_loose_name_match_is_flagged_as_typosquat_risk():
    candidate = Candidate(name="VLC Player Pro Free", package_id="Some.Other", source="winget")
    report = assess_package(candidate, {"publisher": "Someone"}, "vlc", verify_bytes=False)
    finding = next(f for f in report.findings if f.check == "name match")
    assert finding.level == RISK_CAUTION


def test_missing_manifest_hash_is_flagged():
    fields = {k: v for k, v in CLEAN_FIELDS.items() if k != "installer.installer sha256"}
    report = assess_package(VLC, fields, "vlc", verify_bytes=False)
    finding = next(f for f in report.findings if f.check == "manifest hash")
    assert finding.level == RISK_CAUTION


def test_prerelease_channel_is_flagged():
    candidate = Candidate(
        name="VLC media player (Nightly)",
        package_id="VideoLAN.VLC.Nightly",
        version="4.0.0-nightly",
        source="winget",
    )
    report = assess_package(candidate, CLEAN_FIELDS, "vlc", verify_bytes=False)
    assert any(f.check == "release channel" for f in report.findings)


def test_skipping_deep_verification_is_reported_not_hidden():
    report = assess_package(VLC, CLEAN_FIELDS, "vlc", verify_bytes=False)
    finding = next(f for f in report.findings if f.check == "installer bytes")
    assert finding.level == RISK_CAUTION
    assert "not scanned for malware" in finding.detail


def test_report_level_is_the_worst_finding():
    report = Report(candidate=VLC)
    report.add("a", RISK_CLEAN, "fine")
    report.add("b", RISK_CAUTION, "hmm")
    assert report.level == RISK_CAUTION
    report.add("c", RISK_DANGEROUS, "malware")
    assert report.level == RISK_DANGEROUS
    assert report.needs_acceptance


def test_undownloadable_installer_is_risky(monkeypatch):
    monkeypatch.setattr(
        ai, "_download_installer", lambda *a, **k: (False, "404 not found", None)
    )
    report = assess_package(VLC, CLEAN_FIELDS, "vlc", verify_bytes=True)
    finding = next(f for f in report.findings if f.check == "installer bytes")
    assert finding.level == RISK_RISKY
    assert report.needs_acceptance


def test_unsigned_installer_is_risky(monkeypatch, tmp_path):
    fake = tmp_path / "setup.exe"
    fake.write_bytes(b"x" * 2048)
    monkeypatch.setattr(ai, "_download_installer", lambda *a, **k: (True, "", fake))
    monkeypatch.setattr(ai, "_authenticode", lambda p: {"status": "NotSigned", "message": ""})
    monkeypatch.setattr(ai, "_defender_scan", lambda p: ("clean", "no threats"))
    report = assess_package(VLC, CLEAN_FIELDS, "vlc", verify_bytes=True)
    finding = next(f for f in report.findings if f.check == "code signature")
    assert finding.level == RISK_RISKY


def test_defender_detection_is_dangerous(monkeypatch, tmp_path):
    fake = tmp_path / "setup.exe"
    fake.write_bytes(b"x" * 2048)
    monkeypatch.setattr(ai, "_download_installer", lambda *a, **k: (True, "", fake))
    monkeypatch.setattr(
        ai, "_authenticode", lambda p: {"status": "Valid", "signer": "CN=Someone"}
    )
    monkeypatch.setattr(ai, "_defender_scan", lambda p: ("threat", "Trojan:Win32/Test"))
    report = assess_package(VLC, CLEAN_FIELDS, "vlc", verify_bytes=True)
    assert report.level == RISK_DANGEROUS
    assert report.needs_acceptance


# ---------------------------------------------------------------------------
# The consent gate
# ---------------------------------------------------------------------------


def _patch_resolution(monkeypatch, candidate: Candidate, fields: dict):
    monkeypatch.setattr(ai, "_winget_search", lambda q: [candidate])
    monkeypatch.setattr(ai, "_winget_show", lambda pid, src="": (candidate, fields))


def test_clean_package_is_queued_for_approval(monkeypatch, on_windows, store):
    _patch_resolution(monkeypatch, VLC, CLEAN_FIELDS)
    result = InstallAppTool(store=store).execute(name="vlc", skip_deep_verification=True)
    assert result.metadata["status"] == "queued"
    pending = store.list_pending()
    assert len(pending) == 1
    assert pending[0].action_type == "install_app"
    assert pending[0].tier == TIER_HIGH


def test_risky_package_is_not_queued_without_acceptance(monkeypatch, on_windows, store):
    risky = Candidate(name="Thing", package_id="X.Thing", version="1", source="sketchy")
    _patch_resolution(monkeypatch, risky, CLEAN_FIELDS)
    result = InstallAppTool(store=store).execute(name="thing", skip_deep_verification=True)
    assert result.metadata["status"] == "needs_risk_acceptance"
    assert result.metadata["concerns"]
    assert store.list_pending() == []


def test_risky_package_is_queued_once_risks_are_accepted(monkeypatch, on_windows, store):
    risky = Candidate(name="Thing", package_id="X.Thing", version="1", source="sketchy")
    _patch_resolution(monkeypatch, risky, CLEAN_FIELDS)
    result = InstallAppTool(store=store).execute(
        name="thing", accept_risks=True, skip_deep_verification=True
    )
    assert result.metadata["status"] == "queued"
    assert store.list_pending()[0].payload["risks_accepted"] is True


def test_accepted_risks_still_reach_the_human_approving(monkeypatch, on_windows, store):
    """A model setting accept_risks cannot hide the findings: they are carried
    into the approval description the person actually reads."""
    risky = Candidate(name="Thing", package_id="X.Thing", version="1", source="sketchy")
    _patch_resolution(monkeypatch, risky, CLEAN_FIELDS)
    InstallAppTool(store=store).execute(
        name="thing", accept_risks=True, skip_deep_verification=True
    )
    description = store.list_pending()[0].description
    assert "RISKS ACCEPTED" in description
    assert "non-default source" in description


def test_ambiguous_name_asks_instead_of_guessing(monkeypatch, on_windows, store):
    others = [
        Candidate(name="VLC", package_id="XPDM1ZW6815MQM", source="msstore"),
        Candidate(name="VLC media player", package_id="VideoLAN.VLC", source="winget"),
    ]
    monkeypatch.setattr(ai, "_winget_search", lambda q: others)
    result = InstallAppTool(store=store).execute(name="vlc")
    assert result.metadata["status"] == "ambiguous"
    assert len(result.metadata["candidates"]) == 2
    assert store.list_pending() == []


# ---------------------------------------------------------------------------
# Never a dead end
# ---------------------------------------------------------------------------


def test_missing_winget_offers_a_route_forward(monkeypatch, store):
    monkeypatch.setattr(ai, "_winget_path", lambda: None)
    result = InstallAppTool(store=store).execute(name="vlc")
    assert result.metadata["status"] == "unavailable"
    message = result.content.lower()
    assert "not found" not in message
    assert "propose_new_tool" in message or "app installer" in message


def test_unknown_package_offers_a_route_forward(monkeypatch, on_windows, store):
    monkeypatch.setattr(ai, "_winget_search", lambda q: [])
    result = InstallAppTool(store=store).execute(name="zzznotreal")
    assert result.metadata["status"] == "unavailable"
    assert "propose_new_tool" in result.content


def test_empty_name_is_rejected(store):
    result = InstallAppTool(store=store).execute(name="  ")
    assert result.success is False


# ---------------------------------------------------------------------------
# Post-approval executor
# ---------------------------------------------------------------------------


def test_executor_rejects_payload_without_package_id():
    ok, message = exec_install_app({})
    assert ok is False
    assert "package_id" in message


def test_executor_pins_the_verified_version(monkeypatch, on_windows):
    captured = {}

    def fake_run(cmd, timeout):
        captured["cmd"] = cmd
        return 0, "Successfully installed"

    monkeypatch.setattr(ai, "_run", fake_run)
    ok, message = exec_install_app(
        {"package_id": "VideoLAN.VLC", "name": "VLC", "version": "3.0.23", "source": "winget"}
    )
    assert ok is True
    assert "--version" in captured["cmd"]
    assert "3.0.23" in captured["cmd"]
    # never waive the hash check
    assert "--ignore-security-hash" not in captured["cmd"]


def test_executor_notes_when_risks_were_accepted(monkeypatch, on_windows):
    monkeypatch.setattr(ai, "_run", lambda cmd, timeout: (0, "ok"))
    ok, message = exec_install_app(
        {
            "package_id": "X.Thing",
            "name": "Thing",
            "risks_accepted": True,
            "risk_level": RISK_RISKY,
        }
    )
    assert ok is True
    assert "accepted risk" in message


def test_executor_reports_failure_detail(monkeypatch, on_windows):
    monkeypatch.setattr(ai, "_run", lambda cmd, timeout: (1, "Installer failed with 1603"))
    ok, message = exec_install_app({"package_id": "X.Thing", "name": "Thing"})
    assert ok is False
    assert "1603" in message
