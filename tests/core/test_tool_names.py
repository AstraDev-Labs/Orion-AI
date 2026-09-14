"""Which tools the agent gets from [agent] tools."""

from orion.core.tool_names import (
    INTERNAL_TOOLS,
    configured_tool_list,
    enabled_tool_names,
    serialize_tool_list,
)

REGISTERED = ["calculator", "play_music", "record_decision", "web_search", "docker_shell_exec"]


def test_unset_enables_every_tool_but_internal_ones():
    # A fresh install used to get only calculator and web_search.
    assert enabled_tool_names("", REGISTERED) == ["calculator", "play_music", "web_search"]
    assert not INTERNAL_TOOLS & set(enabled_tool_names("", REGISTERED))


def test_explicit_list_is_exact():
    assert enabled_tool_names("web_search, calculator", REGISTERED) == ["calculator", "web_search"]
    assert enabled_tool_names(["play_music"], REGISTERED) == ["play_music"]


def test_internal_tools_stay_off_even_if_listed():
    assert enabled_tool_names("record_decision,calculator", REGISTERED) == ["calculator"]


def test_none_means_no_tools():
    assert enabled_tool_names("none", REGISTERED) == []
    assert configured_tool_list("none") == []


def test_switching_off_the_last_tool_does_not_mean_all():
    value = serialize_tool_list([])
    assert value == "none"
    assert enabled_tool_names(value, REGISTERED) == []


def test_configured_list_none_for_unset():
    assert configured_tool_list("") is None
    assert configured_tool_list([]) is None
    assert configured_tool_list(" a , b ") == ["a", "b"]
