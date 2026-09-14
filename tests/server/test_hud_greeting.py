"""Greeting shown and spoken when the app opens."""

import pytest

from orion.server.hud_routes import greeting_text


@pytest.mark.parametrize(
    ("hour", "expected"),
    [(6, "Good morning"), (11, "Good morning"), (12, "Good afternoon"), (17, "Good evening"), (23, "Hello"), (3, "Hello")],
)
def test_time_of_day(hour, expected):
    assert greeting_text(hour, "Alex") == f"{expected}, Alex. I'm ready when you are."


def test_without_a_known_name():
    assert greeting_text(9, "") == "Good morning. I'm ready when you are."
