"""Record a completed chat turn as a real trace.

``LearningOrchestrator`` (the auto-learning / self-improvement pipeline)
mines exclusively from ``TraceStore``. Before this module existed, nothing
in the normal chat path ever wrote a trace: ``EventType.TRACE_COMPLETE`` is
defined but was never published anywhere, and the one real
``trace_store.save()`` call in the codebase (agents/executor.py) only fires
for scheduled *managed* agents ticking, not for interactive chat. So no
matter how much a user actually talked to Orion, the learning pipeline
always saw zero traces and could only ever report "no training data
available" -- this closes that gap for real chat completions.
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)


# TrainingDataMiner._quality_traces() filters to traces where
# `feedback is not None and feedback >= min_quality` (default min_quality
# 0.7) -- but nothing anywhere in this app ever sets trace.feedback, so
# without this, the learning pipeline was structurally *unable* to ever
# produce SFT pairs, no matter how many traces accumulated. This is a
# disclosed baseline for "completed without error," not a claim about
# actual response quality -- real user feedback (once that UI exists)
# should override it, not be conflated with it.
_BASELINE_FEEDBACK_SUCCESS = 0.75


def record_chat_trace(
    *,
    trace_store,
    query: str,
    result_content: str,
    model: str,
    engine: str,
    started_at: float,
    total_tokens: int = 0,
    agent: str = "",
) -> None:
    """Persist one real chat exchange as a trace. Swallows its own errors so
    a trace-recording failure never affects the chat response already sent.
    """
    if trace_store is None or not query:
        return
    try:
        from orion.core.types import Trace

        outcome = "success" if result_content else "error"
        trace = Trace(
            query=query[:2000],
            agent=agent,
            model=model,
            engine=engine,
            result=(result_content or "")[:2000],
            outcome=outcome,
            feedback=_BASELINE_FEEDBACK_SUCCESS if outcome == "success" else None,
            started_at=started_at,
            ended_at=time.time(),
            total_tokens=total_tokens,
            total_latency_seconds=time.time() - started_at,
        )
        trace_store.save(trace)
    except Exception:
        logger.debug("Chat trace recording failed", exc_info=True)


__all__ = ["record_chat_trace"]
