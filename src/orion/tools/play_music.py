"""Play music tool — launch music on Spotify, YouTube Music, YouTube, or a local player.

Supports:
- Platform selection: spotify, youtube_music, youtube, media_player
- Song/artist/query specification
- Mood-based smart playlists (happy, sad, energetic, relaxed, focus, etc.)
- Language-based music (tamil, hindi, english, telugu, etc.)
"""

from __future__ import annotations

import re
import subprocess
import sys
import urllib.parse
import urllib.request
import webbrowser
from typing import Any

from orion.core.registry import ToolRegistry
from orion.core.types import ToolResult
from orion.tools._stubs import BaseTool, ToolSpec

# Mood → search query mappings
MOOD_QUERIES: dict[str, str] = {
    "happy": "happy upbeat pop hits playlist",
    "sad": "sad emotional songs playlist",
    "energetic": "energetic workout gym songs playlist",
    "relaxed": "relaxing chill lo-fi songs playlist",
    "focus": "focus deep work concentration music playlist",
    "romantic": "romantic love songs playlist",
    "party": "party dance hits playlist",
    "morning": "morning fresh start songs playlist",
    "night": "night chill late night vibes playlist",
    "angry": "intense metal rock angry music playlist",
    "motivated": "motivational inspirational songs playlist",
    "sleepy": "sleep music calm instrumental playlist",
}

# Language-specific prefixes/searches
LANGUAGE_PREFIXES: dict[str, str] = {
    "tamil": "Tamil songs",
    "hindi": "Hindi songs",
    "telugu": "Telugu songs",
    "kannada": "Kannada songs",
    "malayalam": "Malayalam songs",
    "english": "English songs",
    "punjabi": "Punjabi songs",
    "bengali": "Bengali songs",
    "spanish": "Spanish songs",
    "korean": "K-pop Korean songs",
    "japanese": "J-pop Japanese songs",
    "french": "French songs",
}

# Spotify protocol URIs for search
SPOTIFY_SEARCH_URI = "spotify:search:{query}"
SPOTIFY_WEB_URL = "https://open.spotify.com/search/{query}"

# YouTube Music search
YT_MUSIC_URL = "https://music.youtube.com/search?q={query}"

# YouTube search
YOUTUBE_URL = "https://www.youtube.com/results?search_query={query}"

# Apple Music
APPLE_MUSIC_WEB_URL = "https://music.apple.com/search?term={query}"


def _build_query(
    song: str | None,
    artist: str | None,
    mood: str | None,
    language: str | None,
    genre: str | None,
) -> str:
    """Combine all parameters into a single search query string."""
    parts: list[str] = []

    if language:
        lang_lower = language.lower()
        lang_prefix = LANGUAGE_PREFIXES.get(lang_lower, f"{language} songs")
        parts.append(lang_prefix)

    if genre:
        parts.append(genre)

    if mood:
        mood_lower = mood.lower()
        if mood_lower in MOOD_QUERIES:
            mood_q = MOOD_QUERIES[mood_lower]
            parts.append(mood_q)
        else:
            parts.append(f"{mood} mood music")

    if artist:
        parts.append(artist)

    if song:
        parts.append(song)

    if not parts:
        parts.append("music playlist")

    return " ".join(parts)


def _spotify_app_installed() -> bool:
    """Whether a Spotify desktop app has registered the spotify: link type."""
    if sys.platform != "win32":
        return True  # open/xdg-open fail visibly elsewhere; keep old behaviour
    try:
        import winreg

        for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_CLASSES_ROOT):
            try:
                path = r"Software\Classes\spotify" if root == winreg.HKEY_CURRENT_USER else "spotify"
                winreg.CloseKey(winreg.OpenKey(root, path))
                return True
            except OSError:
                continue
    except Exception:
        pass
    return False


def youtube_first_video_id(query: str) -> str:
    """Video id of the top YouTube search result, or "" if it can't be read."""
    encoded = urllib.parse.quote(query)
    request = urllib.request.Request(
        f"https://www.youtube.com/results?search_query={encoded}",
        headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "en"},
    )
    try:
        html = urllib.request.urlopen(request, timeout=8).read().decode("utf-8", "replace")
    except Exception:
        return ""
    match = re.search(r'"videoRenderer":\{"videoId":"([\w-]{11})"', html) or re.search(
        r'"videoId":"([\w-]{11})"', html
    )
    return match.group(1) if match else ""


def _open_spotify(query: str) -> str:
    """Open Spotify with a search query."""
    encoded = urllib.parse.quote(query)

    # `start spotify:...` never raises when Spotify is missing -- Windows just
    # shows "You'll need a new app" -- so check the app is there first.
    if not _spotify_app_installed():
        webbrowser.open(SPOTIFY_WEB_URL.format(query=encoded))
        return f"Spotify app isn't installed, so opened the Spotify Web Player searching for: {query}"

    # Try Spotify URI scheme first (opens desktop app if installed)
    try:
        if sys.platform == "win32":
            subprocess.Popen(
                f'start spotify:search:{encoded}',
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        elif sys.platform == "darwin":
            subprocess.Popen(
                ["open", f"spotify:search:{encoded}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            subprocess.Popen(
                ["xdg-open", f"spotify:search:{encoded}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        return f"Opened Spotify searching for: {query}"
    except Exception:
        # Fall back to Spotify web
        url = SPOTIFY_WEB_URL.format(query=encoded)
        webbrowser.open(url)
        return f"Opened Spotify Web Player searching for: {query}"


def _open_youtube(query: str) -> str:
    """Open YouTube and force autoplay the first search result."""
    encoded = urllib.parse.quote(query)
    video_id = youtube_first_video_id(query)
    if video_id:
        webbrowser.open(f"https://www.youtube.com/watch?v={video_id}&autoplay=1")
        return f"Playing the top YouTube result for: {query}"
    # Fallback to search
    url = YOUTUBE_URL.format(query=encoded)
    webbrowser.open(url)
    return f"Opened YouTube searching for: {query}"


def _open_youtube_music(query: str) -> str:
    """Open YouTube Music and force autoplay the first search result."""
    encoded = urllib.parse.quote(query)
    video_id = youtube_first_video_id(query)
    if video_id:
        webbrowser.open(f"https://music.youtube.com/watch?v={video_id}&autoplay=1")
        return f"Playing the top YouTube Music result for: {query}"
    # Fallback to search
    url = YT_MUSIC_URL.format(query=encoded)
    webbrowser.open(url)
    return f"Opened YouTube Music searching for: {query}"


def _open_apple_music(query: str) -> str:
    """Open Apple Music's web search for the query."""
    encoded = urllib.parse.quote(query)
    url = APPLE_MUSIC_WEB_URL.format(query=encoded)
    webbrowser.open(url)
    return f"Opened Apple Music searching for: {query}"


def _open_media_player(query: str) -> str:
    """Open Windows Media Player or system media player."""
    if sys.platform == "win32":
        # Search Music folder for matching files first
        import os
        from pathlib import Path

        music_dir = Path.home() / "Music"
        words = [w for w in query.lower().split() if len(w) > 2 and w not in {"the", "and", "song", "music"}]
        matched_file: str | None = None
        if music_dir.exists() and words:
            best = 0
            for f in music_dir.rglob("*"):
                if f.suffix.lower() not in {".mp3", ".flac", ".wav", ".m4a", ".ogg", ".aac", ".wma"}:
                    continue
                name = f.stem.lower()
                hits = sum(1 for w in words if w in name)
                # Every distinctive word must match: "any word" played the
                # first file containing e.g. "love" for any love song.
                if hits == len(words) and hits > best:
                    best, matched_file = hits, str(f)

        if matched_file:
            # The file's default player: Windows 11 no longer ships the
            # legacy wmplayer that `start wmplayer` relied on.
            os.startfile(matched_file)  # type: ignore[attr-defined]
            return f"Playing '{Path(matched_file).name}' from your Music folder."
        if not music_dir.exists() or not any(music_dir.rglob("*.*")):
            return "Your Music folder has no songs. Try YouTube Music or Spotify instead."
        return (
            f"No song matching '{query}' in your Music folder. "
            "Try a different title, or play it from YouTube Music or Spotify."
        )
    else:
        return "Local media player is only supported on Windows. Use spotify or youtube instead."


@ToolRegistry.register("play_music")
class PlayMusicTool(BaseTool):
    """Launch music on Spotify, YouTube Music, YouTube, or local media player."""

    tool_id = "play_music"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="play_music",
            description=(
                "Play music on a specified platform (spotify, youtube_music, youtube, apple_music, media_player).\n"
                "Can search for a specific song/artist, a mood-based playlist (happy, sad, energetic, etc.),\n"
                "or a language-based playlist (tamil, hindi, english, korean, etc.).\n"
                "Use this tool whenever the user asks to play, start, or listen to music."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "platform": {
                        "type": "string",
                        "description": (
                            "Music platform to use. "
                            "Options: spotify, youtube_music, youtube, apple_music, media_player. "
                            "Default is youtube_music if not specified."
                        ),
                        "enum": ["spotify", "youtube_music", "youtube", "apple_music", "media_player"],
                    },
                    "song": {
                        "type": "string",
                        "description": "Specific song title to search for.",
                    },
                    "artist": {
                        "type": "string",
                        "description": "Artist or band name.",
                    },
                    "mood": {
                        "type": "string",
                        "description": (
                            "User's mood or desired vibe. "
                            "E.g: happy, sad, energetic, relaxed, focus, romantic, party, morning, night, angry, motivated, sleepy."
                        ),
                    },
                    "language": {
                        "type": "string",
                        "description": (
                            "Language for music. "
                            "E.g: tamil, hindi, english, telugu, kannada, malayalam, punjabi, korean, japanese."
                        ),
                    },
                    "genre": {
                        "type": "string",
                        "description": "Music genre. E.g: pop, rock, classical, jazz, hip-hop, lo-fi, metal.",
                    },
                },
                "required": [],
            },
            category="media",
            requires_confirmation=False,
            timeout_seconds=10.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        platform = (params.get("platform") or "youtube_music").lower().strip()
        song = params.get("song", "") or ""
        artist = params.get("artist", "") or ""
        mood = params.get("mood", "") or ""
        language = params.get("language", "") or ""
        genre = params.get("genre", "") or ""

        # If platform contains platform names in the string, normalise
        if "spotify" in platform:
            platform = "spotify"
        elif "apple" in platform or "applemusic" in platform or "itunes" in platform:
            platform = "apple_music"
        elif "youtube_music" in platform or "ytmusic" in platform or "yt music" in platform:
            platform = "youtube_music"
        elif "youtube" in platform or "yt" in platform:
            platform = "youtube"
        elif "media" in platform or "player" in platform or "wmplayer" in platform:
            platform = "media_player"

        query = _build_query(
            song=song or None,
            artist=artist or None,
            mood=mood or None,
            language=language or None,
            genre=genre or None,
        )

        try:
            if platform == "spotify":
                msg = _open_spotify(query)
            elif platform == "apple_music":
                msg = _open_apple_music(query)
            elif platform == "youtube":
                msg = _open_youtube(query)
            elif platform == "media_player":
                msg = _open_media_player(query)
            else:
                # Default: YouTube Music
                msg = _open_youtube_music(query)

            return ToolResult(
                tool_name="play_music",
                content=msg,
                success=True,
                metadata={"platform": platform, "query": query},
            )
        except Exception as exc:
            return ToolResult(
                tool_name="play_music",
                content=f"Failed to play music: {exc}",
                success=False,
            )


__all__ = ["PlayMusicTool"]
