"""Tests for the idle-triggered background learning scheduler."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock

import pytest

from orion.learning.idle_scheduler import IdleLearningScheduler


def make_orchestrator(result=None):
    orch = MagicMock()
    orch.run.return_value = result or {"status": "skipped", "reason": "no training data available"}
    return orch


class TestShouldRun:
    def test_does_not_run_while_active(self):
        sched = IdleLearningScheduler(make_orchestrator(), minimum_idle_seconds=300)
        sched.touch()
        assert sched._should_run() is False

    def test_runs_after_idle_threshold(self):
        sched = IdleLearningScheduler(make_orchestrator(), minimum_idle_seconds=0.01)
        sched.touch()
        time.sleep(0.02)
        assert sched._should_run() is True

    def test_does_not_run_twice_while_already_running(self):
        sched = IdleLearningScheduler(make_orchestrator(), minimum_idle_seconds=0.0)
        sched._running = True
        assert sched._should_run() is False

    def test_respects_cooldown_between_runs(self):
        sched = IdleLearningScheduler(
            make_orchestrator(), minimum_idle_seconds=0.0, min_seconds_between_runs=3600.0
        )
        sched._last_run_at = time.time()
        assert sched._should_run() is False


class TestRunCycle:
    @pytest.mark.asyncio
    async def test_run_cycle_invokes_orchestrator_and_records_result(self):
        orch = make_orchestrator({"status": "accepted"})
        sched = IdleLearningScheduler(orch, minimum_idle_seconds=0.0)

        await sched._run_cycle()

        orch.run.assert_called_once()
        assert sched._running is False
        assert sched._last_result == {"status": "accepted"}
        assert sched._last_run_at is not None

    @pytest.mark.asyncio
    async def test_run_cycle_clears_running_flag_on_exception(self):
        orch = MagicMock()
        orch.run.side_effect = RuntimeError("boom")
        sched = IdleLearningScheduler(orch, minimum_idle_seconds=0.0)

        await sched._run_cycle()

        assert sched._running is False
        assert sched._last_run_at is not None

    @pytest.mark.asyncio
    async def test_touch_during_run_does_not_crash_and_resets_idle_clock(self):
        """Simulates the user becoming active again while a cycle is in flight:
        the current cycle finishes (no cancellation hook exists inside
        LearningOrchestrator.run()), but the idle clock is reset so no new
        cycle starts immediately after."""
        orch = make_orchestrator()
        sched = IdleLearningScheduler(orch, minimum_idle_seconds=0.05, min_seconds_between_runs=0.0)

        run_task = asyncio.create_task(sched._run_cycle())
        await asyncio.sleep(0)  # let the cycle start
        sched.touch()
        await run_task

        assert sched._should_run() is False  # idle clock was just reset


class TestStatus:
    def test_status_reports_enabled_state(self):
        sched = IdleLearningScheduler(make_orchestrator(), minimum_idle_seconds=120)
        status = sched.status
        assert status["running"] is False
        assert status["minimum_idle_seconds"] == 120
        assert status["last_run_at"] is None
