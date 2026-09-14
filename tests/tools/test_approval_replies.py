"""Bare spoken/typed replies to a drafted action ("send it", "Yes, go ahead.")."""

from __future__ import annotations

import time

import pytest

from orion.tools.approval_store import STATUS_APPROVED, STATUS_DENIED, ApprovalStore
from orion.tools.proactive_tools import parse_approval_response


@pytest.fixture
def store(tmp_path):
    return ApprovalStore(str(tmp_path / "approvals.db"))


def _draft(store, recipient):
    action = store.queue_action(
        "email_send", f"Email {recipient}", {"recipient": recipient}, "email_send", "high"
    )
    time.sleep(0.002)  # distinct created_at ordering
    return action


@pytest.mark.parametrize("reply", ["send it", "Send it.", "Yes, send it.", "yeah", "Go ahead!", "confirm"])
def test_voice_style_approvals(store, reply):
    action = _draft(store, "a@b.com")
    decisions = parse_approval_response(reply, store=store)
    assert decisions == [{"id": action.id, "approved": True, "remembered": False}]
    assert store.get_action(action.id).status == STATUS_APPROVED


@pytest.mark.parametrize("reply", ["no", "Cancel it.", "don't send it"])
def test_voice_style_denials(store, reply):
    action = _draft(store, "a@b.com")
    decisions = parse_approval_response(reply, store=store)
    assert decisions and decisions[0]["approved"] is False
    assert store.get_action(action.id).status == STATUS_DENIED


def test_bare_reply_targets_latest_draft_and_withdraws_older(store):
    wrong = _draft(store, "12345678@exampel.edu.ion")
    right = _draft(store, "12345678@example.edu")
    decisions = parse_approval_response("send it", store=store)
    assert [d["id"] for d in decisions] == [right.id]
    assert store.get_action(right.id).status == STATUS_APPROVED
    assert store.get_action(wrong.id).status == STATUS_DENIED


def test_sentences_are_not_approvals(store):
    _draft(store, "a@b.com")
    assert parse_approval_response("yes I think the weather is nice", store=store) == []
