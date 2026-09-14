"""Session Memory — "remembers yesterday" recap injection.

Tracks when the user last talked to ORION. When a chat request arrives
after a long enough gap (a genuine new session, not mid-conversation), and
that request's own message history has real prior content, an instruction
is injected asking the model to briefly and naturally acknowledge the time
that's passed and what was being discussed — using the conversation history
already present in the request, no extra LLM call needed.
"""

from __future__ import annotations

import json
import time

from orion.core.config import DEFAULT_CONFIG_DIR

_STATE_PATH = DEFAULT_CONFIG_DIR / "session_recap.json"

# How long the user has to be away before returning counts as a "new session".
SESSION_GAP_SECONDS = 3 * 60 * 60  # 3 hours

RECAP_INSTRUCTION = (
    "[SESSION RESUMED] Some time has passed since the conversation above. "
    "Before addressing the user's latest message, briefly and naturally "
    "acknowledge the gap and what you two were discussing last time — one "
    "short sentence, not a formal summary. Then continue normally. Do this "
    "only for this reply."
)


def _load_last_activity() -> float:
    if not _STATE_PATH.exists():
        return 0.0
    try:
        return float(json.loads(_STATE_PATH.read_text(encoding="utf-8")).get("last_activity_at", 0.0))
    except Exception:
        return 0.0


def _save_last_activity(ts: float) -> None:
    try:
        DEFAULT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        _STATE_PATH.write_text(json.dumps({"last_activity_at": ts}), encoding="utf-8")
    except Exception:
        pass


def should_inject_recap(prior_message_count: int) -> bool:
    """Check (without mutating state) whether this turn should get a recap nudge."""
    if prior_message_count < 2:
        return False
    last_activity = _load_last_activity()
    if last_activity <= 0:
        return False
    return (time.time() - last_activity) > SESSION_GAP_SECONDS


def mark_activity() -> None:
    """Record that the user is active right now."""
    _save_last_activity(time.time())
