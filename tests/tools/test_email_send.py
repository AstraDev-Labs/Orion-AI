"""SMTP email sending for approved ``email_send`` actions (fake SMTP, no network)."""

from __future__ import annotations

import smtplib

import pytest

from orion.tools import email_send
from orion.tools.email_send import exec_email_send, send_email, smtp_server_for


class FakeSMTP:
    instances: list["FakeSMTP"] = []
    fail_login = False

    def __init__(self, host, port, timeout=None):
        self.host, self.port = host, port
        self.tls = False
        self.logged_in = None
        self.sent = []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        self.tls = True

    def login(self, user, password):
        if FakeSMTP.fail_login:
            raise smtplib.SMTPAuthenticationError(535, b"bad credentials")
        self.logged_in = (user, password)

    def send_message(self, msg):
        self.sent.append(msg)
        return {}


@pytest.fixture(autouse=True)
def fake_smtp(monkeypatch):
    FakeSMTP.instances = []
    FakeSMTP.fail_login = False
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    creds = {"EMAIL_USERNAME": "me@gmail.com", "EMAIL_PASSWORD": "abcd efgh ijkl mnop"}
    monkeypatch.setattr(email_send, "_credential", lambda key: creds.get(key, ""))
    return creds


def test_sends_over_starttls_with_app_password():
    ok, message = send_email("12345678@example.edu", "Hello, this is a test email.", "Test")
    assert ok, message
    server = FakeSMTP.instances[-1]
    assert (server.host, server.port, server.tls) == ("smtp.gmail.com", 587, True)
    assert server.logged_in == ("me@gmail.com", "abcdefghijklmnop")  # spaces stripped
    msg = server.sent[0]
    assert msg["To"] == "12345678@example.edu" and msg["Subject"] == "Test"
    assert "Hello, this is a test email." in msg.get_content()


def test_invalid_recipient_never_connects():
    ok, message = send_email("12345678@example.e", "hi")
    assert not ok and "not a valid email address" in message
    ok, message = send_email("12345678 at nec", "hi")
    assert not ok
    assert FakeSMTP.instances == []


def test_missing_credentials_points_to_setup(fake_smtp):
    fake_smtp.clear()
    ok, message = send_email("a@b.com", "hi")
    assert not ok and "orion email setup" in message
    assert FakeSMTP.instances == []


def test_rejected_login_is_reported_plainly():
    FakeSMTP.fail_login = True
    ok, message = send_email("a@b.com", "hi")
    assert not ok and "rejected the login" in message and "app password" in message


def test_executor_accepts_model_field_variants():
    ok, _ = exec_email_send({"recipient": "a@b.com", "content": "Hello there"})
    assert ok
    msg = FakeSMTP.instances[-1].sent[0]
    assert msg["To"] == "a@b.com" and msg["Subject"] == "Hello there"
    ok, _ = exec_email_send({"to": ["c@d.org"], "body": "Hi", "subject": "S"})
    assert ok and FakeSMTP.instances[-1].sent[0]["To"] == "c@d.org"


def test_smtp_host_follows_provider():
    assert smtp_server_for("x@outlook.com") == ("smtp-mail.outlook.com", 587)
    assert smtp_server_for("x@gmail.com") == ("smtp.gmail.com", 587)


def test_approved_action_is_actually_sent(tmp_path):
    from orion.tools.approval_store import STATUS_EXECUTED, ApprovalStore
    from orion.tools.proactive_tools import ExecutePendingActionsTool, parse_approval_response

    store = ApprovalStore(str(tmp_path / "approvals.db"))
    action = store.queue_action(
        "email_send",
        "Email 12345678@example.edu",
        {"recipient": "12345678@example.edu", "subject": "", "body": "Hello, this is a test email."},
        "email_send:12345678@example.edu",
        "high",
    )
    assert parse_approval_response("Yes, send it.", store=store)[0]["approved"] is True
    result = ExecutePendingActionsTool(store=store).execute(action_ids=[action.id])
    assert '"success": true' in result.content
    assert store.get_action(action.id).status == STATUS_EXECUTED
    assert FakeSMTP.instances[-1].sent[0]["To"] == "12345678@example.edu"


def test_credentials_toml_survives_special_characters(tmp_path):
    from orion.core.credentials import load_credentials, save_credential

    path = tmp_path / "credentials.toml"
    save_credential("email", "EMAIL_PASSWORD", 'we"ird\\pass', path=path)
    assert load_credentials(path)["email"]["EMAIL_PASSWORD"] == 'we"ird\\pass'


def test_queue_rejects_incomplete_address(tmp_path):
    from orion.tools.approval_store import ApprovalStore
    from orion.tools.proactive_tools import QueueActionTool

    store = ApprovalStore(str(tmp_path / "approvals.db"))
    tool = QueueActionTool(store=store)
    common = {"action_type": "email_send", "description": "d", "permission_key": "k", "tier": "high"}
    bad = tool.execute(payload={"recipient": "12345678@example.e", "body": "hi"}, **common)
    assert not bad.success and store.list_pending() == []
    good = tool.execute(payload={"recipient": "12345678@example.edu", "body": "hi"}, **common)
    assert good.success and len(store.list_pending()) == 1
