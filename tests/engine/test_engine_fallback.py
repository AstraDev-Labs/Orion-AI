"""get_engine must never silently fail over to a cloud router.

litellm's health() only checks that the package imports, so it always passed.
When Ollama was merely busy at startup, the server came up "healthy" routed
through litellm and every chat request failed with "LLM Provider NOT provided".
"""

from __future__ import annotations

import pytest

from orion.core.config import OrionConfig
from orion.core.registry import EngineRegistry
from orion.engine import _discovery


class _Fake:
    def __init__(self, results):
        self._results = list(results)
        self.calls = 0

    def health(self):
        self.calls += 1
        return self._results.pop(0) if self._results else False


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(_discovery, "_HEALTH_RETRY_DELAY", 0)
    monkeypatch.setattr(EngineRegistry, "contains", classmethod(lambda cls, k: True))


def _wire(monkeypatch, engines, discovered):
    monkeypatch.setattr(_discovery, "_make_engine", lambda key, cfg: engines[key])
    monkeypatch.setattr(_discovery, "discover_engines", lambda cfg: discovered)


def test_cloud_engine_is_never_an_automatic_fallback(monkeypatch):
    down = _Fake([False] * 10)
    _wire(monkeypatch, {"ollama": down}, [("litellm", _Fake([True]))])
    assert _discovery.get_engine(OrionConfig(), "ollama") is None


@pytest.mark.parametrize("cloud_key", ["litellm", "cloud", "nvidia"])
def test_no_cloud_engine_is_picked_automatically(monkeypatch, cloud_key):
    _wire(monkeypatch, {"ollama": _Fake([False] * 10)}, [(cloud_key, _Fake([True]))])
    assert _discovery.get_engine(OrionConfig()) is None


def test_another_local_engine_is_still_an_acceptable_fallback(monkeypatch):
    local = _Fake([True])
    _wire(
        monkeypatch,
        {"ollama": _Fake([False] * 10)},
        [("litellm", _Fake([True])), ("llamacpp", local)],
    )
    key, engine = _discovery.get_engine(OrionConfig(), "ollama")
    assert key == "llamacpp" and engine is local


def test_busy_engine_is_retried_rather_than_abandoned(monkeypatch):
    """Ollama loading a model can miss one probe; that is not 'down'."""
    busy = _Fake([False, False, True])
    _wire(monkeypatch, {"ollama": busy}, [("litellm", _Fake([True]))])
    key, engine = _discovery.get_engine(OrionConfig(), "ollama")
    assert key == "ollama" and busy.calls == 3


def test_explicitly_requested_cloud_engine_still_works(monkeypatch):
    cloud = _Fake([True])
    _wire(monkeypatch, {"litellm": cloud, "ollama": _Fake([False] * 10)}, [])
    key, engine = _discovery.get_engine(OrionConfig(), "litellm")
    assert key == "litellm" and engine is cloud


def test_retries_are_bounded(monkeypatch):
    down = _Fake([False] * 50)
    _wire(monkeypatch, {"ollama": down}, [])
    assert _discovery.get_engine(OrionConfig(), "ollama") is None
    assert down.calls == _discovery._HEALTH_ATTEMPTS
