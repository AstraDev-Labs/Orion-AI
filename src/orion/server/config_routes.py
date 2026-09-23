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
        # Windows defaults str.open()/read_text() to the system codepage, not
        # UTF-8 -- this file can (and does) contain non-ASCII bytes, so an
        # unspecified encoding here fails with a UnicodeDecodeError on any
        # config write, real or synthetic.
        doc = tomlkit.parse(path.read_text(encoding="utf-8"))
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

    path.write_text(tomlkit.dumps(doc), encoding="utf-8")


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
    if req.model is not None:
        from orion.server.chat_models import model_purpose

        if model_purpose(req.model) != "chat":
            raise HTTPException(status_code=400, detail="Choose a chat model as the default. Vision and embedding models are used by their respective tools.")
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


from orion.core.tool_names import INTERNAL_TOOLS, enabled_tool_names, serialize_tool_list  # noqa: E402


def _enabled_tool_list(config) -> list[str]:
    """Tools the agent has; an unset list means all of them (core/tool_names.py)."""
    import orion.tools  # noqa: F401  -- triggers @ToolRegistry.register
    from orion.core.registry import ToolRegistry

    return enabled_tool_names(config.agent.tools, ToolRegistry.keys())


@router.get("/tools")
async def get_tools(request: Request) -> dict:
    """List every registered tool and whether the agent currently has it.

    The registry is the source of truth for what exists; ``[agent] tools`` in
    the TOML decides what the agent is actually handed. Those two drift apart
    easily -- a tool can be registered, look present, and still be unreachable
    by the model, which is exactly how computer_control sat unusable after
    being built. Showing both together makes that visible.
    """
    import orion.tools  # noqa: F401  -- triggers @ToolRegistry.register
    from orion.core.config import load_config
    from orion.core.registry import ToolRegistry
    from orion.tools.tool_forge import GENERATED_DIR

    config = getattr(request.app.state, "config", None) or load_config()
    enabled = set(_enabled_tool_list(config))

    tools = []
    for name in sorted(ToolRegistry.keys()):
        # Generated (AI-authored, user-approved) tools get their own
        # dedicated panel -- GET /v1/hud/generated-tools, with a Remove
        # action that deletes the file and restarts. Listing them here too
        # would give two independent on/off controls for the same tool
        # (this grid's toggle only edits agent.tools) that can silently
        # disagree about whether the tool is actually active.
        if (GENERATED_DIR / f"{name}.py").exists() or name in INTERNAL_TOOLS:
            continue
        description = ""
        try:
            entry = ToolRegistry.get(name)
            instance = entry() if isinstance(entry, type) else entry
            description = (instance.spec.description or "").split("\n")[0][:160]
        except Exception:
            pass  # a tool that cannot be instantiated still deserves a row
        tools.append(
            {"name": name, "enabled": name in enabled, "description": description}
        )

    return {"tools": tools, "enabled_count": len(enabled)}


class ToolToggleRequest(BaseModel):
    name: str
    enabled: bool


@router.post("/tools")
async def toggle_tool(req: ToolToggleRequest, request: Request) -> dict:
    """Add or remove a tool from the agent's enabled list, persisted to TOML."""
    import orion.tools  # noqa: F401
    from orion.core.config import load_config
    from orion.core.registry import ToolRegistry

    if req.name not in set(ToolRegistry.keys()):
        raise HTTPException(status_code=404, detail=f"Unknown tool '{req.name}'")
    if req.enabled and req.name in INTERNAL_TOOLS:
        raise HTTPException(status_code=400, detail=f"'{req.name}' is internal and cannot be enabled.")

    config = getattr(request.app.state, "config", None) or load_config()
    current = _enabled_tool_list(config)

    if req.enabled and req.name not in current:
        current.append(req.name)
    elif not req.enabled and req.name in current:
        current = [t for t in current if t != req.name]

    # An explicit list from here on; "none" if the last tool was switched off
    # (an empty value would mean every tool).
    value = serialize_tool_list(current)
    _persist({"agent.tools": value})
    config.agent.tools = value
    request.app.state.config = config

    return {
        "status": "ok",
        "name": req.name,
        "enabled": req.enabled,
        "enabled_count": len(current),
        # The agent's tool set is built once at startup, so the TOML change is
        # persisted immediately but only takes effect on the next boot.
        "note": "Restart the backend for the agent to pick this up.",
    }


# ---------------------------------------------------------------------------
# Auto-reply — master switch + per-contact allowlist
# ---------------------------------------------------------------------------


def _allowlist(config) -> list[str]:
    raw = getattr(config.channel, "auto_reply_allowlist", "") or ""
    return [c.strip() for c in raw.split(",") if c.strip()]


@router.get("/auto-reply")
async def get_auto_reply(request: Request) -> dict:
    """Auto-reply's own settings: enabled + which senders it's allowed to
    answer. Independent of ``channel.enabled`` (whether the channel is
    connected at all) -- this only gates whether Orion replies on the
    owner's behalf while away.
    """
    from orion.core.config import load_config

    config = getattr(request.app.state, "config", None) or load_config()
    return {
        "enabled": bool(getattr(config.channel, "auto_reply_enabled", True)),
        "allowlist": _allowlist(config),
    }


class AutoReplyUpdateRequest(BaseModel):
    enabled: Optional[bool] = None
    allowlist: Optional[list[str]] = None


@router.post("/auto-reply")
async def update_auto_reply(req: AutoReplyUpdateRequest, request: Request) -> dict:
    """Update the auto-reply master switch and/or contact allowlist.

    An empty ``allowlist`` means "everyone" (today's default behavior) --
    this is an opt-in restriction, not opt-out.
    """
    from orion.core.config import load_config

    config = getattr(request.app.state, "config", None) or load_config()

    updates: dict[str, Any] = {}
    if req.enabled is not None:
        updates["channel.auto_reply_enabled"] = req.enabled
    if req.allowlist is not None:
        cleaned = [c.strip() for c in req.allowlist if c.strip()]
        updates["channel.auto_reply_allowlist"] = ",".join(cleaned)

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    try:
        _persist(updates)
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to write config: {exc}"
        ) from exc

    for dotted_key, value in updates.items():
        _apply_live(config, dotted_key, value)
    request.app.state.config = config

    return {
        "status": "ok",
        "enabled": bool(getattr(config.channel, "auto_reply_enabled", True)),
        "allowlist": _allowlist(config),
    }


__all__ = ["router"]
