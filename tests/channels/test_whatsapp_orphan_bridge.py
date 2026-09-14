"""A bridge left behind by a killed backend is stopped before a new one starts."""

from __future__ import annotations

import subprocess
import sys

import pytest

from orion.channels.whatsapp_baileys import WhatsAppBaileysChannel


def _channel(tmp_path) -> WhatsAppBaileysChannel:
    ch = WhatsAppBaileysChannel()
    ch._runtime_dir = tmp_path
    return ch


def test_orphaned_bridge_is_stopped(tmp_path):
    fake_bridge = tmp_path / "dist" / "bridge.js"
    fake_bridge.parent.mkdir(parents=True)
    fake_bridge.write_text("")
    # A long-running process whose command line names this runtime's bridge.js.
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", str(fake_bridge)])
    try:
        ch = _channel(tmp_path)
        ch._write_pid_file(proc.pid)
        ch._stop_orphaned_bridge()
        assert proc.wait(timeout=10) is not None
    finally:
        if proc.poll() is None:
            proc.kill()


def test_unrelated_process_with_reused_pid_is_left_alone(tmp_path):
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        ch = _channel(tmp_path)
        ch._write_pid_file(proc.pid)
        ch._stop_orphaned_bridge()
        assert proc.poll() is None
    finally:
        proc.kill()


def test_missing_pid_file_is_fine(tmp_path):
    _channel(tmp_path)._stop_orphaned_bridge()


def test_connect_is_noop_while_bridge_alive(tmp_path, monkeypatch):
    ch = _channel(tmp_path)
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        ch._process = proc
        called = []
        monkeypatch.setattr(ch, "_ensure_bridge", lambda: called.append(1))
        ch.connect()
        assert called == []  # no second bridge started
    finally:
        proc.kill()
