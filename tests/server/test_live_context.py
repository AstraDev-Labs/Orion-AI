"""Tests for per-turn live context (clock, user name, greeting rules)."""

from __future__ import annotations

from orion.server.live_context import (
    build_live_context,
    capture_name,
    is_short_social_turn,
    user_name,
)
from orion.tools.tool_router import is_conversational


def test_capture_and_recall_name(tmp_path):
    path = tmp_path / "USER.md"
    assert user_name(path) == ""
    assert capture_name("hey, my name is alex", path) == "Alex"
    assert user_name(path) == "Alex"
    assert capture_name("actually call me Tarun", path) == "Tarun"
    assert user_name(path) == "Tarun"
    assert path.read_text(encoding="utf-8").count("Name:") == 1


def test_non_names_are_ignored(tmp_path):
    path = tmp_path / "USER.md"
    assert capture_name("call me later", path) == ""
    assert capture_name("I'm fine thanks", path) == ""
    assert capture_name("my name is Orion", path) == ""
    assert not path.exists()


def test_existing_profile_entries_are_kept(tmp_path):
    path = tmp_path / "USER.md"
    path.write_text("- Likes: chess\n", encoding="utf-8")
    capture_name("my name is Alex", path)
    text = path.read_text(encoding="utf-8")
    assert "Likes: chess" in text and "Name: Alex" in text


def test_context_has_clock_and_greeting_rules(tmp_path):
    path = tmp_path / "USER.md"
    first = build_live_context("hello", first_turn=True, path=path)
    assert "Local date and time" in first
    assert "ask what you should call them" in first
    later = build_live_context("and then?", first_turn=False, path=path)
    assert "do NOT greet again" in later


def test_context_uses_known_name(tmp_path):
    path = tmp_path / "USER.md"
    path.write_text("- Name: Alex\n", encoding="utf-8")
    note = build_live_context("how are you", first_turn=False, path=path)
    assert "The user's name is Alex" in note
    assert "never call the user Orion" in note


def test_short_social_context_is_minimal_and_profile_name_is_normalized(tmp_path):
    path = tmp_path / "USER.md"
    path.write_text("- Name: YOGARaj\n", encoding="utf-8")

    note = build_live_context("Hi!", first_turn=True, path=path, brief_social=True)

    assert user_name(path) == "Yogaraj"
    assert "Local date and time" not in note
    assert "Operating system" not in note
    assert "only a name" in note
    assert "Yogaraj" in note
    assert "addressing you" in note


def test_short_social_turn_detection_is_narrow():
    assert is_short_social_turn("Hi")
    assert is_short_social_turn("good evening, Orion!")
    assert is_short_social_turn("How are you?")
    assert not is_short_social_turn("What time is it?")
    assert not is_short_social_turn("Hi, open Chrome")


def test_conversational_detection():
    assert is_conversational("Hey Orion, can you hear me?")
    assert is_conversational("my name is Alex")
    assert not is_conversational("open google on my desktop")
    assert not is_conversational("what time is it")
    assert not is_conversational("install steam")


def test_normalize_spoken_emails():
    from orion.server.live_context import normalize_transcript

    assert normalize_transcript("Send an email to 12345678 at example.edu, saying hi.") == (
        "Send an email to 12345678@example.edu, saying hi."
    )
    assert normalize_transcript("email alex at gmail dot com") == "email alex@gmail.com"
    assert normalize_transcript("look at google.com") == "look at google.com"
    assert normalize_transcript("meet at 5.30 tomorrow") == "meet at 5.30 tomorrow"
    assert normalize_transcript("can you hear me") == "can you hear me"


def test_speech_prompt_includes_name(tmp_path):
    from orion.server.live_context import speech_prompt

    path = tmp_path / "USER.md"
    assert "Orion" in speech_prompt(path) and "name is" not in speech_prompt(path)
    path.write_text("- Name: Alex\n", encoding="utf-8")
    assert "The user's name is Alex." in speech_prompt(path)


def test_misheard_phrases_are_not_saved_as_names(tmp_path):
    path = tmp_path / "USER.md"
    for phrase in ["call me? Not me.", "my name is not important", "you can call me anything", "call me Orion"]:
        assert capture_name(phrase, path) == "", phrase
    assert not path.exists()
    assert capture_name("My name is Alex Kumar", path) == "Alex Kumar"


def test_prompt_echo_is_detected():
    from orion.server.live_context import is_prompt_echo, speech_prompt

    prompt = "Conversation with Orion, a voice assistant. The user's name is Alex. Email addresses are written like 12345678@college.edu.in or name@gmail.com."
    assert is_prompt_echo("The user's name is Alex. Email addresses are written like 12345678.", prompt)
    assert not is_prompt_echo("Hey Orion, can you hear me?", prompt)
    assert not is_prompt_echo("Send an email to 12345678@example.edu", prompt)
    assert not is_prompt_echo("yes", prompt)
