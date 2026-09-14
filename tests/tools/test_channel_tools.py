"""Tests for channel MCP tools — ChannelSendTool, ChannelListTool, ChannelStatusTool."""

from __future__ import annotations

import pytest

from orion.channels._stubs import (
    BaseChannel,
    ChannelHandler,
    ChannelStatus,
)
from orion.mcp.server import MCPServer
from orion.tools.channel_tools import (
    ChannelListTool,
    ChannelSendTool,
    ChannelStatusTool,
)


class _MockChannel(BaseChannel):
    """In-memory channel implementation for testing."""

    channel_id = "mock"

    def __init__(self):
        self._sent: list[dict] = []
        self._status = ChannelStatus.CONNECTED
        self._handlers: list[ChannelHandler] = []

    def connect(self) -> None:
        self._status = ChannelStatus.CONNECTED

    def disconnect(self) -> None:
        self._status = ChannelStatus.DISCONNECTED

    def send(self, channel, content, *, conversation_id="", metadata=None) -> bool:
        self._sent.append(
            {
                "channel": channel,
                "content": content,
                "conversation_id": conversation_id,
            }
        )
        return True

    def status(self) -> ChannelStatus:
        return self._status

    def list_channels(self) -> list[str]:
        return ["mock-channel-1", "mock-channel-2"]

    def on_message(self, handler) -> None:
        self._handlers.append(handler)


class _FailingChannel(_MockChannel):
    """Channel that always fails to send."""

    def send(self, channel, content, *, conversation_id="", metadata=None) -> bool:
        return False


class _ErrorChannel(_MockChannel):
    """Channel that raises exceptions."""

    def send(self, channel, content, *, conversation_id="", metadata=None) -> bool:
        raise RuntimeError("Connection lost")

    def list_channels(self) -> list[str]:
        raise RuntimeError("Connection lost")

    def status(self) -> ChannelStatus:
        raise RuntimeError("Connection lost")


@pytest.fixture
def channel():
    return _MockChannel()


@pytest.fixture
def approvals(tmp_path, monkeypatch):
    from orion.channels import live
    from orion.tools import proactive_tools
    from orion.tools.approval_store import ApprovalStore

    store = ApprovalStore(str(tmp_path / "approvals.db"))
    monkeypatch.setattr(proactive_tools, "_store", store)
    live.clear_live_channels()
    yield store
    live.clear_live_channels()


class TestChannelSendTool:
    """channel_send drafts; nothing is sent until the user approves."""

    def test_spec(self):
        tool = ChannelSendTool()
        assert tool.spec.name == "channel_send"
        assert tool.spec.category == "channel"
        assert "channel" in tool.spec.parameters["required"]
        assert "content" in tool.spec.parameters["required"]

    def test_send_is_queued_not_sent(self, channel, approvals):
        tool = ChannelSendTool(channel)
        result = tool.execute(channel="919876543210", content="Hello!", platform="whatsapp")
        assert result.success is True
        assert "Nothing sent yet" in result.content
        assert channel._sent == []
        pending = approvals.list_pending()
        assert len(pending) == 1
        assert pending[0].action_type == "channel_send"
        assert pending[0].payload == {"platform": "whatsapp", "target": "919876543210", "content": "Hello!"}

    def test_platform_defaults_to_connected_channel(self, approvals):
        from orion.channels import live

        live.register_live_channel("telegram", _MockChannel())
        ChannelSendTool().execute(channel="chat-123", content="Hi")
        assert approvals.list_pending()[0].payload["platform"] == "telegram"

    def test_approved_draft_is_sent_on_live_channel(self, approvals):
        from orion.channels import live
        from orion.tools.proactive_tools import ExecutePendingActionsTool, parse_approval_response

        mock = _MockChannel()
        live.register_live_channel("telegram", mock)
        ChannelSendTool().execute(channel="chat-123", content="Hi there", platform="telegram")
        assert parse_approval_response("yes, send it", store=approvals)[0]["approved"]
        ExecutePendingActionsTool(store=approvals).execute()
        assert mock._sent and mock._sent[0]["content"] == "Hi there"

    def test_missing_params(self, channel, approvals):
        tool = ChannelSendTool(channel)
        result = tool.execute()
        assert result.success is False
        assert "required" in result.content

    def test_missing_content(self, channel, approvals):
        tool = ChannelSendTool(channel)
        result = tool.execute(channel="chat-123")
        assert result.success is False
        assert approvals.list_pending() == []

    def test_tool_id(self):
        assert ChannelSendTool.tool_id == "channel_send"


class TestChannelListTool:
    def test_spec(self):
        tool = ChannelListTool()
        assert tool.spec.name == "channel_list"
        assert tool.spec.category == "channel"

    def test_list_success(self, channel):
        tool = ChannelListTool(channel)
        result = tool.execute()
        assert result.success is True
        assert "mock-channel-1" in result.content
        assert "mock-channel-2" in result.content

    def test_no_backend(self, approvals):
        tool = ChannelListTool()
        result = tool.execute()
        assert "No messaging app is connected" in result.content

    def test_error_handling(self):
        tool = ChannelListTool(_ErrorChannel())
        result = tool.execute()
        assert result.success is False
        assert "List error" in result.content

    def test_tool_id(self):
        assert ChannelListTool.tool_id == "channel_list"


class TestChannelStatusTool:
    def test_spec(self):
        tool = ChannelStatusTool()
        assert tool.spec.name == "channel_status"
        assert tool.spec.category == "channel"

    def test_status_success(self, channel):
        tool = ChannelStatusTool(channel)
        result = tool.execute()
        assert result.success is True
        assert "connected" in result.content

    def test_no_backend(self, approvals):
        tool = ChannelStatusTool()
        result = tool.execute()
        assert "No messaging app is connected" in result.content

    def test_error_handling(self):
        tool = ChannelStatusTool(_ErrorChannel())
        result = tool.execute()
        assert result.success is False
        assert "Status error" in result.content

    def test_tool_id(self):
        assert ChannelStatusTool.tool_id == "channel_status"


class TestChannelToolsMCPDiscovery:
    def test_auto_discover_finds_channel_tools(self):
        """MCPServer auto-discovery finds channel tools."""
        server = MCPServer()
        from orion.mcp.protocol import MCPRequest

        req = MCPRequest(method="tools/list", id=1)
        resp = server.handle(req)
        names = {t["name"] for t in resp.result["tools"]}
        assert "channel_send" in names
        assert "channel_list" in names
        assert "channel_status" in names

    def test_channel_tool_annotations(self):
        """Channel tools have correct MCP annotations."""
        server = MCPServer()
        from orion.mcp.protocol import MCPRequest

        req = MCPRequest(method="tools/list", id=1)
        resp = server.handle(req)
        tools_by_name = {t["name"]: t for t in resp.result["tools"]}

        send_tool = tools_by_name.get("channel_send", {})
        assert send_tool.get("annotations", {}).get("destructiveHint") is True

        list_tool = tools_by_name.get("channel_list", {})
        assert list_tool.get("annotations", {}).get("readOnlyHint") is True
