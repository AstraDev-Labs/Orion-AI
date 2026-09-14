"""open_app must never open an arbitrary search result for an unknown app."""

from __future__ import annotations

from orion.tools import open_app


def test_domain_match_heuristic():
    assert open_app._domain_matches_name("https://www.notion.so/", "Notion")
    assert open_app._domain_matches_name("https://discord.com/app", "Discord app")
    assert not open_app._domain_matches_name("https://apkpure.com/zzz-archive", "zzzz orion nonexistent app")
    assert not open_app._domain_matches_name("https://example.com", "the app")


def test_unknown_app_opens_nothing(monkeypatch):
    opened = []
    monkeypatch.setattr(open_app, "_resolve_exact", lambda name: None)
    monkeypatch.setattr(open_app, "_launch_via_start_menu", lambda name: False)
    monkeypatch.setattr(open_app, "_first_web_result", lambda q: "https://apkpure.com/zzz-archive")
    monkeypatch.setattr(open_app.webbrowser, "open", lambda url: opened.append(url))
    result = open_app.OpenAppTool().execute(app_name="zzzz orion nonexistent app")
    assert opened == []
    assert result.success is False
    assert "install" in result.content.lower()
