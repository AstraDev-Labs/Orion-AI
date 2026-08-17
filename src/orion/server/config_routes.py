"""Settings API — read and update Orion's persisted configuration.

Exposes a curated subset of ``config.toml`` for the frontend Settings
view (:file:`frontend/src/components/Dashboard/Views/SettingsView.tsx`)
and applies changes both to the on-disk TOML file and to the live,
already-running ``OrionConfig`` instance so the API server doesn't need
a restart to pick up most changes. Engine/model changes additionally
trigger an in-place hot-reload of ``app.state.engine``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/config", tags=["config"])

# Maps the flat fields the Settings UI edits to their dotted OrionConfig path.
_FIELD_TO_KEY = {
    "model": "intelligence.default_model",
    "engine": "engine.default",
    "temperature": "intelligence.temperature",
    "max_tokens": "intelligence.max_tokens",
    "obsidian_dir": "tools.storage.obsidian_dir",
    "learning_enabled": "learning.enabled",
}


class ConfigUpdateRequest(BaseModel):
    """Partial config update — only present fields are changed."""

    model: Optional[str] = None
    engine: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    obsidian_dir: Optional[str] = None
    learning_enabled: Optional[bool] = None


def _config_path() -> Path:
    from orion.core.config import DEFAULT_CONFIG_DIR

    return Path(os.environ.get("OPENORION_CONFIG", DEFAULT_CONFIG_DIR / "config.toml"))


def _persist(dotted_values: dict[str, Any]) -> None:
    """Write dotted-key/value pairs into the TOML config file, preserving formatting."""
    import tomlkit

    path = _config_path()
    if path.exists():
        doc = tomlkit.parse(path.read_text())
    else:
        doc = tomlkit.document()
        path.parent.mkdir(parents=True, exist_ok=True)

    for dotted_key, value in dotted_values.items():
        parts = dotted_key.split(".")
        current: Any = doc
        for part in parts[:-1]:
            if part not in current:
                current.add(part, tomlkit.table())
            current = current[part]
        current[parts[-1]] = value

    path.write_text(tomlkit.dumps(doc))


def _apply_live(config: Any, dotted_key: str, value: Any) -> None:
    """Set a dotted-key value on the live in-memory OrionConfig instance."""
    parts = dotted_key.split(".")
    target = config
    for part in parts[:-1]:
        target = getattr(target, part)
    setattr(target, parts[-1], value)


def _hot_reload_engine(app: Any, config: Any) -> None:
    """Rebuild the underlying inference engine in place after a config change.

    Mirrors the wrapping order ``serve.py`` builds at startup — security
    guardrails, then an optional ``MultiEngine`` (local + cloud), then
    telemetry instrumentation — so a reload preserves whichever of those
    layers were already active instead of dropping them.
    """
    from orion.core.registry import EngineRegistry
    from orion.engine._discovery import _make_engine
    from orion.engine.multi import MultiEngine
    from orion.security import setup_security

    engine_key = config.engine.default
    if not EngineRegistry.contains(engine_key):
        raise RuntimeError(f"Unknown engine: {engine_key!r}")

    raw_engine = _make_engine(engine_key, config)
    if not raw_engine.health():
        raise RuntimeError(f"Engine {engine_key!r} failed its health check")

    bus = getattr(app.state, "bus", None)
    wrapped_engine = setup_security(config, raw_engine, bus).engine

    # Peel off the telemetry (InstrumentedEngine) layer, if present, to find
    # what it wraps: either a MultiEngine (local + cloud) or the security
    # wrapped engine directly.
    outer = app.state.engine
    telemetry_holder = outer if hasattr(outer, "_inner") else None
    inner = telemetry_holder._inner if telemetry_holder is not None else outer

    if isinstance(inner, MultiEngine):
        # Keep the cloud entry (if any); replace every local entry with the
        # freshly built + wrapped engine under the new engine key.
        kept = [(k, e) for k, e in inner._engines if k == "cloud"]
        kept.append((engine_key, wrapped_engine))
        inner._engines = kept
        inner._refresh_map()
    elif telemetry_holder is not None:
        telemetry_holder._inner = wrapped_engine
    else:
        app.state.engine = wrapped_engine

    app.state.engine_name = engine_key
    app.state.model = config.intelligence.default_model


@router.get("")
async def get_config(request: Request) -> dict:
    """Return the config fields the Settings view can display and edit."""
    from orion.core.config import load_config

    config = getattr(request.app.state, "config", None) or load_config()

    available_models: list[dict[str, str]] = []
    try:
        from orion.engine._discovery import discover_engines, discover_models

        engines = discover_engines(config)
        by_engine = discover_models(engines)
        for engine_key, model_ids in by_engine.items():
            for model_id in model_ids:
                available_models.append({"id": model_id, "engine": engine_key})
    except Exception:
        logger.debug("Model discovery failed for GET /v1/config", exc_info=True)

    return {
        "model": getattr(request.app.state, "model", "")
        or config.intelligence.default_model,
        "engine": getattr(request.app.state, "engine_name", "") or config.engine.default,
        "temperature": config.intelligence.temperature,
        "max_tokens": config.intelligence.max_tokens,
        "obsidian_dir": config.tools.storage.obsidian_dir,
        "learning_enabled": config.learning.enabled,
        "available_models": available_models,
    }


@router.post("")
async def update_config(req: ConfigUpdateRequest, request: Request) -> dict:
    """Apply a partial config update: persist to TOML, apply live, hot-reload if needed."""
    from orion.core.config import load_config, validate_config_key

    config = getattr(request.app.state, "config", None)
    if config is None:
        config = load_config()
        request.app.state.config = config

    updates: dict[str, Any] = {}
    for field_name, dotted_key in _FIELD_TO_KEY.items():
        value = getattr(req, field_name)
        if value is None:
            continue
        try:
            validate_config_key(dotted_key)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        updates[dotted_key] = value

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    # Reject an unknown engine key up front — persisting it would leave
    # config.toml pointing at a backend `get_engine()` can never resolve,
    # bricking the server on its next restart. A *known but unreachable*
    # engine (bad host, missing API key) still persists — same as
    # `orion config set`, which warns but saves anyway.
    if req.engine is not None:
        from orion.core.registry import EngineRegistry

        if not EngineRegistry.contains(req.engine):
            raise HTTPException(
                status_code=400, detail=f"Unknown engine: {req.engine!r}"
            )

    # Persist to disk first — if this fails, nothing changes live.
    try:
        _persist(updates)
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to write config: {exc}"
        ) from exc

    for dotted_key, value in updates.items():
        _apply_live(config, dotted_key, value)

    reloaded = False
    reload_error = None
    if req.engine is not None:
        # Backend swap (e.g. ollama -> nvidia) — rebuild the engine object.
        try:
            _hot_reload_engine(request.app, config)
            reloaded = True
        except Exception as exc:
            logger.warning("Engine hot-reload failed: %s", exc)
            reload_error = str(exc)
    elif req.model is not None:
        # Same backend, new default model — engines take `model` per call,
        # so just update the fallback default; no engine rebuild needed.
        request.app.state.model = config.intelligence.default_model

    return {
        "status": "ok",
        "updated": sorted(updates.keys()),
        "engine_reloaded": reloaded,
        "reload_error": reload_error,
    }


__all__ = ["router"]
