"""Direct read actions for connected email, GitHub and weather providers."""

from __future__ import annotations

from typing import Any

from orion.core.registry import ToolRegistry
from orion.core.types import ToolResult
from orion.tools._stubs import BaseTool, ToolSpec


@ToolRegistry.register("gmail_search_emails")
class GmailSearchEmailsTool(BaseTool):
    """Search recent messages from the Gmail IMAP connection."""

    tool_id = "gmail_search_emails"
    is_local = False

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description=(
                "Search the most recent 50 Gmail messages using the Email connection's Gmail app password. "
                "Returns matching subject, sender, date, and a short snippet. This is read-only."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Text to find in recent Gmail messages.",
                    },
                    "max_results": {
                        "type": "integer",
                        "default": 10,
                        "minimum": 1,
                        "maximum": 50,
                    },
                },
                "required": ["query"],
            },
            category="communication",
            required_capabilities=["network:fetch"],
            timeout_seconds=60.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        query = str(params.get("query", "")).strip().casefold()
        if not query:
            return ToolResult(
                tool_name=self.tool_id,
                content="Enter text to search for in Gmail.",
                success=False,
            )
        try:
            from orion.connectors.gmail_imap import GmailIMAPConnector

            connector = GmailIMAPConnector(max_messages=50)
            if not connector.is_connected():
                return ToolResult(
                    tool_name=self.tool_id,
                    content="Gmail inbox search needs a Gmail address and app password in Connections. This does not use an unrelated email provider's SMTP login.",
                    success=False,
                )
            words = [word for word in query.split() if len(word) > 1]
            found = []
            for doc in connector.sync():
                searchable = f"{doc.title}\n{doc.author}\n{doc.content}".casefold()
                if all(word in searchable for word in words):
                    found.append(doc)
                    if len(found) >= min(
                        max(int(params.get("max_results", 10)), 1), 50
                    ):
                        break
            if not found:
                return ToolResult(
                    tool_name=self.tool_id,
                    content="No matching messages found among the 50 most recent Gmail messages checked.",
                    success=True,
                    metadata={"searched_recent": 50, "results": []},
                )
            rows = [
                {
                    "subject": d.title,
                    "from": d.author,
                    "date": d.timestamp.isoformat(),
                    "snippet": d.content[:500],
                    "message_id": d.metadata.get("message_id", ""),
                }
                for d in found
            ]
            text = "\n\n".join(
                f"{r['subject']} — {r['from']} — {r['date']}\n{r['snippet']}"
                for r in rows
            )
            return ToolResult(
                tool_name=self.tool_id,
                content=text,
                success=True,
                metadata={"searched_recent": 50, "results": rows},
            )
        except Exception as exc:
            return ToolResult(
                tool_name=self.tool_id,
                content=f"Gmail search failed: {exc}",
                success=False,
            )


@ToolRegistry.register("github_notifications")
class GitHubNotificationsTool(BaseTool):
    """Read the current user's GitHub notifications."""

    tool_id = "github_notifications"
    is_local = False

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Fetch recent GitHub notifications from the connected personal access token. Read-only.",
            parameters={
                "type": "object",
                "properties": {
                    "max_results": {
                        "type": "integer",
                        "default": 20,
                        "minimum": 1,
                        "maximum": 50,
                    }
                },
            },
            category="knowledge",
            required_capabilities=["network:fetch"],
            timeout_seconds=45.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            from orion.connectors.github_notifications import (
                GitHubNotificationsConnector,
            )

            connector = GitHubNotificationsConnector()
            if not connector.is_connected():
                return ToolResult(
                    tool_name=self.tool_id,
                    content="GitHub notifications are not configured. Add a read-only notifications token in Connections.",
                    success=False,
                )
            limit = min(max(int(params.get("max_results", 20)), 1), 50)
            docs = []
            for doc in connector.sync():
                docs.append(doc)
                if len(docs) >= limit:
                    break
            if not docs:
                return ToolResult(
                    tool_name=self.tool_id,
                    content="No GitHub notifications were returned.",
                    success=True,
                    metadata={"results": []},
                )
            rows = [
                {
                    "title": d.title,
                    "repository": d.metadata.get("repo", ""),
                    "reason": d.metadata.get("reason", ""),
                    "url": d.url,
                }
                for d in docs
            ]
            text = "\n".join(
                f"{r['title']} — {r['repository']} ({r['reason']}) {r['url'] or ''}"
                for r in rows
            )
            return ToolResult(
                tool_name=self.tool_id,
                content=text,
                success=True,
                metadata={"results": rows},
            )
        except Exception as exc:
            return ToolResult(
                tool_name=self.tool_id,
                content=f"GitHub notifications failed: {exc}",
                success=False,
            )


@ToolRegistry.register("weather")
class ConnectedWeatherTool(BaseTool):
    """Fetch conditions and forecast from the saved Weather connection."""

    tool_id = "weather"
    is_local = False

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Get current weather and short forecast from the Weather connection's saved city and OpenWeatherMap API key.",
            parameters={
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "Optional city override, such as Chennai,IN.",
                    }
                },
            },
            category="search",
            required_capabilities=["network:fetch"],
            timeout_seconds=45.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            from orion.connectors.weather import WeatherConnector

            connector = WeatherConnector()
            if not connector.is_connected():
                return ToolResult(
                    tool_name=self.tool_id,
                    content="Weather is not configured. Add an OpenWeatherMap key in Connections.",
                    success=False,
                )
            override = str(params.get("location", "")).strip()
            docs = list(connector.sync(location_override=override))
            if not docs:
                return ToolResult(
                    tool_name=self.tool_id,
                    content="The Weather provider returned no current conditions or forecast.",
                    success=False,
                )
            text = "\n\n".join(f"{doc.title}\n{doc.content}" for doc in docs)
            return ToolResult(
                tool_name=self.tool_id,
                content=text,
                success=True,
                metadata={"location": docs[0].metadata.get("location", "")},
            )
        except Exception as exc:
            return ToolResult(
                tool_name=self.tool_id,
                content=f"Weather lookup failed: {exc}",
                success=False,
            )


__all__ = ["ConnectedWeatherTool", "GmailSearchEmailsTool", "GitHubNotificationsTool"]
