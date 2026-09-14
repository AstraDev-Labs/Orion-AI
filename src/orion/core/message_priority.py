"""Heuristic priority classifier for inbound channel messages.

Tags every incoming message as one of ``"emergency"``, ``"important"``, or
``"normal"`` so notifications can be triaged instead of arriving as an
undifferentiated stream. This is a fast keyword/pattern heuristic (no LLM
call) so it can run inline on every message without adding latency.
"""

from __future__ import annotations

import re

PRIORITY_EMERGENCY = "emergency"
PRIORITY_IMPORTANT = "important"
PRIORITY_NORMAL = "normal"

_EMERGENCY_PATTERNS = re.compile(
    r"\b(emergency|urgent|asap|right now|immediately|call me now|"
    r"help me|accident|hospital|ambulance|police|fire|"
    r"i('m| am) (in trouble|hurt|bleeding|stuck)|"
    r"need you now|life or death|911|112)\b",
    re.IGNORECASE,
)

_IMPORTANT_PATTERNS = re.compile(
    r"\b(important|urgent(?!ly)?|deadline|asap|please call|please respond|"
    r"can you call|need to talk|need your help|time[- ]sensitive|"
    r"waiting on you|are you (there|around|free)|when (are|will) you)\b",
    re.IGNORECASE,
)

# Excessive punctuation/caps is a weak-but-useful urgency signal on its own.
_SHOUTING = re.compile(r"[!?]{2,}|\b[A-Z]{4,}\b")


def classify_priority(text: str) -> str:
    """Classify a single message's urgency from its text content alone."""
    if not text:
        return PRIORITY_NORMAL

    if _EMERGENCY_PATTERNS.search(text):
        return PRIORITY_EMERGENCY

    if _IMPORTANT_PATTERNS.search(text):
        return PRIORITY_IMPORTANT

    if _SHOUTING.search(text) and len(text) < 200:
        return PRIORITY_IMPORTANT

    return PRIORITY_NORMAL


__all__ = [
    "classify_priority",
    "PRIORITY_EMERGENCY",
    "PRIORITY_IMPORTANT",
    "PRIORITY_NORMAL",
]
