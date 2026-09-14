"""Telemetry records carry wall-clock timestamps, not perf_counter values."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

from orion.core.events import EventBus, EventType
from orion.telemetry.instrumented_engine import InstrumentedEngine


def test_generate_record_timestamp_is_wall_clock():
    inner = MagicMock()
    inner.engine_id = "ollama"
    inner.generate.return_value = {"content": "hi", "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4}}
    bus = EventBus()
    records = []
    bus.subscribe(EventType.TELEMETRY_RECORD, lambda e: records.append(e.data["record"]))
    before = time.time()
    InstrumentedEngine(inner, bus).generate([], model="m")
    assert records and before - 1 <= records[0].timestamp <= time.time() + 1


def test_stream_record_uses_engine_reported_usage():
    import asyncio

    class _Inner:
        engine_id = "ollama"

        async def stream(self, messages, *, model, temperature=0.7, max_tokens=1024, **kw):
            for piece in ("Hel", "lo", " there"):
                yield piece
            self._last_stream_usage = {"prompt_tokens": 120, "prompt_tokens_evaluated": 120, "completion_tokens": 3, "total_tokens": 123}

    class _Guard:  # a wrapper between telemetry and the real engine
        engine_id = "ollama"

        def __init__(self):
            self._engine = _Inner()

        def stream(self, *a, **kw):
            return self._engine.stream(*a, **kw)

    bus = EventBus()
    records = []
    bus.subscribe(EventType.TELEMETRY_RECORD, lambda e: records.append(e.data["record"]))
    eng = InstrumentedEngine(_Guard(), bus)

    async def run():
        return [t async for t in eng.stream([], model="m")]

    assert "".join(asyncio.run(run())) == "Hello there"
    rec = records[-1]
    assert (rec.prompt_tokens, rec.completion_tokens, rec.total_tokens) == (120, 3, 123)
