"""Live weather from Open-Meteo: current conditions and a two-day forecast.

Open-Meteo is free and needs no API key or account, so this works for every
user out of the box. Web-search snippets ("Chennai Weather Today | AccuWeather:
Check current conditions...") carry no actual numbers, and a small model kept
searching again and again for a temperature that was never in them.

Only the place name and its coordinates are sent to open-meteo.com.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_TIMEOUT = 8.0

# Countries that report weather in Fahrenheit; everywhere else uses Celsius.
_IMPERIAL_COUNTRIES = frozenset({"US", "LR", "MM", "BS", "BZ", "KY", "PW"})

# WMO weather interpretation codes, as used by Open-Meteo.
_WMO: Dict[int, str] = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "freezing fog",
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
    56: "freezing drizzle", 57: "heavy freezing drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain",
    66: "freezing rain", 67: "heavy freezing rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
    80: "light rain showers", 81: "rain showers", 82: "violent rain showers",
    85: "snow showers", 86: "heavy snow showers",
    95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with heavy hail",
}


def _get_json(url: str, params: Dict[str, Any]) -> Dict[str, Any]:
    resp = httpx.get(url, params=params, timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def geocode(location: str) -> Optional[Dict[str, Any]]:
    """Best match for a place name like "Chennai, India", or None.

    Countries and regions are not a single place to report weather for, so a
    bare country name returns None and the caller falls back to search.
    """
    parts = [p.strip() for p in (location or "").split(",") if p.strip()]
    if not parts:
        return None
    data = _get_json(_GEOCODE_URL, {"name": parts[0], "count": 5, "language": "en", "format": "json"})
    wanted = parts[0].lower()

    def _extends_the_query(name: str) -> bool:
        # The search completes prefixes: "news" -> Newsa, and "Bangalore" ->
        # Bangalore Town, a neighbourhood in Pakistan. A longer name starting
        # with the query is not the place asked for; search handles it instead.
        name = name.lower()
        return name.startswith(wanted) and name != wanted

    # Exact names first, then places matched through an alternate name.
    results = sorted(
        (r for r in (data.get("results") or []) if not _extends_the_query(str(r.get("name", "")))),
        key=lambda r: 0 if str(r.get("name", "")).lower() == wanted else 1,
    )
    if not results:
        return None
    # "Chennai, India" -> prefer a match in that country when there are several.
    hint = parts[-1].lower() if len(parts) > 1 else ""
    if hint:
        for r in results:
            if hint in (str(r.get("country", "")).lower(), str(r.get("country_code", "")).lower(), str(r.get("admin1", "")).lower()):
                return None if str(r.get("feature_code", "")).startswith("PCL") else r
    best = results[0]
    return None if str(best.get("feature_code", "")).startswith("PCL") else best


def describe(code: Any) -> str:
    try:
        return _WMO.get(int(code), "unknown conditions")
    except (TypeError, ValueError):
        return "unknown conditions"


def live_weather(location: str) -> Optional[str]:
    """A short plain-text weather report for `location`, or None if unavailable."""
    try:
        place = geocode(location)
        if not place:
            return None
        imperial = str(place.get("country_code", "")).upper() in _IMPERIAL_COUNTRIES
        params: Dict[str, Any] = {
            "latitude": place["latitude"],
            "longitude": place["longitude"],
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,precipitation,weather_code,wind_speed_10m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "timezone": "auto",
            "forecast_days": 2,
        }
        if imperial:
            params.update({"temperature_unit": "fahrenheit", "wind_speed_unit": "mph", "precipitation_unit": "inch"})
        data = _get_json(_FORECAST_URL, params)
    except Exception as exc:
        logger.debug("Live weather unavailable for %r: %s", location, exc)
        return None

    t_unit = "°F" if imperial else "°C"
    w_unit = "mph" if imperial else "km/h"
    name = ", ".join(str(p) for p in (place.get("name"), place.get("admin1"), place.get("country")) if p)
    lines = []
    cur = data.get("current") or {}
    if cur:
        lines.append(
            f"Now in {name} ({cur.get('time', '').replace('T', ' ')} local): "
            f"{cur.get('temperature_2m')}{t_unit}, feels like {cur.get('apparent_temperature')}{t_unit}, "
            f"{describe(cur.get('weather_code'))}, humidity {cur.get('relative_humidity_2m')}%, "
            f"wind {cur.get('wind_speed_10m')} {w_unit}."
        )
    daily = data.get("daily") or {}
    for i, label in enumerate(("Today", "Tomorrow")):
        try:
            lines.append(
                f"{label}: {describe(daily['weather_code'][i])}, high {daily['temperature_2m_max'][i]}{t_unit}, "
                f"low {daily['temperature_2m_min'][i]}{t_unit}, "
                f"{daily['precipitation_probability_max'][i]}% chance of rain."
            )
        except (KeyError, IndexError, TypeError):
            break
    if not lines:
        return None
    lines.append("(Live data from Open-Meteo.)")
    return "\n".join(lines)


_WEATHER_WORDS = re.compile(
    r"\b(weather|temperature|temp|forecast|rain|raining|rainfall|humid|humidity|hot|cold|sunny|cloudy|climate)\b",
    re.IGNORECASE,
)
_FILLER = frozenset(
    """what whats what's is it the a an in at for of on today todays today's tomorrow now right current
    currently live latest update updates report conditions condition like how will be going to there
    this week weekend tonight morning evening afternoon me my please tell check give show get chance
    will expected expect degrees celsius fahrenheit outside detailed hourly daily news alert alerts
    warning warnings change impact heat wave storm city area near""".split()
)
_MONTHS = frozenset(
    "january february march april may june july august september october november december "
    "jan feb mar apr jun jul aug sep sept oct nov dec".split()
)


def weather_for_query(query: str) -> Optional[str]:
    """Live weather for a search query about the weather, or None.

    "current weather in Chennai India September 14 2026" -> Chennai's report.
    The model often web-searches weather (its prompt says to search for
    anything current), so web_search answers with real numbers too.
    """
    if not query or not _WEATHER_WORDS.search(query):
        return None
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z'.-]*", query)]
    place = [
        w for w in words
        if not _WEATHER_WORDS.fullmatch(w) and w.lower() not in _FILLER and w.lower() not in _MONTHS
    ]
    if not place:
        return None
    candidates = [" ".join(place)]
    if len(place) > 1:
        candidates += [f"{' '.join(place[:-1])}, {place[-1]}", place[0]]
    for candidate in dict.fromkeys(candidates):
        report = live_weather(candidate)
        if report:
            return report
    return None


__all__ = ["live_weather", "weather_for_query", "geocode", "describe"]
