"""A real, signal-derived affect state -- not a fabricated "mood."

Every field here is computed from something that actually happened:
message urgency from the same classifier already used for WhatsApp
priority (`message_priority.classify_priority`), momentum from real recent
trace outcomes (`traces/store.py`, populated since the memory/learning work
this session), and familiarity from real similarity against the persisted
memory backend (`tools/storage/dense.py`). Nothing here is the model
claiming to "feel" something -- it's a small typed summary of real recent
signal, used to color the Holotable orb and lightly steer response tone.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from orion.core.message_priority import (
    PRIORITY_EMERGENCY,
    PRIORITY_IMPORTANT,
    PRIORITY_NORMAL,
    classify_priority,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AffectState:
    """A snapshot, not a personality -- recomputed fresh each time."""

    urgency: str = PRIORITY_NORMAL  # emergency | important | normal
    momentum: float = 0.5  # 0..1, recent trace/learning success rate; 0.5 = no data yet
    familiarity: float = 0.0  # 0..1, how well the current topic matches existing memory
    label: str = "steady"  # short, honest description derived from the above -- not a claim of feeling

    def to_dict(self) -> dict:
        return {
            "urgency": self.urgency,
            "momentum": round(self.momentum, 3),
            "familiarity": round(self.familiarity, 3),
            "label": self.label,
        }


def _derive_label(urgency: str, momentum: float, familiarity: float) -> str:
    """A short, honest descriptor -- picked from the same three real numbers
    the caller already has, not an invented backstory.
    """
    if urgency == PRIORITY_EMERGENCY:
        return "alert"
    if urgency == PRIORITY_IMPORTANT:
        return "focused"
    if momentum < 0.35:
        return "cautious"  # recent cycles/tasks have mostly not gone well
    if familiarity > 0.6:
        return "warm"  # this topic connects to a lot of existing memory
    if momentum > 0.7:
        return "confident"
    return "steady"


def compute_affect(
    *,
    text: str = "",
    trace_store=None,
    memory_backend=None,
) -> AffectState:
    """Compute a real affect snapshot from whatever signals are actually
    available. Missing inputs degrade to neutral defaults, not fabricated
    values -- e.g. no trace history yet means momentum stays at the
    documented neutral 0.5, not a guessed number.
    """
    urgency = classify_priority(text) if text else PRIORITY_NORMAL

    momentum = 0.5
    if trace_store is not None:
        try:
            recent = trace_store.list_traces(limit=20)
            scored = [t for t in recent if t.outcome in ("success", "error")]
            if scored:
                momentum = sum(1 for t in scored if t.outcome == "success") / len(scored)
        except Exception:
            logger.debug("Affect momentum lookup failed", exc_info=True)

    familiarity = 0.0
    if memory_backend is not None and text:
        try:
            results = memory_backend.retrieve(text, top_k=1)
            if results:
                # Cosine similarity in [-1, 1] for normalized vectors;
                # clamp to [0, 1] since a real match is what's meaningful
                # here, not "how anti-correlated" something is.
                familiarity = max(0.0, min(1.0, float(results[0].score)))
        except Exception:
            logger.debug("Affect familiarity lookup failed", exc_info=True)

    label = _derive_label(urgency, momentum, familiarity)
    return AffectState(urgency=urgency, momentum=momentum, familiarity=familiarity, label=label)


# -- Tone guidance, derived from the same real signals -----------------------

_TONE_BY_LABEL = {
    "alert": "This reads as urgent -- be direct and brief; don't pad the reply.",
    "focused": "This reads as time-sensitive -- stay on task, skip pleasantries.",
    "cautious": (
        "Recent cycles/tasks haven't gone well -- check in plainly rather than "
        "push forward confidently; it's fine to say what didn't work."
    ),
    "warm": "This connects to things already discussed -- feel free to reference that continuity briefly.",
    "confident": "Recent work has been landing well -- normal tone, no need to hedge more than usual.",
    "steady": None,  # no additional instruction -- the default system prompt already covers this
}


def tone_instruction(state: AffectState) -> Optional[str]:
    """One real, small instruction derived from the affect state, or None
    when there's nothing worth adding. Never a first-person feelings claim
    -- an instruction about *behavior*, not an assertion the model then
    might parrot back as if it were sentient.
    """
    return _TONE_BY_LABEL.get(state.label)


__all__ = ["AffectState", "compute_affect", "tone_instruction"]
