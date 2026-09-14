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


# --- Repeated or late approvals must never revive an action -----------------


def _run_all(store, ran):
    from orion.tools.proactive_tools import ExecutePendingActionsTool

    def executor(action):
        ran.append(action.id)
        return True, "sent"

    return ExecutePendingActionsTool(store=store, executor_fn=executor)


def test_repeated_id_approval_does_not_run_an_executed_action_again(store):
    from orion.tools.approval_store import STATUS_EXECUTED

    action = _draft(store, "a@b.com")
    ran: list[str] = []
    tool = _run_all(store, ran)

    assert parse_approval_response(f"{action.id} yes", store=store)
    tool.execute(action_ids=[action.id])
    assert ran == [action.id]
    assert store.get_action(action.id).status == STATUS_EXECUTED

    # The same message submitted again (retry, duplicate send).
    assert parse_approval_response(f"{action.id} yes", store=store) == []
    tool.execute(action_ids=[action.id])
    assert ran == [action.id]
    assert store.get_action(action.id).status == STATUS_EXECUTED


@pytest.mark.parametrize("reply", ["yes {id}", "{id} approve", "approve all"])
def test_denied_action_cannot_be_approved_later(store, reply):
    action = _draft(store, "a@b.com")
    assert parse_approval_response(f"no {action.id}", store=store)
    assert parse_approval_response(reply.format(id=action.id), store=store) == []
    assert store.get_action(action.id).status == STATUS_DENIED


def test_expired_action_cannot_be_approved(store):
    from orion.tools.approval_store import STATUS_PENDING

    action = store.queue_action(
        "email_send", "Email a@b.com", {"recipient": "a@b.com"}, "email_send", "high", ttl_hours=-1
    )
    assert parse_approval_response(f"{action.id} yes", store=store) == []
    assert store.get_action(action.id).status == STATUS_PENDING


def test_executor_runs_an_approved_action_once_even_if_called_twice(store):
    action = _draft(store, "a@b.com")
    assert parse_approval_response("send it", store=store)
    ran: list[str] = []
    tool = _run_all(store, ran)
    first = tool.execute(action_ids=[action.id])
    second = tool.execute(action_ids=[action.id])
    assert ran == [action.id]
    assert first.metadata["executed"] == 1
    assert second.metadata["executed"] == 0


def test_record_decision_refuses_an_already_decided_action(store):
    from orion.tools.proactive_tools import RecordDecisionTool

    action = _draft(store, "a@b.com")
    assert parse_approval_response(f"{action.id} no", store=store)
    result = RecordDecisionTool(store=store).execute(action_id=action.id, approved=True)
    assert result.success is False
    assert store.get_action(action.id).status == STATUS_DENIED
