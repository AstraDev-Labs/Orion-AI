"""Tests for install_game, and the confirmation gate that silently disabled it.

Two regressions are pinned here:

* ``install_game`` existed as a module but was never registered, dispatched or
  routed, so the capability simply did not exist at runtime.
* Both install tools set ``requires_confirmation=True``. tools/_stubs.py
  enforces that by refusing the call outright when there is no interactive
  confirm callback -- which is always the case on the server -- so the model
  could call them and nothing would ever run.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from orion.core.registry import ToolRegistry
from orion.tools import game_install as gi
from orion.tools.approval_store import TIER_HIGH, TIER_MEDIUM, ApprovalStore
from orion.tools.game_install import (
    OWNED_CONFIRMED,
    OWNED_NOT,
    OWNED_UNVERIFIED,
    REQ_FAIL,
    REQ_MANUAL,
    REQ_PASS,
    REQ_UNKNOWN,
    Check,
    GameRef,
    GameReport,
    InstallGameTool,
    check_requirements,
    exec_install_game,
    install_url,
    parse_requirements,
)

STEAM = gi.PLATFORM_STEAM


@pytest.fixture
def store() -> ApprovalStore:
    return ApprovalStore(str(Path(tempfile.mkdtemp()) / "approvals.db"))


@pytest.fixture
def on_windows(monkeypatch):
    monkeypatch.setattr(gi, "_is_windows", lambda: True)
    monkeypatch.setattr(
        gi,
        "detect_platforms",
        lambda: {STEAM: True, gi.PLATFORM_EPIC: False, gi.PLATFORM_EA: False, gi.PLATFORM_UBISOFT: False},
    )


def _specs(**kw) -> gi.Specs:
    base = dict(
        cpu="Intel i5-12500H",
        cores=12,
        ram_gb=15.7,
        gpu="NVIDIA GeForce RTX 2050",
        vram_gb=4.0,
        os_caption="Microsoft Windows 11 Home",
        arch="64-bit",
        free_disk_gb=500.0,
        disk_target="C:\\",
    )
    base.update(kw)
    return gi.Specs(**base)


# ---------------------------------------------------------------------------
# Wiring: the capability must actually exist
# ---------------------------------------------------------------------------


def test_tool_is_registered(real_registries):
    """It was written but never imported, so it never registered."""
    import orion.tools  # noqa: F401

    assert ToolRegistry.contains("install_game")


def test_approved_action_has_an_executor():
    """proactive_tools must dispatch install_game, not fall through."""
    from orion.tools.proactive_tools import ExecutePendingActionsTool  # noqa: F401
    import orion.tools.proactive_tools as pt

    src = Path(pt.__file__).read_text(encoding="utf-8")
    assert 'atype == "install_game"' in src
    assert "exec_install_game" in src


def test_router_surfaces_it_for_game_requests(real_registries):
    import orion.tools  # noqa: F401
    from orion.tools.tool_router import select_tools

    tools = []
    for name in ToolRegistry.keys():
        try:
            tools.append(ToolRegistry.get(name)())
        except Exception:
            pass
    picked = [t.spec.name for t in select_tools(tools, "install a game from my steam library", max_tools=6)]
    assert "install_game" in picked


def test_generic_installs_still_prefer_install_app(real_registries):
    """install_game must not claim 'install'/'download' and outrank install_app."""
    import orion.tools  # noqa: F401
    from orion.tools.tool_router import select_tools

    tools = []
    for name in ToolRegistry.keys():
        try:
            tools.append(ToolRegistry.get(name)())
        except Exception:
            pass
    picked = [t.spec.name for t in select_tools(tools, "install vlc", max_tools=6)]
    assert picked.index("install_app") < picked.index("install_game")


# ---------------------------------------------------------------------------
# The confirmation gate that made both tools dead on the server
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tool_name", ["install_app", "install_game"])
def test_install_tools_are_not_confirmation_gated(tool_name, real_registries):
    """requires_confirmation is refused outright without an interactive callback.

    Both tools already queue a TIER_HIGH approval and install nothing
    themselves, so the flag added no safety and made them unusable.
    """
    import orion.tools  # noqa: F401

    spec = ToolRegistry.get(tool_name)().spec
    assert spec.requires_confirmation is False


# ---------------------------------------------------------------------------
# Requirements comparison
# ---------------------------------------------------------------------------


def test_parses_real_steam_requirement_html():
    html = (
        "<strong>Minimum:</strong><br><ul class='bb_ul'>"
        "<li><strong>OS:</strong> Windows 10<br></li>"
        "<li><strong>Processor:</strong> INTEL CORE I5-8400<br></li>"
        "<li><strong>Memory:</strong> 12 GB RAM<br></li>"
        "<li><strong>Graphics:</strong> NVIDIA GEFORCE GTX 1060 3 GB<br></li>"
        "<li><strong>Storage:</strong> 60 GB available space</li></ul>"
    )
    got = parse_requirements(html)
    assert got["os"] == "Windows 10"
    assert got["memory"] == "12 GB RAM"
    assert got["storage"] == "60 GB available space"


def _verdict(checks, item):
    return next(c.verdict for c in checks if c.item == item)


def test_insufficient_storage_fails():
    checks = check_requirements({"storage": "60 GB available space"}, _specs(free_disk_gb=36.2))
    assert _verdict(checks, "Storage") == REQ_FAIL


def test_sufficient_storage_passes():
    checks = check_requirements({"storage": "60 GB available space"}, _specs(free_disk_gb=500.0))
    assert _verdict(checks, "Storage") == REQ_PASS


def test_ram_tolerance_accepts_a_16gb_machine():
    """WMI reports 15.7 GB on a 16 GB box; a 16 GB requirement must not fail."""
    checks = check_requirements({"memory": "16 GB RAM"}, _specs(ram_gb=15.7))
    assert _verdict(checks, "Memory") == REQ_PASS


def test_windows_11_satisfies_a_windows_10_requirement():
    checks = check_requirements({"os": "Windows 10"}, _specs())
    assert _verdict(checks, "OS") == REQ_PASS


def test_vram_is_extracted_from_the_graphics_line():
    checks = check_requirements(
        {"graphics": "NVIDIA GEFORCE GTX 1060 3 GB"}, _specs(vram_gb=4.0)
    )
    assert _verdict(checks, "VRAM") == REQ_PASS


def test_insufficient_vram_fails():
    checks = check_requirements(
        {"graphics": "NVIDIA RTX 3080 10 GB"}, _specs(vram_gb=4.0)
    )
    assert _verdict(checks, "VRAM") == REQ_FAIL


def test_cpu_and_gpu_are_never_auto_ranked():
    """Ranking two arbitrary part numbers cannot be done truthfully."""
    checks = check_requirements(
        {"processor": "INTEL CORE I5-8400", "graphics": "GTX 1060"}, _specs()
    )
    assert _verdict(checks, "Processor") == REQ_MANUAL
    assert _verdict(checks, "Graphics") == REQ_MANUAL


def test_unstated_requirement_is_unknown_not_a_failure():
    checks = check_requirements({}, _specs())
    assert _verdict(checks, "Memory") == REQ_UNKNOWN


# ---------------------------------------------------------------------------
# Install URLs -- none of these can purchase anything
# ---------------------------------------------------------------------------


def test_steam_install_url():
    assert install_url(GameRef(STEAM, "1245620", "ELDEN RING")) == "steam://install/1245620"


def test_epic_install_url_is_encoded():
    url = install_url(GameRef(gi.PLATFORM_EPIC, "ns:cat:app", "X"))
    assert url.startswith("com.epicgames.launcher://apps/")
    assert "%3A" in url and url.endswith("?action=install")


def test_unknown_platform_has_no_url():
    assert install_url(GameRef("gog", "1", "X")) == ""


# ---------------------------------------------------------------------------
# Queueing behaviour
# ---------------------------------------------------------------------------


def _patch_resolution(monkeypatch, *, ownership, details=None, installed=None):
    monkeypatch.setattr(gi, "installed_games", lambda: installed or [])
    monkeypatch.setattr(gi, "_steam_search", lambda q: [{"id": 1245620, "name": "ELDEN RING"}])
    monkeypatch.setattr(gi, "_steam_appdetails", lambda a: details or {"name": "ELDEN RING"})
    monkeypatch.setattr(gi, "_steam_owns", lambda a: (ownership, "test"))
    monkeypatch.setattr(gi, "read_specs", lambda target_dir="": _specs())
    monkeypatch.setattr(gi, "_steam_root", lambda: None)


def test_not_owned_never_queues_and_never_buys(monkeypatch, on_windows, store):
    _patch_resolution(monkeypatch, ownership=OWNED_NOT)
    result = InstallGameTool(store=store).execute(name="Elden Ring")
    assert result.metadata["status"] == "not_owned"
    assert store.list_pending() == []
    assert "won't buy" in result.content or "not in your" in result.content


def test_already_installed_short_circuits(monkeypatch, on_windows, store):
    installed = [GameRef(STEAM, "1245620", "ELDEN RING", install_dir="D:/games/er")]
    _patch_resolution(monkeypatch, ownership=OWNED_CONFIRMED, installed=installed)
    result = InstallGameTool(store=store).execute(name="ELDEN RING")
    assert result.metadata["status"] == "already_installed"
    assert store.list_pending() == []


def test_requirements_shortfall_blocks_queueing(monkeypatch, on_windows, store):
    details = {
        "name": "ELDEN RING",
        "pc_requirements": {"minimum": "<strong>Storage:</strong> 900 GB available space"},
    }
    _patch_resolution(monkeypatch, ownership=OWNED_CONFIRMED, details=details)
    result = InstallGameTool(store=store).execute(name="Elden Ring")
    assert result.metadata["status"] == "requirements_not_met"
    assert store.list_pending() == []


def test_shortfall_can_be_overridden_explicitly(monkeypatch, on_windows, store):
    details = {
        "name": "ELDEN RING",
        "pc_requirements": {"minimum": "<strong>Storage:</strong> 900 GB available space"},
    }
    _patch_resolution(monkeypatch, ownership=OWNED_CONFIRMED, details=details)
    result = InstallGameTool(store=store).execute(name="Elden Ring", ignore_requirements=True)
    assert result.metadata["status"] == "queued"
    action = store.list_pending()[0]
    assert action.payload["requirements_overridden"] is True
    assert "BELOW MINIMUM SPEC" in action.description


def test_confirmed_ownership_queues_at_medium_tier(monkeypatch, on_windows, store):
    _patch_resolution(monkeypatch, ownership=OWNED_CONFIRMED)
    InstallGameTool(store=store).execute(name="Elden Ring")
    assert store.list_pending()[0].tier == TIER_MEDIUM


def test_unverified_ownership_always_asks(monkeypatch, on_windows, store):
    _patch_resolution(monkeypatch, ownership=OWNED_UNVERIFIED)
    result = InstallGameTool(store=store).execute(name="Elden Ring")
    assert store.list_pending()[0].tier == TIER_HIGH
    assert "could not confirm" in result.content


# ---------------------------------------------------------------------------
# Never a dead end
# ---------------------------------------------------------------------------


def test_no_launcher_offers_a_route_forward(monkeypatch, store):
    monkeypatch.setattr(gi, "_is_windows", lambda: True)
    monkeypatch.setattr(gi, "detect_platforms", lambda: {p: False for p in gi._PLATFORM_LABELS})
    result = InstallGameTool(store=store).execute(name="Elden Ring")
    assert result.metadata["status"] == "unavailable"
    assert "not found" not in result.content.lower()


def test_unknown_title_suggests_alternatives(monkeypatch, on_windows, store):
    monkeypatch.setattr(gi, "installed_games", lambda: [])
    monkeypatch.setattr(gi, "_steam_search", lambda q: [])
    result = InstallGameTool(store=store).execute(name="zzznotreal")
    assert result.metadata["status"] == "unavailable"
    assert "Epic" in result.content or "platform" in result.content


def test_empty_name_is_rejected(store):
    assert InstallGameTool(store=store).execute(name="  ").success is False


# ---------------------------------------------------------------------------
# Post-approval executor
# ---------------------------------------------------------------------------


def test_executor_rejects_incomplete_payload():
    ok, msg = exec_install_game({"platform": STEAM})
    assert ok is False and "app_id" in msg


def test_executor_hands_the_url_to_the_launcher(monkeypatch):
    monkeypatch.setattr(gi, "_is_windows", lambda: True)
    captured = {}
    monkeypatch.setattr(gi.os, "startfile", lambda u: captured.setdefault("url", u), raising=False)
    ok, msg = exec_install_game(
        {"platform": STEAM, "app_id": "1245620", "title": "ELDEN RING"}
    )
    assert ok is True
    assert captured["url"] == "steam://install/1245620"


def test_executor_flags_an_overridden_spec(monkeypatch):
    monkeypatch.setattr(gi, "_is_windows", lambda: True)
    monkeypatch.setattr(gi.os, "startfile", lambda u: None, raising=False)
    ok, msg = exec_install_game(
        {
            "platform": STEAM,
            "app_id": "1",
            "title": "X",
            "requirements_overridden": True,
        }
    )
    assert ok is True and "below the game's stated minimum" in msg


# ---------------------------------------------------------------------------
# Report shaping
# ---------------------------------------------------------------------------


def test_report_flags_failures():
    report = GameReport(
        game=GameRef(STEAM, "1", "X"),
        ownership=OWNED_CONFIRMED,
        checks=[Check("Storage", "60 GB", "10 GB", REQ_FAIL)],
    )
    assert report.meets_requirements is False
    assert len(report.failures) == 1


def test_manual_checks_do_not_count_as_failures():
    report = GameReport(
        game=GameRef(STEAM, "1", "X"),
        ownership=OWNED_CONFIRMED,
        checks=[Check("Processor", "i5-8400", "i5-12500H", REQ_MANUAL)],
    )
    assert report.meets_requirements is True
