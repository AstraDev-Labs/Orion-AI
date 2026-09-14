"""Tolerant JSON extraction from model output.

The regression these guard: `learning/domain_research.py` called a bare
`json.loads()` on the synthesis response. Whenever the model appended anything
after the array, that raised `Extra data`, the whole response was discarded,
and SFT synthesis returned [] -- so the self-improvement loop silently received
no training data while only logging a warning.
"""

from __future__ import annotations

from orion.core.json_extract import extract_json, extract_json_list

PAIRS = '[{"prompt": "What is Orion?", "completion": "A local-first assistant."}]'


# ---------------------------------------------------------------------------
# The production failure
# ---------------------------------------------------------------------------


def test_trailing_prose_after_the_array():
    """The exact shape that produced 'Extra data: line 1 column 336'."""
    out = extract_json_list(PAIRS + "\n\nI hope these pairs are helpful!")
    assert out is not None
    assert out[0]["prompt"] == "What is Orion?"


def test_leading_prose_before_the_array():
    out = extract_json_list("Sure! Here are the pairs you asked for:\n" + PAIRS)
    assert out is not None and len(out) == 1


def test_prose_on_both_sides():
    out = extract_json_list(f"Here you go:\n{PAIRS}\nLet me know if you need more.")
    assert out is not None and len(out) == 1


def test_bare_json_still_parses():
    assert extract_json_list(PAIRS) is not None


# ---------------------------------------------------------------------------
# Fenced blocks
# ---------------------------------------------------------------------------


def test_json_fenced_block():
    out = extract_json_list(f"```json\n{PAIRS}\n```")
    assert out is not None and len(out) == 1


def test_untagged_fenced_block():
    out = extract_json_list(f"```\n{PAIRS}\n```")
    assert out is not None and len(out) == 1


def test_fenced_block_with_commentary_around_it():
    text = f"Here is the result:\n\n```json\n{PAIRS}\n```\n\nThat covers it."
    out = extract_json_list(text)
    assert out is not None and out[0]["completion"].startswith("A local-first")


# ---------------------------------------------------------------------------
# Cases the previous balanced-bracket scan got wrong
# ---------------------------------------------------------------------------


def test_bracket_inside_a_string_value():
    """A hand-rolled bracket walk closes early here; the real parser does not."""
    text = '[{"prompt": "what does a ] do?", "completion": "it closes [ ]"}]'
    out = extract_json_list(text)
    assert out is not None
    assert out[0]["completion"] == "it closes [ ]"


def test_escaped_quotes_inside_values():
    text = '[{"prompt": "say \\"hi\\"", "completion": "hi"}]'
    out = extract_json_list(text)
    assert out is not None and out[0]["completion"] == "hi"


def test_nested_structures_survive():
    text = 'Result: [{"a": {"b": [1, 2, {"c": 3}]}}] done'
    out = extract_json_list(text)
    assert out is not None
    assert out[0]["a"]["b"][2]["c"] == 3


def test_prose_containing_a_stray_bracket_before_the_json():
    out = extract_json_list(f"See item [1] below.\n{PAIRS}")
    assert out is not None and len(out) == 1


# ---------------------------------------------------------------------------
# Shape normalisation and failure
# ---------------------------------------------------------------------------


def test_lone_object_becomes_a_list():
    out = extract_json_list('{"prompt": "p", "completion": "c"}')
    assert out == [{"prompt": "p", "completion": "c"}]


def test_empty_array_is_not_confused_with_failure():
    assert extract_json_list("[]") == []


def test_unparseable_returns_none():
    assert extract_json_list("I could not produce any pairs, sorry.") is None


def test_empty_input_returns_none():
    assert extract_json_list("") is None
    assert extract_json_list("   ") is None


def test_extract_json_preserves_scalar_shapes():
    assert extract_json('{"a": 1}') == {"a": 1}
    assert extract_json("[1, 2]") == [1, 2]


# ---------------------------------------------------------------------------
# The wrapper the proactive agent still calls
# ---------------------------------------------------------------------------


def test_proactive_agent_wrapper_delegates():
    from orion.agents.proactive_agent import _extract_json_block

    out = _extract_json_block(f"Here:\n{PAIRS}\nDone.")
    assert out is not None and out[0]["prompt"] == "What is Orion?"
