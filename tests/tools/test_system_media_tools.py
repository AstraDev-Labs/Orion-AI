"""system_control, play_music and play_video without touching the real machine."""

from __future__ import annotations

import sys

import pytest

from orion.tools import play_music, play_video, system_control

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="system_control is Windows-only")


@windows_only
def test_wifi_uses_real_adapter_name_and_falls_back_without_admin(monkeypatch):
    calls = []

    def fake_run(cmd):
        calls.append(cmd)
        if cmd[:4] == ["netsh", "wlan", "show", "interfaces"]:
            return True, "    Name                   : WLAN 2\n    State                  : connected"
        if cmd[:3] == ["netsh", "interface", "set"]:
            return False, "The requested operation requires elevation."
        if cmd[:3] == ["netsh", "wlan", "disconnect"]:
            return True, "Disconnection request was completed successfully"
        return False, ""

    monkeypatch.setattr(system_control, "_run", fake_run)
    ok, msg = system_control._set_wifi(False)
    assert ok and "Disconnected" in msg
    assert ["netsh", "interface", "set", "interface", "WLAN 2", "disabled"] in calls


@windows_only
def test_sleep_calls_api_not_rundll32(monkeypatch):
    called = {}

    class _Powrprof:
        @staticmethod
        def SetSuspendState(hibernate, force, wake):  # noqa: N802
            called["args"] = (hibernate, force, wake)
            return 1

    class _Windll:
        powrprof = _Powrprof()

    monkeypatch.setattr(system_control.ctypes, "windll", _Windll(), raising=False)
    ok, _ = system_control._sleep()
    assert ok and called["args"] == (False, True, False)  # sleep, never hibernate


@windows_only
def test_brightness_get_parses_level(monkeypatch):
    monkeypatch.setattr(system_control, "_run", lambda cmd: (True, "65\r\n"))
    assert system_control._get_brightness() == (True, "Brightness is 65%.")


def test_spotify_falls_back_to_web_when_app_missing(monkeypatch):
    opened = []
    monkeypatch.setattr(play_music, "_spotify_app_installed", lambda: False)
    monkeypatch.setattr(play_music.webbrowser, "open", lambda url: opened.append(url))
    msg = play_music._open_spotify("Blinding Lights")
    assert opened == ["https://open.spotify.com/search/Blinding%20Lights"]
    assert "Web Player" in msg


def test_youtube_plays_first_result(monkeypatch):
    opened = []
    monkeypatch.setattr(play_music, "youtube_first_video_id", lambda q: "7wtfhZwyrcc")
    monkeypatch.setattr(play_music.webbrowser, "open", lambda url: opened.append(url))
    play_music._open_youtube_music("Imagine Dragons Believer")
    assert opened == ["https://music.youtube.com/watch?v=7wtfhZwyrcc&autoplay=1"]


def test_youtube_falls_back_to_search_when_lookup_fails(monkeypatch):
    opened = []
    monkeypatch.setattr(play_music, "youtube_first_video_id", lambda q: "")
    monkeypatch.setattr(play_video.webbrowser, "open", lambda url: opened.append(url))
    play_video._open_youtube_autoplay("Interstellar trailer")
    assert opened == ["https://www.youtube.com/results?search_query=Interstellar%20trailer"]


@windows_only
def test_local_player_requires_every_word(monkeypatch, tmp_path):
    music = tmp_path / "Music"
    music.mkdir()
    (music / "Love Story.mp3").write_bytes(b"x")
    (music / "Love Me Like You Do.mp3").write_bytes(b"x")
    started = []
    monkeypatch.setattr(play_music.Path if hasattr(play_music, "Path") else __import__("pathlib").Path, "home", lambda: tmp_path)
    monkeypatch.setattr("os.startfile", lambda p: started.append(p), raising=False)
    msg = play_music._open_media_player("love me like you do")
    assert started and started[0].endswith("Love Me Like You Do.mp3")
    assert "Love Me Like You Do" in msg
