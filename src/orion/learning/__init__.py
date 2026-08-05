"""Learning primitive -- router policies, reward functions, learning."""

from __future__ import annotations

from orion.learning._stubs import (
    QueryAnalyzer,
    RewardFunction,
    RouterPolicy,
    RoutingContext,
)
from orion.learning.agents.agent_evolver import AgentConfigEvolver
from orion.learning.learning_orchestrator import LearningOrchestrator
from orion.learning.optimize.llm_optimizer import LLMOptimizer
from orion.learning.optimize.optimizer import OptimizationEngine
from orion.learning.optimize.store import OptimizationStore
from orion.learning.routing.complexity import (
    ComplexityQueryAnalyzer,
    score_complexity,
)
from orion.learning.routing.heuristic_reward import HeuristicRewardFunction
from orion.learning.routing.router import (
    HeuristicRouter,
    build_routing_context,
)
from orion.learning.training.data import TrainingDataMiner
from orion.learning.training.lora import HAS_TORCH, LoRATrainer, LoRATrainingConfig


def ensure_registered() -> None:
    """Ensure all learning policies are registered in RouterPolicyRegistry."""
    from orion.learning.routing.heuristic_policy import (
        ensure_registered as _reg_heuristic,
    )

    _reg_heuristic()

    from orion.learning.routing.learned_router import (
        ensure_registered as _reg_learned,
    )

    _reg_learned()

    # Intelligence training (optional deps)
    try:
        import orion.learning.intelligence  # noqa: F401
    except ImportError:
        pass

    # Orchestrator-specific training (optional deps)
    try:
        import orion.learning.intelligence.orchestrator  # noqa: F401
    except ImportError:
        pass

    # Agent optimizers (optional deps)
    try:
        import orion.learning.agents.dspy_optimizer  # noqa: F401
    except ImportError:
        pass
    try:
        import orion.learning.agents.gepa_optimizer  # noqa: F401
    except ImportError:
        pass
    try:
        import orion.learning.agents.ace_optimizer  # noqa: F401
    except ImportError:
        pass


__all__ = [
    "AgentConfigEvolver",
    "ComplexityQueryAnalyzer",
    "HAS_TORCH",
    "HeuristicRewardFunction",
    "HeuristicRouter",
    "LLMOptimizer",
    "LearningOrchestrator",
    "LoRATrainer",
    "LoRATrainingConfig",
    "OptimizationEngine",
    "OptimizationStore",
    "QueryAnalyzer",
    "RewardFunction",
    "RouterPolicy",
    "RoutingContext",
    "TrainingDataMiner",
    "build_routing_context",
    "ensure_registered",
    "score_complexity",
]
