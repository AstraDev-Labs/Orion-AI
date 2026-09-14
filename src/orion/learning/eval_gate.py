"""A real accept/reject gate for LearningOrchestrator.

Before this module existed, `LearningOrchestrator` was constructed with no
`eval_fn` (`system/builder.py::_setup_learning_orchestrator` never passed
one), so `LearningOrchestrator.run()`'s baseline/post-score comparison
never ran and every cycle's result was unconditionally marked
`accepted: True` -- a rubber stamp, not a safety check. This wires a real,
fast, fully-deterministic benchmark (ToolCall-15: 15 tool-calling
scenarios, no network calls, no LLM judge) as that gate, so an accepted
result actually means something.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)


def build_eval_fn(*, model: str, engine_key: Optional[str] = None) -> Optional[Callable[[], float]]:
    """Return a callable that runs a fast real benchmark and returns a
    scalar pass rate in [0, 1], or ``None`` if the eval harness can't be
    constructed (e.g. missing optional deps) -- callers should fall back to
    the old unconditional-accept behavior rather than crash learning
    entirely over a broken benchmark.
    """
    try:
        from orion.evals.backends.orion_direct import OrionDirectBackend
        from orion.evals.core.runner import EvalRunner
        from orion.evals.core.types import RunConfig
        from orion.evals.datasets.toolcall15 import ToolCall15Dataset
        from orion.evals.scorers.toolcall15 import ToolCall15Scorer
    except Exception:
        logger.warning("Eval harness unavailable; learning cycles will accept unconditionally", exc_info=True)
        return None

    def _eval_fn() -> float:
        backend = OrionDirectBackend(engine_key=engine_key)
        dataset = ToolCall15Dataset()
        scorer = ToolCall15Scorer(None, "")  # deterministic scorer, no judge model used
        config = RunConfig(
            benchmark="toolcall15",
            backend="orion-direct",
            model=model,
            max_workers=1,  # a local model shouldn't be hit with concurrent requests
        )
        runner = EvalRunner(config, dataset, backend, scorer)
        summary = runner.run()
        logger.info(
            "Eval gate: %s/%s ToolCall-15 scenarios passed (%.0f%%)",
            summary.correct,
            summary.scored_samples,
            summary.accuracy * 100,
        )
        return summary.accuracy

    return _eval_fn


__all__ = ["build_eval_fn"]
