"""Tests for OrionSystem.wire_channel() — channel → agent routing.

These tests exercise wire_channel() on OrionSystem directly. The serve.py
entrypoint now delegates all channel-wiring logic there.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from orion.channels._stubs import ChannelMessage
from orion.core.config import OrionConfig
from orion.core.events import EventBus
from orion.sessions.session import SessionStore
from orion.system import OrionSystem

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_channel_message(
    channel: str = "telegram",
    sender: str = "42",
    content: str = "hello",
    conversation_id: str = "42",
) -> ChannelMessage:
    return ChannelMessage(
        channel=channel,
        sender=sender,
        content=content,
        message_id="1",
        conversation_id=conversation_id,
    )


def _make_system(engine=None, agent_name="", tmp_path=None) -> OrionSystem:
    """Build a minimal OrionSystem with mock engine for testing wire_channel."""
    config = OrionConfig()
    if tmp_path is not None:
        config.sessions.db_path = str(tmp_path / "sessions.db")
    mock_engine = engine or MagicMock()
    return OrionSystem(
        config=config,
        bus=EventBus(record_history=False),
        engine=mock_engine,
        engine_key="mock",
        model="test-model",
        agent_name=agent_name,
    )


def _fire(channel_mock, cm: ChannelMessage) -> None:
    """Invoke all registered on_message handlers as if the channel received cm."""
    for handler in channel_mock.on_message.call_args_list:
        handler[0][0](cm)


@pytest.fixture(autouse=True)
def _deterministic_away(monkeypatch):
    """Pin the away gate instead of reading real OS idle time.

    wire_channel() skips auto-reply unless is_user_away() is true, and that
    reads the OS idle timer -- so these tests otherwise passed or failed
    depending on whether the developer had touched the keyboard in the last
    ten minutes. These cases exercise the routing and session logic downstream
    of the gate; none of them assert the closed-gate behaviour.
    """
    monkeypatch.setattr("orion.core.activity.is_user_away", lambda *a, **k: True)


def _make_channel_mock() -> MagicMock:
    """A channel mock that does not accidentally veto its own replies.

    A bare MagicMock auto-creates every attribute, so
    `getattr(bridge, "owner_replied_since")` returned a truthy mock whose call
    result was also truthy -- wire_channel then logged "Owner already replied"
    and never called send(). Real channels either omit the hook or return False.
    """
    ch = MagicMock()
    ch.owner_replied_since = MagicMock(return_value=False)
    return ch


def _wait_for_send(mock_channel, timeout: float = 5.0) -> None:
    """Block until the channel reply has actually been dispatched.

    wire_channel() hands replies to a ThreadPoolExecutor
    (see system/core.py's _reply_pool), so the handler returns before
    channel_bridge.send() runs. Asserting immediately after handler(cm) is a
    race that happens to pass only when the worker wins.
    """
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if mock_channel.send.call_count:
            return
        time.sleep(0.01)


# ---------------------------------------------------------------------------
# Tests via OrionSystem.wire_channel()
# ---------------------------------------------------------------------------


class TestWireChannelWithAgent:
    """wire_channel routes incoming messages through the agent and replies."""

    def test_ask_called_and_reply_sent(self, tmp_path):
        system = _make_system(agent_name="simple", tmp_path=tmp_path)
        # Patch ask() so we don't need a real engine/agent
        system.ask = MagicMock(return_value={"content": "pong"})

        mock_channel = _make_channel_mock()
        system.wire_channel(mock_channel)

        # Simulate an incoming message
        cm = _make_channel_message(content="ping")
        handler = mock_channel.on_message.call_args[0][0]
        handler(cm)

        _wait_for_send(mock_channel)

        system.ask.assert_called_once()
        assert system.ask.call_args[0][0] == "ping"
        mock_channel.send.assert_called_once_with(
            "telegram",
            "pong",
            conversation_id="42",
        )

    def test_session_store_created_lazily(self, tmp_path):
        system = _make_system(tmp_path=tmp_path)
        assert system.session_store is None

        mock_channel = _make_channel_mock()
        system.ask = MagicMock(return_value={"content": "ok"})
        system.wire_channel(mock_channel)

        handler = mock_channel.on_message.call_args[0][0]
        handler(_make_channel_message())

        assert system.session_store is not None

    def test_existing_session_store_reused(self, tmp_path):
        system = _make_system(tmp_path=tmp_path)
        existing_store = SessionStore(db_path=tmp_path / "sessions.db")
        system.session_store = existing_store
        system.ask = MagicMock(return_value={"content": "ok"})

        mock_channel = _make_channel_mock()
        system.wire_channel(mock_channel)

        handler = mock_channel.on_message.call_args[0][0]
        handler(_make_channel_message())

        assert system.session_store is existing_store


class TestWireChannelWithEngine:
    """wire_channel falls back to engine when no agent is set."""

    def test_engine_path_used_when_no_agent(self, tmp_path):
        system = _make_system(agent_name="", tmp_path=tmp_path)
        system.ask = MagicMock(return_value={"content": "raw reply"})

        mock_channel = _make_channel_mock()
        system.wire_channel(mock_channel)

        handler = mock_channel.on_message.call_args[0][0]
        handler(_make_channel_message(content="hi"))

        _wait_for_send(mock_channel)
        mock_channel.send.assert_called_once_with(
            "telegram",
            "raw reply",
            conversation_id="42",
        )


class TestWireChannelSessionIsolation:
    """Separate conversation_ids get independent sessions."""

    def test_two_chats_isolated(self, tmp_path):
        system = _make_system(tmp_path=tmp_path)
        replies = {"111": "reply-A", "222": "reply-B"}
        system.ask = MagicMock(
            side_effect=lambda q, **kw: {"content": replies.get(q, "")}
        )

        mock_channel = _make_channel_mock()
        system.wire_channel(mock_channel)
        handler = mock_channel.on_message.call_args[0][0]

        handler(_make_channel_message(content="111", conversation_id="111"))
        handler(_make_channel_message(content="222", conversation_id="222"))

        # Reload sessions — each chat must have only its own messages
        s1 = system.session_store.get_or_create("telegram:111")
        s2 = system.session_store.get_or_create("telegram:222")
        c1 = {m.content for m in s1.messages}
        c2 = {m.content for m in s2.messages}

        assert "111" in c1 and "222" not in c1
        assert "222" in c2 and "111" not in c2

    def test_same_chat_accumulates_history(self, tmp_path):
        system = _make_system(tmp_path=tmp_path)
        system.ask = MagicMock(return_value={"content": "reply"})

        mock_channel = _make_channel_mock()
        system.wire_channel(mock_channel)
        handler = mock_channel.on_message.call_args[0][0]

        handler(_make_channel_message(content="first"))
        handler(_make_channel_message(content="second"))

        session = system.session_store.get_or_create("telegram:42")
        contents = [m.content for m in session.messages]
        # user + assistant alternating for two turns
        assert contents.count("first") == 1
        assert contents.count("second") == 1


class TestWireChannelErrorHandling:
    """Handler sends a user-visible error message when ask() raises."""

    def test_generation_error_stays_silent(self, tmp_path):
        """A failed generation must not send anything to the contact.

        This used to assert that an error message was replied. wire_channel now
        deliberately swallows it -- see system/core.py: "stay silent rather than
        send an error to a contact" -- because the recipient is a third party
        who should never receive Orion's internal failures. The handler must
        still not raise.
        """
        system = _make_system(tmp_path=tmp_path)
        system.ask = MagicMock(side_effect=RuntimeError("boom"))

        mock_channel = _make_channel_mock()
        system.wire_channel(mock_channel)
        handler = mock_channel.on_message.call_args[0][0]
        handler(_make_channel_message())

        # Give the reply pool a chance to run before asserting nothing was sent.
        _wait_for_send(mock_channel, timeout=1.0)
        mock_channel.send.assert_not_called()


class TestChannelToolLoading:
    """OrionSystem receives tools when agent accepts them."""

    def test_tool_using_agent_receives_tools(self, tmp_path):
        """OrionSystem built with a tool list passes tools to the agent via ask()."""
        from orion.tools._stubs import BaseTool, ToolSpec

        # Minimal fake tool
        class _FakeTool(BaseTool):
            spec = ToolSpec(name="fake", description="", parameters={})

            def execute(self, **_):  # type: ignore[override]
                pass

        fake_tool = _FakeTool()
        config = OrionConfig()
        config.sessions.db_path = str(tmp_path / "sessions.db")

        system = OrionSystem(
            config=config,
            bus=EventBus(record_history=False),
            engine=MagicMock(),
            engine_key="mock",
            model="test-model",
            agent_name="simple",
            tools=[fake_tool],
        )

        assert len(system.tools) == 1
        assert system.tools[0].spec.name == "fake"

    def test_non_tool_agent_receives_empty_tools(self, tmp_path):
        """OrionSystem with no tools list results in empty tools — simple agent
        unaffected."""
        config = OrionConfig()
        config.sessions.db_path = str(tmp_path / "sessions.db")

        system = OrionSystem(
            config=config,
            bus=EventBus(record_history=False),
            engine=MagicMock(),
            engine_key="mock",
            model="test-model",
            agent_name="simple",
        )

        assert system.tools == []


class TestPerChatSessionIsolation:
    """Direct SessionStore isolation tests (not via wire_channel)."""

    def test_two_chats_have_separate_sessions(self, tmp_path):
        store = SessionStore(db_path=tmp_path / "sessions.db")

        session_a = store.get_or_create(
            "telegram:111",
            channel="telegram",
            channel_user_id="111",
        )
        store.save_message(session_a.session_id, "user", "msg from A")

        session_b = store.get_or_create(
            "telegram:222",
            channel="telegram",
            channel_user_id="222",
        )
        store.save_message(session_b.session_id, "user", "msg from B")

        reloaded_a = store.get_or_create(
            "telegram:111",
            channel="telegram",
            channel_user_id="111",
        )
        reloaded_b = store.get_or_create(
            "telegram:222",
            channel="telegram",
            channel_user_id="222",
        )

        contents_a = {m.content for m in reloaded_a.messages}
        contents_b = {m.content for m in reloaded_b.messages}

        assert "msg from A" in contents_a and "msg from B" not in contents_a
        assert "msg from B" in contents_b and "msg from A" not in contents_b

    def test_same_chat_accumulates_history(self, tmp_path):
        store = SessionStore(db_path=tmp_path / "sessions.db")
        session = store.get_or_create(
            "telegram:42",
            channel="telegram",
            channel_user_id="42",
        )
        store.save_message(session.session_id, "user", "first")
        store.save_message(session.session_id, "assistant", "reply")

        reloaded = store.get_or_create(
            "telegram:42",
            channel="telegram",
            channel_user_id="42",
        )
        assert [m.content for m in reloaded.messages] == ["first", "reply"]
