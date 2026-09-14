"""One context window for every Ollama request.

Ollama reloads the entire model whenever num_ctx differs from the previous
request. generate()/stream() used to send 4096 while stream_full() sent 8192,
so any flow that mixed them (the plain chat route vs the streaming bridge)
paid a full model reload on every switch.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import httpx
import respx

from orion.core.config import OrionConfig
from orion.core.types import Message, Role
from orion.engine import _discovery
from orion.engine.ollama import OllamaEngine

HOST = "http://localhost:11434"


def _chat_ok():
    return httpx.Response(
        200,
        json={"message": {"role": "assistant", "content": "ok"}, "done": True,
              "prompt_eval_count": 1, "eval_count": 1},
    )


def _sent_num_ctx(route) -> int:
    return json.loads(route.calls.last.request.content)["options"]["num_ctx"]


@respx.mock
def test_generate_uses_the_configured_context():
    route = respx.post(f"{HOST}/api/chat").mock(return_value=_chat_ok())
    OllamaEngine(host=HOST, num_ctx=6144).generate(
        [Message(role=Role.USER, content="hi")], model="m"
    )
    assert _sent_num_ctx(route) == 6144


@respx.mock
def test_default_context_is_8192():
    route = respx.post(f"{HOST}/api/chat").mock(return_value=_chat_ok())
    OllamaEngine(host=HOST).generate([Message(role=Role.USER, content="hi")], model="m")
    assert _sent_num_ctx(route) == 8192


@respx.mock
def test_per_call_override_still_wins():
    route = respx.post(f"{HOST}/api/chat").mock(return_value=_chat_ok())
    OllamaEngine(host=HOST, num_ctx=8192).generate(
        [Message(role=Role.USER, content="hi")], model="m", num_ctx=2048
    )
    assert _sent_num_ctx(route) == 2048


def test_no_method_hardcodes_its_own_context():
    """The mismatch came from each method carrying a literal default."""
    src = Path(OllamaEngine.__module__.replace(".", "/") + ".py")
    text = (Path("src") / src).read_text(encoding="utf-8")
    assert not re.search(r'kwargs\.get\("num_ctx",\s*\d+\)', text)
    assert text.count('kwargs.get("num_ctx", self._num_ctx)') == 3


def test_discovery_passes_config_context(monkeypatch):
    from orion.core.registry import EngineRegistry

    if not EngineRegistry.contains("ollama"):
        EngineRegistry.register_value("ollama", OllamaEngine)
    cfg = OrionConfig()
    cfg.engine.ollama.host = HOST
    cfg.engine.ollama.num_ctx = 4096
    engine = _discovery._make_engine("ollama", cfg)
    assert engine._num_ctx == 4096


def test_config_default_matches_engine_default():
    """Engines built without config (CLI helpers) must agree with configured ones."""
    assert OrionConfig().engine.ollama.num_ctx == OllamaEngine(host=HOST)._num_ctx
