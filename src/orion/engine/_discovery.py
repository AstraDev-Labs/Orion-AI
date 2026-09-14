"""Engine discovery — probe running engines and aggregate available models."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

from orion.core.config import OrionConfig
from orion.core.registry import EngineRegistry
from orion.engine._base import InferenceEngine

logger = logging.getLogger(__name__)

# Map registry keys to config host attribute (None = no host arg)
_HOST_MAP: Dict[str, str | None] = {
    "ollama": "ollama_host",
    "vllm": "vllm_host",
    "llamacpp": "llamacpp_host",
    "sglang": "sglang_host",
    "mlx": "mlx_host",
    "lmstudio": "lmstudio_host",
    "exo": "exo_host",
    "nexa": "nexa_host",
    "uzu": "uzu_host",
    "apple_fm": "apple_fm_host",
    "lemonade": "lemonade_host",
    "nvidia": "nvidia_host",
    "cloud": None,
    "litellm": None,
    "gemma_cpp": None,
}


def _make_engine(key: str, config: OrionConfig) -> InferenceEngine:
    """Instantiate a registered engine with the appropriate config host."""
    cls = EngineRegistry.get(key)

    # gemma_cpp: pass config fields instead of host
    if key == "gemma_cpp":
        cfg = config.engine.gemma_cpp
        return cls(
            model_path=cfg.model_path or None,
            tokenizer_path=cfg.tokenizer_path or None,
            model_type=cfg.model_type or None,
            num_threads=cfg.num_threads,
        )

    # ollama: host plus the one context window every request must share
    if key == "ollama":
        cfg = config.engine.ollama
        return cls(host=cfg.host or None, num_ctx=cfg.num_ctx, keep_alive=cfg.keep_alive)

    # nvidia: pass host and api_key
    if key == "nvidia":
        cfg = config.engine.nvidia
        return cls(host=cfg.host or None, api_key=cfg.api_key or None)

    host_attr = _HOST_MAP.get(key)
    if host_attr is not None:
        host = getattr(config.engine, host_attr, None)
        if host:
            return cls(host=host)
    return cls()


def _maybe_register_mining_sidecar_engine() -> None:
    """If a mining sidecar exists with a ``vllm_endpoint``, register a derived
    vLLM engine class pointing at it.  Idempotent.  Quiet on error.

    The trigger is the *shape* of the sidecar (presence of ``vllm_endpoint``),
    not the value of its ``provider`` field — this leaves room for future
    non-engine-replacing providers (e.g., a hypothetical cpu-pearl) whose
    sidecars don't include ``vllm_endpoint``.
    """
    try:
        from orion.mining import Sidecar
        from orion.mining._constants import SIDECAR_PATH
    except ImportError:
        return

    if EngineRegistry.contains("vllm-pearl-mining"):
        return  # idempotent

    payload = Sidecar.read(SIDECAR_PATH)
    if payload is None:
        return

    endpoint = payload.get("vllm_endpoint")
    model = payload.get("model")
    if not endpoint or not model:
        return  # data-driven gate: no vllm_endpoint → don't register

    from orion.engine._openai_compat import _OpenAICompatibleEngine

    # Strip a trailing "/v1" path segment so _default_host is the bare
    # base URL and _api_prefix="/v1" combines correctly in request paths.
    api_prefix = "/v1"
    base_url = endpoint.rstrip("/")
    if base_url.endswith(api_prefix):
        base_url = base_url[: -len(api_prefix)]

    _cls = type(
        "VllmPearlMiningEngine",
        (_OpenAICompatibleEngine,),
        {
            "engine_id": "vllm-pearl-mining",
            "_default_host": base_url,
            "_api_prefix": api_prefix,
        },
    )
    EngineRegistry.register_value("vllm-pearl-mining", _cls)


def discover_engines(config: OrionConfig) -> List[Tuple[str, InferenceEngine]]:
    """Probe registered engines in parallel and return ``[(key, instance)]`` for healthy ones.

    Results are sorted with the config default engine first.
    """
    _maybe_register_mining_sidecar_engine()
    healthy: List[Tuple[str, InferenceEngine]] = []

    import concurrent.futures
    import platform

    keys = list(EngineRegistry.keys())
    # Skip macOS-only engines on non-macOS platforms
    if platform.system().lower() != "darwin":
        keys = [k for k in keys if k not in ("mlx", "apple_fm")]

    engine_map = {}
    for key in keys:
        try:
            engine_map[key] = _make_engine(key, config)
        except Exception as exc:
            logger.debug("Failed to instantiate engine %r: %s", key, exc)

    if engine_map:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(engine_map)) as executor:
            future_to_key = {
                executor.submit(engine.health): key
                for key, engine in engine_map.items()
            }
            for future in concurrent.futures.as_completed(future_to_key):
                key = future_to_key[future]
                try:
                    if future.result():
                        healthy.append((key, engine_map[key]))
                except Exception as exc:
                    logger.debug("Engine %r health check raised exception: %s", key, exc)

    default_key = config.engine.default

    def sort_key(item: Tuple[str, Any]) -> Tuple[int, str]:
        return (0 if item[0] == default_key else 1, item[0])

    healthy.sort(key=sort_key)
    return healthy


def discover_models(
    engines: List[Tuple[str, InferenceEngine]],
) -> Dict[str, List[str]]:
    """Call ``list_models()`` on each engine and return a dict."""
    result: Dict[str, List[str]] = {}
    for key, engine in engines:
        try:
            result[key] = engine.list_models()
        except Exception as exc:
            logger.debug("Failed to list models for engine %r: %s", key, exc)
            result[key] = []
    return result


def get_engine(
    config: OrionConfig, engine_key: str | None = None
) -> Tuple[str, InferenceEngine] | None:
    """Get a specific engine by key, or the default with fallback.

    Returns ``(key, engine_instance)`` or ``None`` if no engine is available.
    """
    # Build an ordered list of keys to try, then fall back to full discovery.
    keys_to_try: list[str] = []
    if engine_key:
        keys_to_try.append(engine_key)

    default_key = config.engine.default
    if default_key and default_key not in keys_to_try:
        keys_to_try.append(default_key)

    for key in keys_to_try:
        if not EngineRegistry.contains(key):
            continue
        try:
            engine = _make_engine(key, config)
        except Exception as exc:
            logger.debug("Engine %r could not be constructed: %s", key, exc)
            continue
        if _healthy_with_retry(key, engine):
            return (key, engine)

    # Fallback to another healthy *local* engine. Cloud engines are never
    # picked automatically: litellm's health() only checks that the package
    # imports, so it always "passed", and a server whose Ollama was merely busy
    # at boot came up routed through litellm -- reporting healthy while every
    # chat request failed with "LLM Provider NOT provided". Silently switching
    # a local-first assistant to a cloud router is never an acceptable fallback;
    # a cloud engine runs only when chosen explicitly (engine_key or default).
    healthy = [
        (k, e) for k, e in discover_engines(config) if k not in _CLOUD_ENGINES
    ]
    if healthy:
        logger.warning(
            "Requested engine(s) %s unavailable; falling back to local engine %r",
            keys_to_try,
            healthy[0][0],
        )
        return healthy[0]
    return None


# Engines that send requests off the machine. Never chosen as a fallback.
_CLOUD_ENGINES = frozenset({"cloud", "litellm", "nvidia"})

# A local engine that is busy (e.g. Ollama loading a model) can miss a single
# 2-second health probe; retry briefly before concluding it is down.
_HEALTH_ATTEMPTS = 5
_HEALTH_RETRY_DELAY = 2.0


def _healthy_with_retry(key: str, engine: InferenceEngine) -> bool:
    import time

    for attempt in range(1, _HEALTH_ATTEMPTS + 1):
        try:
            if engine.health():
                return True
        except Exception as exc:
            logger.debug("Engine %r health check failed: %s", key, exc)
        if attempt < _HEALTH_ATTEMPTS:
            time.sleep(_HEALTH_RETRY_DELAY)
    logger.warning("Engine %r did not become healthy after %d attempts", key, _HEALTH_ATTEMPTS)
    return False


__all__ = ["discover_engines", "discover_models", "get_engine"]
