"""Connections API: catalog, write-only secrets, verify-before-save, loopback guard."""

from __future__ import annotations

import dataclasses

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from orion.core import credentials
from orion.server import connections


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(credentials, "_DEFAULT_PATH", tmp_path / "credentials.toml")
    monkeypatch.setattr(connections, "_CONNECTORS_DIR", tmp_path / "connectors")
    for key in ("EMAIL_USERNAME", "EMAIL_PASSWORD", "EMAIL_SMTP_HOST", "EMAIL_SMTP_PORT", "TAVILY_API_KEY"):
        monkeypatch.delenv(key, raising=False)

    calls = []

    def fake_verifier(values):
        calls.append(dict(values))
        if values.get("EMAIL_PASSWORD") == "wrong" or values.get("token") == "wrong":
            return False, "rejected"
        return True, "verified ok"

    patched = tuple(
        dataclasses.replace(c, verifier=fake_verifier) if c.verifier is not None else c
        for c in connections.CATALOG
    )
    monkeypatch.setattr(connections, "CATALOG", patched)
    monkeypatch.setattr(connections, "_BY_ID", {c.id: c for c in patched})

    app = FastAPI()
    app.state.api_key = ""
    app.include_router(connections.router)
    c = TestClient(app)
    c.verifier_calls = calls
    return c


def _conn(client, cid):
    items = client.get("/v1/connections").json()["connections"]
    return next(i for i in items if i["id"] == cid)


def test_catalog_lists_every_category(client):
    items = client.get("/v1/connections").json()["connections"]
    ids = {i["id"] for i in items}
    assert {"email", "telegram", "whatsapp", "web_search", "obsidian", "google", "openai"} <= ids
    assert all(i["status"] in ("not_connected", "coming_soon") for i in items if i["kind"] != "whatsapp")


def test_save_verifies_and_never_returns_secret(client):
    res = client.put(
        "/v1/connections/email",
        json={"values": {"EMAIL_USERNAME": "me@gmail.com", "EMAIL_PASSWORD": "abcd efgh ijkl mnop"}},
    ).json()
    assert res["saved"] and res["ok"] and res["message"] == "verified ok"
    email = _conn(client, "email")
    assert email["status"] == "connected"
    fields = {f["key"]: f for f in email["fields"]}
    assert fields["EMAIL_USERNAME"]["value"] == "me@gmail.com"
    assert fields["EMAIL_PASSWORD"] == {**fields["EMAIL_PASSWORD"], "set": True, "value": ""}
    assert "abcd" not in client.get("/v1/connections").text


def test_failed_verification_keeps_the_working_secret(client):
    client.put("/v1/connections/email", json={"values": {"EMAIL_USERNAME": "me@gmail.com", "EMAIL_PASSWORD": "good"}})
    res = client.put("/v1/connections/email", json={"values": {"EMAIL_PASSWORD": "wrong"}}).json()
    assert not res["saved"] and res["message"] == "rejected"
    assert credentials.get_tool_credential("email", "EMAIL_PASSWORD") == "good"


def test_blank_secret_keeps_stored_value_when_editing_other_fields(client):
    client.put("/v1/connections/email", json={"values": {"EMAIL_USERNAME": "me@gmail.com", "EMAIL_PASSWORD": "good"}})
    res = client.put(
        "/v1/connections/email", json={"values": {"EMAIL_USERNAME": "other@gmail.com", "EMAIL_PASSWORD": ""}}
    ).json()
    assert res["saved"]
    assert client.verifier_calls[-1]["EMAIL_PASSWORD"] == "good"
    assert credentials.get_tool_credential("email", "EMAIL_USERNAME") == "other@gmail.com"


def test_missing_required_field_is_rejected(client):
    res = client.put("/v1/connections/email", json={"values": {"EMAIL_USERNAME": "me@gmail.com"}})
    assert res.status_code == 400 and "App password" in res.json()["detail"]


def test_unknown_field_and_connection_rejected(client):
    assert client.put("/v1/connections/email", json={"values": {"EVIL": "x", "EMAIL_USERNAME": "a@b.co", "EMAIL_PASSWORD": "p"}}).status_code == 400
    assert client.put("/v1/connections/nope", json={"values": {}}).status_code == 404


def test_connector_json_storage_and_disconnect(client, tmp_path):
    res = client.put("/v1/connections/github", json={"values": {"token": "ghp_123"}}).json()
    assert res["saved"]
    path = tmp_path / "connectors" / "github.json"
    assert '"token": "ghp_123"' in path.read_text(encoding="utf-8")
    assert _conn(client, "github")["status"] == "connected"
    assert client.delete("/v1/connections/github").json()["ok"]
    assert not path.exists() and _conn(client, "github")["status"] == "not_connected"


def test_disconnect_credentials_clears_env(client, monkeypatch):
    import os

    client.put("/v1/connections/web_search", json={"values": {"TAVILY_API_KEY": "tvly-1"}})
    assert os.environ.get("TAVILY_API_KEY") == "tvly-1"
    client.delete("/v1/connections/web_search")
    assert "TAVILY_API_KEY" not in os.environ
    assert credentials.get_tool_credential("web_search", "TAVILY_API_KEY") is None


def test_restart_flag_reported(client):
    res = client.put("/v1/connections/web_search", json={"values": {"TAVILY_API_KEY": "tvly-1"}}).json()
    assert "Restart Orion" in res["message"]


def test_remote_clients_are_refused(client):
    remote = TestClient(client.app, client=("192.168.1.50", 5000))
    assert remote.get("/v1/connections").status_code == 403
    assert remote.put("/v1/connections/email", json={"values": {}}).status_code == 403


def test_remote_allowed_when_api_key_auth_enabled(client):
    client.app.state.api_key = "secret"
    remote = TestClient(client.app, client=("192.168.1.50", 5000))
    assert remote.get("/v1/connections").status_code == 200


def test_one_email_login_covers_gmail_inbox(client, tmp_path):
    from orion.connectors.gmail_imap import GmailIMAPConnector

    ids = {i["id"] for i in client.get("/v1/connections").json()["connections"]}
    assert "gmail_imap" not in ids  # no second form asking for the same login

    reader = GmailIMAPConnector(credentials_path=str(tmp_path / "connectors" / "gmail_imap.json"))
    assert not reader.is_connected()
    client.put("/v1/connections/email", json={"values": {"EMAIL_USERNAME": "me@gmail.com", "EMAIL_PASSWORD": "abcd efgh"}})
    assert reader.is_connected()
    assert reader._resolve_credentials() == ("me@gmail.com", "abcdefgh")
    client.delete("/v1/connections/email")
    assert not reader.is_connected()


def test_service_reason_and_hint_are_shown(monkeypatch):
    import httpx

    def fake_request(method, url, **kwargs):
        return httpx.Response(401, json={"cod": 401, "message": "Invalid API key."}, request=httpx.Request(method, url))

    monkeypatch.setattr(connections.httpx, "request", fake_request)
    ok, message = connections._verify_weather({"api_key": "k", "location": "Palayamkottai,IN"})
    assert not ok
    assert "Invalid API key." in message and "2 hours" in message


def test_whatsapp_status_follows_live_bridge(client, monkeypatch):
    monkeypatch.setattr(connections, "_whatsapp_live_status", lambda: "connected")
    assert _conn(client, "whatsapp")["status"] == "connected"
    monkeypatch.setattr(connections, "_whatsapp_live_status", lambda: "connecting")
    assert _conn(client, "whatsapp")["status"] == "not_connected"


def test_google_is_work_in_progress(client):
    google = _conn(client, "google")
    assert google["status"] == "coming_soon" and "website" in google["coming_soon"]
    res = client.post("/v1/connections/google/authorize")
    assert res.status_code == 400
