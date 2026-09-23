"""Tests for query-aware tool subsetting.

These lock in the behaviour that fixed a real failure: qwen3.5:2b handed
all 44 tools called desktop-typing instead of `calculator`, but picks
correctly when the advertised list is short and relevant.
"""

from __future__ import annotations

import pytest

from orion.core.types import ToolResult
from orion.tools._stubs import BaseTool, ToolSpec
from orion.tools.tool_router import FORGE_TOOL, score_tool, select_tools


def _tool(name: str, description: str = "", category: str = "") -> BaseTool:
    class _T(BaseTool):
        tool_id = name

        @property
        def spec(self) -> ToolSpec:
            return ToolSpec(
                name=name,
                description=description,
                parameters={"type": "object", "properties": {}},
                category=category,
            )

        def execute(self, **params):
            return ToolResult(tool_name=name, success=True, content="")

    return _T()


def _names(tools):
    return [t.spec.name for t in tools]


@pytest.fixture
def catalogue():
    return [
        _tool("calculator", "Evaluate a mathematical expression."),
        _tool("web_search", "Search the web for information."),
        _tool("desktop_control", "Control the desktop, windows and wallpaper."),
        _tool("computer_control", "Move the mouse and type on the keyboard."),
        _tool("queue_action", "Queue a proposed action for user approval."),
        _tool("system_info", "Report host machine metrics."),
        _tool("obsidian_write_note", "Write a note into the vault."),
        _tool("file_read", "Read the contents of a file."),
        _tool("think", "Reason privately about a problem."),
        _tool(FORGE_TOOL, "Propose a brand-new tool when none of your tools cover it."),
    ]


class TestSelection:
    def test_explicit_tool_name_ranks_first(self, catalogue):
        sel = _names(select_tools(catalogue, "Compute 8473 * 2914 using the calculator tool.", max_tools=4))
        assert sel[0] == "calculator"

    def test_alias_surfaces_tool_its_description_never_mentions(self, catalogue):
        # queue_action's description says nothing about WhatsApp/messaging;
        # the alias map carries that knowledge from the system prompt.
        sel = _names(select_tools(catalogue, "Send a message to Sanjay on WhatsApp", max_tools=4))
        assert "queue_action" in sel

    def test_named_notion_write_beats_obsidian_and_browser_tools(self):
        # Isolate lexical ranking from registry fixtures, which intentionally
        # clear global registries between unit tests.
        tools = [
            _tool("notion_create_page", "Create a new page in Notion."),
            _tool("notion_search_pages", "Search Notion pages."),
            _tool("notion_get_page", "Read a Notion page."),
            _tool("obsidian_write_note", "Write a note into the vault."),
            _tool("obsidian_search_notes", "Search notes in the vault."),
            _tool("open_app", "Open an application or website."),
            _tool("web_search", "Search the web."),
        ]
        # Add enough unrelated tools to exercise the capped router path.
        tools.extend(_tool(f"unrelated_{i}", "Manage local desktop settings.") for i in range(12))
        selected = _names(select_tools(tools, "Save this to Notion as a new page", max_tools=6))
        assert selected[0] == "notion_create_page"

    def test_respects_max_tools(self, catalogue):
        assert len(select_tools(catalogue, "anything at all", max_tools=3)) <= 3

    def test_zero_disables_routing(self, catalogue):
        assert len(select_tools(catalogue, "x", max_tools=0)) == len(catalogue)

    def test_short_catalogue_returned_whole(self, catalogue):
        subset = catalogue[:3]
        assert len(select_tools(subset, "x", max_tools=10)) == 3

    def test_always_include_is_honoured(self, catalogue):
        sel = _names(select_tools(catalogue, "Compute 2+2 with calculator", max_tools=2, always_include=["file_read"]))
        assert "file_read" in sel


class TestForgeFallback:
    def test_offered_when_nothing_matches(self, catalogue):
        sel = _names(select_tools(catalogue, "Transpose this melody to F sharp minor", max_tools=5))
        assert FORGE_TOOL in sel

    def test_not_offered_when_a_good_match_exists(self, catalogue):
        sel = _names(select_tools(catalogue, "Compute 8473 * 2914 using the calculator tool.", max_tools=5))
        assert FORGE_TOOL not in sel

    def test_fallback_survives_being_ranked_below_the_cap(self, catalogue):
        # Regression: the forge tool sorts near-last on an unmatched query,
        # so a selection loop that breaks at max_tools never reaches it and
        # the fallback silently never fired.
        sel = _names(select_tools(catalogue, "zzzz qqqq wwww", max_tools=3))
        assert FORGE_TOOL in sel
        assert len(sel) <= 3


class TestRobustness:
    def test_empty_query_does_not_crash(self, catalogue):
        assert len(select_tools(catalogue, "", max_tools=3)) <= 3

    def test_tool_with_raising_spec_is_skipped(self, catalogue):
        class _Broken(BaseTool):
            tool_id = "broken"

            @property
            def spec(self):
                raise RuntimeError("no spec")

            def execute(self, **params):
                return ToolResult(tool_name="broken", success=False, content="")

        sel = select_tools(catalogue + [_Broken()], "calculator", max_tools=5)
        assert all(t.spec.name != "broken" for t in sel)

    def test_selection_is_deterministic(self, catalogue):
        a = _names(select_tools(catalogue, "read a file", max_tools=4))
        b = _names(select_tools(catalogue, "read a file", max_tools=4))
        assert a == b

    def test_scoring_prefers_named_tool_over_description_overlap(self, catalogue):
        q = ["calculator"]
        calc = next(t for t in catalogue if t.spec.name == "calculator")
        web = next(t for t in catalogue if t.spec.name == "web_search")
        assert score_tool(calc, q) > score_tool(web, q)


import pytest as _pytest

from orion.tools.tool_router import wants_live_data


@_pytest.mark.parametrize("query", [
    "what's the weather in Chennai right now",
    "what's my battery level",
    "latest news in India",
    "is it going to rain tomorrow",
])
def test_live_data_queries(query):
    assert wants_live_data(query)


@_pytest.mark.parametrize("query", [
    "what did I tell you about my exam",
    "what's my name",
    "send a whatsapp message to mom",
    "",
])
def test_personal_queries_keep_memory(query):
    assert not wants_live_data(query)
