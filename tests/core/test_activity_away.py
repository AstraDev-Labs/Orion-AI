"""Manual away flag must not outlive the user's return."""

from __future__ import annotations

import json
import time

from orion.core import activity


def _use_tmp_state(monkeypatch, tmp_path):
    monkeypatch.setattr(activity, "_STATE_PATH", tmp_path / "away_state.json")


def test_fresh_manual_away_holds_even_with_input(monkeypatch, tmp_path):
    _use_tmp_state(monkeypatch, tmp_path)
    monkeypatch.setattr(activity, "get_os_idle_seconds", lambda: 5.0)
    activity.set_manual_away(True)
    assert activity.get_manual_away() is True  # user may still be leaving


def test_stale_manual_away_clears_on_recent_input(monkeypatch, tmp_path):
    _use_tmp_state(monkeypatch, tmp_path)
    (tmp_path / "away_state.json").write_text(json.dumps({"manual_away": True, "set_at": time.time() - 3 * 86400}))
    monkeypatch.setattr(activity, "get_os_idle_seconds", lambda: 10.0)
    assert activity.get_manual_away() is False
    assert json.loads((tmp_path / "away_state.json").read_text())["manual_away"] is False


def test_stale_manual_away_kept_while_machine_idle(monkeypatch, tmp_path):
    _use_tmp_state(monkeypatch, tmp_path)
    (tmp_path / "away_state.json").write_text(json.dumps({"manual_away": True, "set_at": time.time() - 3 * 3600}))
    monkeypatch.setattr(activity, "get_os_idle_seconds", lambda: 3 * 3600.0)
    assert activity.get_manual_away() is True
