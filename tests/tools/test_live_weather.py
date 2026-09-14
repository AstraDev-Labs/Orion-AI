"""Live weather (Open-Meteo) report building, with the network mocked."""

from __future__ import annotations

import pytest

from orion.tools import live_weather as lw

_CHENNAI = {
    "name": "Chennai", "admin1": "Tamil Nadu", "country": "India", "country_code": "IN",
    "latitude": 13.08, "longitude": 80.27, "feature_code": "PPLA",
}
_FORECAST = {
    "current": {"time": "2026-09-14T02:15", "temperature_2m": 28.2, "apparent_temperature": 34.4,
                "relative_humidity_2m": 87, "weather_code": 95, "wind_speed_10m": 6.7},
    "daily": {"weather_code": [95, 51], "temperature_2m_max": [31.1, 32.2],
              "temperature_2m_min": [25.4, 25.9], "precipitation_probability_max": [90, 65]},
}


def _fake(responses, calls):
    def get(url, params):
        calls.append((url, dict(params)))
        return responses[url]
    return get


def test_report_has_real_numbers(monkeypatch):
    calls = []
    monkeypatch.setattr(lw, "_get_json", _fake({lw._GEOCODE_URL: {"results": [_CHENNAI]}, lw._FORECAST_URL: _FORECAST}, calls))
    report = lw.live_weather("Chennai, India")
    assert "28.2°C" in report and "thunderstorm" in report
    assert "high 31.1°C" in report and "90% chance of rain" in report
    assert "Tomorrow: light drizzle" in report
    assert calls[0][1]["name"] == "Chennai"
    assert "temperature_unit" not in calls[1][1]  # Celsius outside the US


def test_fahrenheit_for_the_us(monkeypatch):
    place = dict(_CHENNAI, name="Austin", admin1="Texas", country="United States", country_code="US")
    calls = []
    monkeypatch.setattr(lw, "_get_json", _fake({lw._GEOCODE_URL: {"results": [place]}, lw._FORECAST_URL: _FORECAST}, calls))
    report = lw.live_weather("Austin, Texas")
    assert calls[1][1]["temperature_unit"] == "fahrenheit"
    assert "°F" in report and "mph" in report


def test_prefers_the_named_country(monkeypatch):
    elsewhere = dict(_CHENNAI, country="United States", country_code="US", admin1="Ohio")
    monkeypatch.setattr(lw, "_get_json", _fake({lw._GEOCODE_URL: {"results": [elsewhere, _CHENNAI]}, lw._FORECAST_URL: _FORECAST}, []))
    assert "Tamil Nadu, India" in lw.live_weather("Chennai, India")


@pytest.mark.parametrize("results", [[], [dict(_CHENNAI, name="India", feature_code="PCLI")]])
def test_unknown_place_or_country_gives_none(monkeypatch, results):
    monkeypatch.setattr(lw, "_get_json", _fake({lw._GEOCODE_URL: {"results": results}}, []))
    assert lw.live_weather("India") is None


def test_network_failure_gives_none(monkeypatch):
    def boom(url, params):
        raise OSError("offline")
    monkeypatch.setattr(lw, "_get_json", boom)
    assert lw.live_weather("Chennai, India") is None


def test_situation_awareness_uses_live_weather_without_searching(monkeypatch):
    from orion.tools import situation_awareness as sa

    monkeypatch.setattr(lw, "live_weather", lambda location: "Now in Chennai: 28.2°C")
    searched = []
    monkeypatch.setattr(sa, "_search", lambda q, *a, **k: searched.append(q) or "• result")
    result = sa.SituationAwarenessTool().execute(location="Chennai, India", categories=["weather"])
    assert "28.2°C" in result.content
    assert searched == []


@pytest.mark.parametrize(("query", "completion"), [("news", "Newsa"), ("Bangalore", "Bangalore Town")])
def test_prefix_completions_are_not_the_place(monkeypatch, query, completion):
    place = dict(_CHENNAI, name=completion)
    monkeypatch.setattr(lw, "_get_json", _fake({lw._GEOCODE_URL: {"results": [place]}}, []))
    assert lw.geocode(query) is None


def test_weather_for_query_extracts_the_place(monkeypatch):
    asked = []
    monkeypatch.setattr(lw, "live_weather", lambda loc: asked.append(loc) or ("report" if loc == "Chennai India" else None))
    assert lw.weather_for_query("current weather in Chennai India September 14 2026") == "report"
    assert asked[0] == "Chennai India"


def test_non_weather_queries_are_left_to_search(monkeypatch):
    monkeypatch.setattr(lw, "live_weather", lambda loc: pytest.fail("should not look up weather"))
    assert lw.weather_for_query("latest iphone price") is None


def test_web_search_answers_weather_with_live_data(monkeypatch):
    from orion.tools.web_search import WebSearchTool

    monkeypatch.setattr(lw, "weather_for_query", lambda q: "Now in Chennai: 28.0°C")
    result = WebSearchTool().execute(query="weather in Chennai today")
    assert result.success and "28.0°C" in result.content
    assert result.metadata["mode"] == "live_weather"
