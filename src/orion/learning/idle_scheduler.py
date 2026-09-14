"""Idle-triggered learning scheduler.

Runs :class:`LearningOrchestrator` in the background only while the user
is inactive, and yields to them immediately: any request handler that
touches the scheduler resets the idle clock, so a cycle already in flight
is left to finish (LearningOrchestrator.run() has no internal cancellation
points) but a *new* cycle never starts while the user is active, and the
orchestrator runs in a worker thread so it never blocks the event loop
that serves chat responses.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)


class IdleLearningScheduler:
    """Background loop: run a learning cycle after sustained user inactivity."""

    def __init__(
        self,
        orchestrator: Any,
        *,
        minimum_idle_seconds: float = 300.0,
        check_interval_seconds: float = 30.0,
        min_seconds_between_runs: float = 3600.0,
    ) -> None:
        self._orchestrator = orchestrator
        self._minimum_idle_seconds = minimum_idle_seconds
        self._check_interval_seconds = check_interval_seconds
        self._min_seconds_between_runs = min_seconds_between_runs

        self._last_activity = time.time()
        self._last_run_at: Optional[float] = None
        self._running = False
        self._last_result: Optional[dict] = None
        self._task: Optional[asyncio.Task] = None

    def touch(self) -> None:
        """Call on every real user interaction (chat message, voice turn, ...)."""
        self._last_activity = time.time()

    @property
    def status(self) -> dict:
        return {
            "running": self._running,
            "idle_seconds": round(time.time() - self._last_activity, 1),
            "minimum_idle_seconds": self._minimum_idle_seconds,
            "last_run_at": self._last_run_at,
            "last_result": self._last_result,
        }

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())
            logger.info(
                "Idle learning scheduler started (idle threshold=%ss, cooldown=%ss)",
                self._minimum_idle_seconds,
                self._min_seconds_between_runs,
            )

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(self._check_interval_seconds)
                if self._should_run():
                    await self._run_cycle()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Idle learning scheduler loop error")

    def _should_run(self) -> bool:
        if self._running:
            return False
        if time.time() - self._last_activity < self._minimum_idle_seconds:
            return False
        if self._last_run_at is not None and (time.time() - self._last_run_at) < self._min_seconds_between_runs:
            return False
        return True

    async def _run_cycle(self) -> None:
        self._running = True
        logger.info("Idle learning cycle starting (idle for %.0fs)", time.time() - self._last_activity)
        try:
            result = await asyncio.to_thread(self._orchestrator.run)
            self._last_result = result
            logger.info("Idle learning cycle finished: %s", result.get("status"))
        except Exception:
            logger.exception("Idle learning cycle failed")
        finally:
            self._last_run_at = time.time()
            self._running = False
