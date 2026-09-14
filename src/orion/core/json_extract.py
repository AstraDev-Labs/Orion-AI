"""Tolerant JSON extraction from language-model output.

Models asked for JSON reliably return JSON *plus* something else: a fenced code
block, a leading "Here's the result:", or a trailing sentence of explanation.
A bare ``json.loads()`` on that raises ``Extra data`` and the caller silently
loses the whole response -- which is exactly how SFT synthesis in
``learning/domain_research.py`` was failing, taking the self-improvement loop
down with it while only logging a warning.

The core of the fix is ``json.JSONDecoder().raw_decode()``: it is the real
parser, so it handles nesting, escapes and brackets inside strings correctly,
and it stops cleanly at the end of the first complete value instead of
demanding that the value be the entire input. A hand-rolled balanced-bracket
scan (the earlier approach in ``agents/proactive_agent.py``) gets
``[{"note": "a ] b"}]`` wrong; this does not.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

# ```json ... ``` or a bare ``` ... ``` block. Non-greedy so several fenced
# blocks in one response are each considered separately.
_FENCED = re.compile(r"```(?:json|JSON)?\s*\n?(.*?)```", re.DOTALL)


def _first_json_value(text: str) -> Optional[Any]:
    """Decode the first complete JSON array or object in *text*.

    Anything before or after the value is ignored. Returns None when no
    position yields a parseable value.
    """
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char not in "[{":
            continue
        try:
            value, _end = decoder.raw_decode(text, index)
        except ValueError:
            continue  # A bracket inside prose -- keep looking.
        return value
    return None


def extract_json(text: str) -> Optional[Any]:
    """Pull the first JSON value out of model output, or None.

    Tried in order: the whole string, each fenced code block, then the first
    parseable value anywhere in the raw text.
    """
    if not text or not text.strip():
        return None
    stripped = text.strip()

    try:
        return json.loads(stripped)
    except ValueError:
        pass

    for match in _FENCED.finditer(text):
        value = _first_json_value(match.group(1).strip())
        if value is not None:
            return value

    return _first_json_value(stripped)


def extract_json_list(text: str) -> Optional[List[Dict[str, Any]]]:
    """``extract_json`` normalised to a list.

    A lone object becomes a one-element list, since models frequently return a
    single record where the prompt asked for an array. Returns None when
    nothing parses, so callers can tell "no JSON" from "an empty array".
    """
    value = extract_json(text)
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return None


__all__ = ["extract_json", "extract_json_list"]
