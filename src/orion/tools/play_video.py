"""Play video tool — launch TV shows and movies on streaming platforms.

Supports:
- Platforms: netflix, apple_tv, prime_video, disney_plus, hulu, crunchyroll, youtube
- Title (movie/show name)
"""

from __future__ import annotations

import subprocess
import sys
import urllib.parse
import webbrowser
from typing import Any

from orion.core.registry import ToolRegistry
from orion.core.types import ToolResult
from orion.tools._stubs import BaseTool, ToolSpec

# Search URL patterns for different platforms
PLATFORM_URLS: dict[str, str] = {
    "netflix": "https://www.netflix.com/search?q={query}",
    "apple_tv": "https://tv.apple.com/search?q={query}",
    "prime_video": "https://www.primevideo.com/search/ref=atv_sr_sug_4?phrase={query}",
    "disney_plus": "https://www.disneyplus.com/search?q={query}",
    "hulu": "https://www.hulu.com/search?q={query}",
    "crunchyroll": "https://www.crunchyroll.com/search?q={query}",
    "youtube": "https://www.youtube.com/results?search_query={query}",
}


def _build_query(title: str | None, genre: str | None) -> str:
    """Combine parameters into a single search query string."""
    parts: list[str] = []

    if title:
        parts.append(title)

    if genre:
        parts.append(f"{genre} movies and shows")

    if not parts:
        parts.append("movies")

    return " ".join(parts)


def _open_platform(platform: str, query: str) -> str:
    """Open the specified platform with a search query."""
    encoded = urllib.parse.quote(query)

    # Check if we should try a native Windows URI first
    if platform == "apple_tv":
        try:
            if sys.platform == "win32":
                subprocess.Popen(
                    ['powershell', '-Command', f'Start-Process "videos://search?term={encoded}"'],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return f"Opened Apple TV searching for: {query}"
        except Exception:
            pass # Fall through to web

    # Default behavior for streaming platforms: Open in browser
    # The browser will automatically trigger the PWA/installed app if registered.
    url_template = PLATFORM_URLS.get(platform)
    if not url_template:
        raise ValueError(f"Unknown platform: {platform}")

    url = url_template.format(query=encoded)
    webbrowser.open(url)

    friendly_names = {
        "netflix": "Netflix",
        "apple_tv": "Apple TV",
        "prime_video": "Amazon Prime Video",
        "disney_plus": "Disney+",
        "hulu": "Hulu",
        "crunchyroll": "Crunchyroll",
        "youtube": "YouTube",
    }

    name = friendly_names.get(platform, platform)
    return f"Opened {name} searching for: {query}"


@ToolRegistry.register("play_video")
class PlayVideoTool(BaseTool):
    """Launch movies and TV shows on streaming platforms."""

    tool_id = "play_video"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="play_video",
            description=(
                "Play or search for video content (movies, TV shows, anime) on a specified streaming platform.\n"
                "Supported platforms: netflix, apple_tv, prime_video, disney_plus, hulu, crunchyroll, youtube.\n"
                "Use this tool whenever the user asks to watch a movie, TV show, or open a video streaming app."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "platform": {
                        "type": "string",
                        "description": (
                            "Video streaming platform to use. "
                            "Options: netflix, apple_tv, prime_video, disney_plus, hulu, crunchyroll, youtube. "
                            "Default is netflix if not specified."
                        ),
                        "enum": ["netflix", "apple_tv", "prime_video", "disney_plus", "hulu", "crunchyroll", "youtube"],
                    },
                    "title": {
                        "type": "string",
                        "description": "Specific movie or TV show title to search for.",
                    },
                    "genre": {
                        "type": "string",
                        "description": "Video genre. E.g: action, comedy, sci-fi, horror, documentary, anime.",
                    },
                },
                "required": [],
            },
            category="media",
            requires_confirmation=False,
            timeout_seconds=10.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        platform = (params.get("platform") or "netflix").lower().strip()
        title = params.get("title", "") or ""
        genre = params.get("genre", "") or ""

        # Normalise platform names
        if "netflix" in platform:
            platform = "netflix"
        elif "apple" in platform or "tv" in platform:
            platform = "apple_tv"
        elif "prime" in platform or "amazon" in platform:
            platform = "prime_video"
        elif "disney" in platform or "hotstar" in platform:
            platform = "disney_plus"
        elif "hulu" in platform:
            platform = "hulu"
        elif "crunchy" in platform or "anime" in platform:
            platform = "crunchyroll"
        elif "youtube" in platform or "yt" in platform:
            platform = "youtube"

        query = _build_query(
            title=title or None,
            genre=genre or None,
        )

        try:
            msg = _open_platform(platform, query)
            return ToolResult(
                tool_name="play_video",
                content=msg,
                success=True,
                metadata={"platform": platform, "query": query},
            )
        except Exception as exc:
            return ToolResult(
                tool_name="play_video",
                content=f"Failed to launch video platform: {exc}",
                success=False,
            )


__all__ = ["PlayVideoTool"]
