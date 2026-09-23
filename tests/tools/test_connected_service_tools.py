from __future__ import annotations

from orion.tools import notion_tools
from orion.tools.connected_service_tools import (
    ConnectedWeatherTool,
    GitHubNotificationsTool,
    GmailSearchEmailsTool,
)


def test_notion_page_create_is_verified_by_api_readback(monkeypatch):
    monkeypatch.setattr(notion_tools, "_token", lambda: "secret-test-token")
    monkeypatch.setattr(
        notion_tools,
        "_notion_api_create_page",
        lambda *a, **k: {"id": "new-page", "url": "https://notion.so/new-page"},
    )
    monkeypatch.setattr(
        notion_tools,
        "_notion_api_get_page",
        lambda *_: {
            "id": "new-page",
            "url": "https://notion.so/new-page",
            "properties": {"title": {"title": [{"plain_text": "Visit Doctor"}]}},
        },
    )
    monkeypatch.setattr(
        notion_tools,
        "_notion_api_get_blocks",
        lambda *_: [
            {
                "type": "paragraph",
                "paragraph": {"rich_text": [{"plain_text": "Call clinic at 9"}]},
            }
        ],
    )

    result = notion_tools.NotionCreatePageTool().execute(
        title="Visit Doctor", content="Call clinic at 9", parent_page_id="parent"
    )
    assert result.success
    assert result.metadata["verified"] is True
    assert "Created and verified" in result.content


def test_notion_page_create_fails_if_readback_differs(monkeypatch):
    monkeypatch.setattr(notion_tools, "_token", lambda: "secret-test-token")
    monkeypatch.setattr(
        notion_tools, "_notion_api_create_page", lambda *a, **k: {"id": "new-page"}
    )
    monkeypatch.setattr(
        notion_tools,
        "_notion_api_get_page",
        lambda *_: {
            "id": "new-page",
            "properties": {"title": {"title": [{"plain_text": "Wrong title"}]}},
        },
    )
    monkeypatch.setattr(notion_tools, "_notion_api_get_blocks", lambda *_: [])

    result = notion_tools.NotionCreatePageTool().execute(
        title="Expected", content="note", parent_page_id="parent"
    )
    assert not result.success
    assert result.metadata == {
        "page_id": "new-page",
        "url": "",
        "created": True,
        "verified": False,
    }
    assert "cannot confirm" in result.content


def test_notion_create_requires_shared_parent_id():
    result = notion_tools.NotionCreatePageTool().execute(title="A note", content="text")
    assert not result.success
    assert "shared parent page first" in result.content


def test_gmail_tool_refuses_when_inbox_is_not_connected(monkeypatch):
    class OfflineGmail:
        def __init__(self, **_kwargs):
            pass

        def is_connected(self):
            return False

    monkeypatch.setattr("orion.connectors.gmail_imap.GmailIMAPConnector", OfflineGmail)
    result = GmailSearchEmailsTool().execute(query="doctor")
    assert not result.success
    assert "app password" in result.content


def test_github_tool_reads_provider_and_returns_real_notifications(monkeypatch):
    from orion.connectors._stubs import Document

    class GitHub:
        def is_connected(self):
            return True

        def sync(self):
            yield Document(
                "n1",
                "github_notifications",
                "notification",
                "Reason: review",
                title="PR review requested",
                metadata={"repo": "orion/core", "reason": "review"},
                url="https://github.test/pr/1",
            )

    monkeypatch.setattr(
        "orion.connectors.github_notifications.GitHubNotificationsConnector", GitHub
    )
    result = GitHubNotificationsTool().execute()
    assert result.success
    assert "PR review requested" in result.content
    assert result.metadata["results"][0]["repository"] == "orion/core"


def test_weather_tool_uses_saved_city_and_provider(monkeypatch):
    from orion.connectors._stubs import Document

    class Weather:
        def is_connected(self):
            return True

        def sync(self, **kwargs):
            assert kwargs["location_override"] == "Chennai,IN"
            yield Document(
                "w1",
                "weather",
                "current",
                "Temperature: 31°C",
                title="Current Weather — Chennai",
                metadata={"location": "Chennai,IN"},
            )

    monkeypatch.setattr("orion.connectors.weather.WeatherConnector", Weather)
    result = ConnectedWeatherTool().execute(location="Chennai,IN")
    assert result.success
    assert result.metadata["location"] == "Chennai,IN"
    assert "31°C" in result.content
