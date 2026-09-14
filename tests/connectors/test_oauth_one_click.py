"""One-click Google sign-in: shipped client, PKCE, state, scope-scoped token files."""

from __future__ import annotations

import base64
import hashlib
import socket
import threading
import time
import urllib.request
from urllib.parse import parse_qs, urlparse

import pytest

from orion.connectors import oauth, oauth_clients


@pytest.fixture
def flow(tmp_path, monkeypatch):
    monkeypatch.setattr(oauth, "_CONNECTORS_DIR", tmp_path)
    opened: list[str] = []
    exchanged: dict = {}
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url) or True)

    def fake_wait(host, port, path, expected_state=None, timeout=120):
        exchanged["expected_state"] = expected_state
        return "the-code"

    def fake_exchange(provider, code, client_id, client_secret, redirect_uri, code_verifier=""):
        exchanged.update(code=code, client_id=client_id, verifier=code_verifier)
        return {"access_token": "at", "refresh_token": "rt", "expires_in": 3600}

    monkeypatch.setattr(oauth, "_wait_for_callback_code", fake_wait)
    monkeypatch.setattr(oauth, "_exchange_token", fake_exchange)
    return tmp_path, opened, exchanged


def test_no_shipped_client_means_no_one_click(monkeypatch, flow):
    monkeypatch.delenv("ORION_GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("ORION_GOOGLE_CLIENT_SECRET", raising=False)
    assert oauth.shipped_client(oauth.OAUTH_PROVIDERS["google"]) == ("", "")
    with pytest.raises(RuntimeError, match="No client credentials"):
        oauth.run_connector_oauth("gcalendar")


def test_one_click_uses_shipped_client_with_pkce_and_state(monkeypatch, flow):
    tmp_path, opened, exchanged = flow
    monkeypatch.setenv("ORION_GOOGLE_CLIENT_ID", "shipped.apps.googleusercontent.com")
    monkeypatch.setenv("ORION_GOOGLE_CLIENT_SECRET", "public-secret")

    oauth.run_connector_oauth("gcalendar")

    params = {k: v[0] for k, v in parse_qs(urlparse(opened[0]).query).items()}
    assert params["client_id"] == "shipped.apps.googleusercontent.com"
    assert params["state"] == exchanged["expected_state"] and len(params["state"]) > 20
    assert params["code_challenge_method"] == "S256"
    expected_challenge = base64.urlsafe_b64encode(hashlib.sha256(exchanged["verifier"].encode()).digest()).decode().rstrip("=")
    assert params["code_challenge"] == expected_challenge
    # Only non-restricted scopes on the shipped client.
    assert "auth/drive" not in params["scope"] and "auth/gmail" not in params["scope"]
    assert "auth/calendar" in params["scope"]

    written = {p.name for p in tmp_path.iterdir()}
    assert {"google.json", "gcalendar.json", "gcontacts.json", "google_tasks.json"} <= written
    assert "gdrive.json" not in written and "gmail.json" not in written
    # The shipped client is not reported as the user's own client.
    assert oauth.get_client_credentials(oauth.OAUTH_PROVIDERS["google"]) is None


def test_own_client_takes_priority_and_keeps_full_scopes(monkeypatch, flow):
    tmp_path, opened, exchanged = flow
    monkeypatch.setenv("ORION_GOOGLE_CLIENT_ID", "shipped")
    monkeypatch.setenv("ORION_GOOGLE_CLIENT_SECRET", "public-secret")
    oauth.save_client_credentials(oauth.OAUTH_PROVIDERS["google"], "mine", "my-secret")

    oauth.run_connector_oauth("gcalendar")

    params = parse_qs(urlparse(opened[0]).query)
    assert params["client_id"] == ["mine"]
    assert "auth/drive" in params["scope"][0]
    assert (tmp_path / "gdrive.json").exists()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_callback_ignores_wrong_state_and_accepts_right_one():
    port = _free_port()
    result: dict = {}

    def run():
        result["code"] = oauth._wait_for_callback_code(port=port, timeout=10, expected_state="good")

    t = threading.Thread(target=run)
    t.start()
    time.sleep(0.8)
    for state, code in (("evil", "attacker-code"), ("good", "real-code")):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/callback?code={code}&state={state}", timeout=5)
        except Exception:
            pass  # the rejected request answers 400
    t.join(timeout=10)
    assert result["code"] == "real-code"


def test_callback_times_out_instead_of_hanging():
    start = time.monotonic()
    with pytest.raises(RuntimeError, match="timed out"):
        oauth._wait_for_callback_code(port=_free_port(), timeout=2)
    assert time.monotonic() - start < 8


def test_shipped_scopes_exclude_restricted():
    assert not any("drive" in s or "gmail" in s for s in oauth_clients.GOOGLE_ONE_CLICK_SCOPES)
