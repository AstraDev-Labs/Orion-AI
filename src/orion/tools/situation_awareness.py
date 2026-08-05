"""Situation Awareness Tool — parallel news, weather, and trending search.

When the user asks "what's happening around me" or wants a daily briefing,
J.A.R.V.I.S. calls this tool to get a fast aggregated summary.
"""

from __future__ import annotations

import concurrent.futures
import datetime
import logging
import os
from typing import Any

from orion.core.registry import ToolRegistry
from orion.core.types import ToolResult
from orion.tools._stubs import BaseTool, ToolSpec

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ddg_search(query: str, max_results: int = 4) -> str:
    """Run a DuckDuckGo search and return formatted snippet text."""
    try:
        from ddgs import DDGS
        is_news = "news" in query.lower()
        if is_news:
            results = list(DDGS().news(query, max_results=max_results))
        else:
            results = list(DDGS().text(query, max_results=max_results))

        if not results:
            return f"No results for: {query}"

        lines = []
        for r in results:
            title = r.get("title", "")
            body = r.get("body", "")
            source = r.get("source", "")
            if is_news and source:
                lines.append(f"• [{source}] {title}: {body[:250]}")
            else:
                lines.append(f"• {title}: {body[:250]}")
        return "\n".join(lines)
    except Exception as exc:
        logger.debug("DuckDuckGo search failed for '%s': %s", query, exc)
        return f"Search unavailable ({exc})"


def _tavily_search(query: str, api_key: str, max_results: int = 4) -> str:
    """Run a Tavily search and return formatted snippet text."""
    try:
        from tavily import TavilyClient
        resp = TavilyClient(api_key=api_key).search(query, max_results=max_results)
        results = resp.get("results", [])
        if not results:
            return f"No results for: {query}"
        return "\n".join(
            f"• {r.get('title', '')}: {r.get('content', '')[:200]}"
            for r in results
        )
    except Exception:
        return _ddg_search(query, max_results)


def _search(query: str, api_key: str | None = None, max_results: int = 4) -> str:
    if api_key:
        return _tavily_search(query, api_key, max_results)
    return _ddg_search(query, max_results)


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------

@ToolRegistry.register("situation_awareness")
class SituationAwarenessTool(BaseTool):
    """Aggregate news, weather, and trending info for a location briefing."""

    tool_id = "situation_awareness"
    is_local = False

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or os.environ.get("TAVILY_API_KEY")

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="situation_awareness",
            description=(
                "Get a real-time situational briefing: current news headlines, "
                "weather, and trending topics for a given location. "
                "Use this when the user asks 'what's happening around me', "
                "'give me a briefing', 'what's the news', 'daily update', etc."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": (
                            "City or region to fetch weather and local news for. "
                            "Example: 'Chennai, India' or 'New York'. "
                            "Use the user's configured location if not specified."
                        ),
                    },
                    "categories": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Categories to include. Options: 'news', 'weather', "
                            "'sports', 'tech', 'markets'. Defaults to all."
                        ),
                    },
                },
                "required": [],
            },
            category="search",
            metadata={"parallel": True},
        )

    def execute(self, **params: Any) -> ToolResult:
        location = params.get("location", "") or _default_location()
        categories = params.get("categories") or ["news", "weather", "tech", "sports"]

        now = datetime.datetime.now()
        date_str = now.strftime("%B %d, %Y")
        queries: dict[str, str] = {}

        if "news" in categories:
            queries["📰 Top News"] = f"top news headlines today {date_str} {location}"
        if "weather" in categories:
            queries["🌤️ Weather"] = f"current weather {location} today {date_str}"
        if "tech" in categories:
            queries["💻 Tech"] = f"technology news today {date_str}"
        if "sports" in categories:
            queries["⚽ Sports"] = f"sports news today {date_str} {location}"
        if "markets" in categories:
            queries["📈 Markets"] = f"stock market update today {date_str} India Sensex Nifty"

        sections: list[str] = []

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(queries)) as pool:
            future_map = {
                pool.submit(_search, q, self._api_key): label
                for label, q in queries.items()
            }
            results_ordered: dict[str, str] = {}
            for future in concurrent.futures.as_completed(future_map):
                label = future_map[future]
                try:
                    results_ordered[label] = future.result()
                except Exception as exc:
                    results_ordered[label] = f"Error: {exc}"

        # Preserve insertion order of sections
        for label in queries:
            content = results_ordered.get(label, "")
            sections.append(f"=== {label} ===\n{content}")

        briefing = (
            f"SITUATIONAL BRIEFING — {date_str}, {location}\n\n"
            + "\n\n".join(sections)
        )

        return ToolResult(
            tool_name="situation_awareness",
            content=briefing,
            success=True,
            metadata={"location": location, "categories": categories},
        )


def _default_location() -> str:
    """Try to detect location from system timezone, fallback to India."""
    try:
        import subprocess
        result = subprocess.run(
            ["powershell", "-Command",
             "(Get-TimeZone).Id"],
            capture_output=True, text=True, timeout=3
        )
        tz = result.stdout.strip()
        # Map common Windows timezone IDs to cities
        _TZ_MAP = {
            "India Standard Time": "India",
            "SE Asia Standard Time": "Southeast Asia",
            "Singapore Standard Time": "Singapore",
            "China Standard Time": "China",
            "Tokyo Standard Time": "Japan",
            "Eastern Standard Time": "New York, USA",
            "Pacific Standard Time": "Los Angeles, USA",
            "GMT Standard Time": "London, UK",
            "Central European Standard Time": "Germany",
        }
        return _TZ_MAP.get(tz, "India")
    except Exception:
        return "India"


__all__ = ["SituationAwarenessTool"]
