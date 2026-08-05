"""Benchmarking framework for Orion inference engines."""

from __future__ import annotations

from orion.bench._stubs import BaseBenchmark, BenchmarkResult, BenchmarkSuite
from orion.core.registry import BenchmarkRegistry


def ensure_registered() -> None:
    """Ensure all benchmark implementations are registered."""
    from orion.bench.energy import ensure_registered as _reg_energy
    from orion.bench.latency import ensure_registered as _reg_latency
    from orion.bench.throughput import ensure_registered as _reg_throughput

    _reg_latency()
    _reg_throughput()
    _reg_energy()


# Trigger registration on import
ensure_registered()

__all__ = [
    "BaseBenchmark",
    "BenchmarkRegistry",
    "BenchmarkResult",
    "BenchmarkSuite",
    "ensure_registered",
]
