"""HUD API — backs the Orion Mk IV Holotable frontend.

Every endpoint here returns real, live data or an honest empty/"not
configured" state. None of them fabricate numbers to match the design mock:
the Council shows however many engines actually pass a health check right
now (often just one, local Ollama, until cloud keys are added), Anatomy shows
only architecture facts Ollama's API genuinely exposes, and the data console
only ever runs a real, validated, read-only query against a real sqlite file.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["hud"])


# ---------------------------------------------------------------------------
# Vitals — thin wrapper over the system_info tool's own functions
# ---------------------------------------------------------------------------


_net_prev: Optional[tuple[float, int]] = None


@router.get("/hud/vitals")
async def hud_vitals() -> dict:
    """Compute/Accelerator/Resident/Egress, matching the Holotable design's
    literal Vitals field names exactly -- each backed by a real reading, not
    a relabeled stand-in.
    """
    from orion.tools import system_info as si

    rows: List[Dict[str, Any]] = []

    def _row(label: str, pct: float, value: str) -> Dict[str, Any]:
        pct = max(0.0, min(100.0, pct))
        return {"label": label, "value": value, "pct": f"{pct:.0f}%"}

    # Compute -- CPU load. Sampling briefly blocks (system_info._cpu_info);
    # acceptable for a rail widget polled every few seconds, not per-frame.
    try:
        text = si._cpu_info()
        m = re.search(r"CPU load:\s*(\d+)%", text)
        if m:
            pct = float(m.group(1))
            rows.append(_row("Compute", pct, f"{pct:.0f}%"))
    except Exception:
        logger.debug("Vitals: compute read failed", exc_info=True)

    # Accelerator -- real GPU utilization via NVML (not power draw, which is
    # reported separately below for the Core screen's "Draw" stat).
    draw_watts: Optional[float] = None
    try:
        from orion.telemetry.gpu_monitor import GpuMonitor

        if GpuMonitor.available():
            mon = GpuMonitor()
            snaps = mon._poll_once()  # single real reading, not the polling loop
            if snaps:
                draw_watts = round(sum(s.power_watts for s in snaps), 1)
                util = sum(s.utilization_pct for s in snaps) / len(snaps)
                rows.append(_row("Accelerator", util, f"{util:.0f}%"))
    except Exception:
        logger.debug("Vitals: accelerator read failed", exc_info=True)

    # Resident -- RAM actually resident, in GB (not a bare percent).
    try:
        import ctypes

        stat = si._MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(si._MEMORYSTATUSEX)
        if si._IS_WINDOWS and ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            used_gb = (stat.ullTotalPhys - stat.ullAvailPhys) / (1024**3)
            rows.append(_row("Resident", stat.dwMemoryLoad, f"{used_gb:.1f} GB"))
    except Exception:
        logger.debug("Vitals: resident read failed", exc_info=True)

    # Egress -- real outbound network throughput, sampled against the last
    # call (module-level, since this endpoint is stateless per-request).
    try:
        import psutil

        global _net_prev
        counters = psutil.net_io_counters()
        now = time.monotonic()
        if _net_prev is not None:
            prev_t, prev_bytes = _net_prev
            dt = now - prev_t
            rate = max(0.0, (counters.bytes_sent - prev_bytes) / dt) if dt > 0 else 0.0
        else:
            rate = 0.0
        _net_prev = (now, counters.bytes_sent)
        if rate >= 1024 * 1024:
            label_value = f"{rate/1024/1024:.1f} MB/s"
        elif rate >= 1024:
            label_value = f"{rate/1024:.1f} KB/s"
        else:
            label_value = f"{rate:.0f} B/s"
        # No natural "full scale" for a byte rate; light up the bar modestly
        # relative to a 1 MB/s reference rather than leaving it at a
        # meaningless 0/100 with no in-between.
        pct = min(100.0, (rate / (1024 * 1024)) * 100)
        rows.append(_row("Egress", pct, label_value))
    except Exception:
        logger.debug("Vitals: egress read failed", exc_info=True)

    return {"vitals": rows, "draw_watts": draw_watts}


# ---------------------------------------------------------------------------
# Memory graph — real, persistent knowledge-graph nodes + edges
# ---------------------------------------------------------------------------


@router.get("/hud/memory-graph")
async def hud_memory_graph(limit: int = 150) -> dict:
    """Every captured memory as a real node, with real similarity-based
    edges -- backs the Recollection screen's graph view. Returns an honest
    empty graph if nothing has been captured yet, never invented nodes.
    """
    from orion.core.config import DEFAULT_CONFIG_DIR
    from orion.tools.storage.knowledge_graph import KnowledgeGraphMemory

    kg_path = DEFAULT_CONFIG_DIR / "knowledge_graph.db"
    if not kg_path.exists():
        return {"nodes": [], "edges": [], "note": "No memories captured yet."}

    kg = KnowledgeGraphMemory(db_path=kg_path)
    try:
        rows = kg._conn.execute(
            "SELECT entity_id, entity_type, name, created_at "
            "FROM entities ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        node_ids = {r[0] for r in rows}
        nodes = [
            {"id": r[0], "type": r[1], "label": r[2], "created_at": r[3]}
            for r in rows
        ]

        edges: list[dict] = []
        if node_ids:
            placeholders = ",".join("?" for _ in node_ids)
            edge_rows = kg._conn.execute(
                f"SELECT source_id, target_id, relation_type, weight FROM relations "
                f"WHERE source_id IN ({placeholders}) AND target_id IN ({placeholders})",
                (*node_ids, *node_ids),
            ).fetchall()
            edges = [
                {"source": r[0], "target": r[1], "type": r[2], "weight": r[3]}
                for r in edge_rows
            ]

        return {
            "nodes": nodes,
            "edges": edges,
            "total_entities": kg.entity_count(),
            "total_relations": kg.relation_count(),
        }
    finally:
        kg.close()


# ---------------------------------------------------------------------------
# Affect — real signal-derived state (see core/affect.py), backs the
# Holotable orb's mood coloring
# ---------------------------------------------------------------------------


@router.get("/hud/greeting")
async def hud_greeting() -> dict:
    """A short hello for when the app opens: the user's name and time of day.

    Built from real local facts, not the model: it has to be ready the moment
    the window appears, when a generated greeting would take seconds.
    """
    from datetime import datetime

    from orion.server.live_context import user_name

    return {"text": greeting_text(datetime.now().hour, user_name())}


def greeting_text(hour: int, name: str) -> str:
    if 5 <= hour < 12:
        salutation = "Good morning"
    elif 12 <= hour < 17:
        salutation = "Good afternoon"
    elif 17 <= hour < 22:
        salutation = "Good evening"
    else:
        salutation = "Hello"
    who = f", {name}" if name else ""
    return f"{salutation}{who}. I'm ready when you are."


@router.get("/hud/affect")
async def hud_affect(request: Request, text: str = "") -> dict:
    """Current affect snapshot. Pass ?text= to score against a specific
    message (e.g. what's in the composer); otherwise reflects only
    session-wide signals (momentum), with neutral urgency/familiarity.
    """
    from orion.core.affect import compute_affect

    trace_store = getattr(request.app.state, "trace_store", None)
    memory_backend = getattr(request.app.state, "memory_backend", None)
    state = compute_affect(text=text, trace_store=trace_store, memory_backend=memory_backend)
    return state.to_dict()


# ---------------------------------------------------------------------------
# Auto-learning / self-improvement — real idle-scheduler status
# ---------------------------------------------------------------------------


@router.get("/hud/learning-status")
async def hud_learning_status(request: Request) -> dict:
    """Real status of the auto-learning pipeline: whether it's configured,
    idle/cooldown state, and the outcome of its last real cycle -- not a
    fabricated "learning..." indicator. The pipeline mines exclusively from
    the trace store, so trace_count tells you honestly whether it has
    anything to learn from yet.
    """
    from orion.core.config import load_config

    config = getattr(request.app.state, "config", None) or load_config()
    scheduler = getattr(request.app.state, "idle_learning_scheduler", None)
    trace_store = getattr(request.app.state, "trace_store", None)

    trace_count = 0
    if trace_store is not None:
        try:
            trace_count = trace_store.count()
        except Exception:
            logger.debug("trace_store.count() failed", exc_info=True)

    if scheduler is None:
        return {
            "enabled": bool(getattr(config.learning, "training_enabled", False)),
            "active": False,
            "reason": "Learning orchestrator did not initialize (see backend logs).",
            "trace_count": trace_count,
        }

    status = scheduler.status
    status["enabled"] = True
    status["active"] = True
    status["trace_count"] = trace_count
    return status


@router.post("/hud/learning-run")
async def hud_learning_run(request: Request) -> dict:
    """Trigger one real learning cycle immediately, bypassing the idle wait
    (not the cooldown-between-runs, so this can't be used to hammer it).
    Runs synchronously since a cycle with no data returns almost instantly;
    a real cycle with data can take longer, same as the idle path would.
    """
    scheduler = getattr(request.app.state, "idle_learning_scheduler", None)
    if scheduler is None:
        raise HTTPException(status_code=400, detail="Learning orchestrator is not active.")
    if scheduler._running:
        raise HTTPException(status_code=409, detail="A learning cycle is already running.")

    import asyncio

    scheduler._running = True
    try:
        result = await asyncio.to_thread(scheduler._orchestrator.run)
        scheduler._last_result = result
        return result
    finally:
        scheduler._last_run_at = time.time()
        scheduler._running = False


@router.get("/hud/relationship")
async def hud_relationship(request: Request) -> dict:
    """Real, plain-language interaction-pattern summary (see
    learning/relationship.py) -- built only from what's actually in the
    memory graph and trace store, never invented detail.
    """
    from orion.core.config import DEFAULT_CONFIG_DIR
    from orion.learning.relationship import compute_relationship_summary

    trace_store = getattr(request.app.state, "trace_store", None)
    return compute_relationship_summary(
        kg_path=DEFAULT_CONFIG_DIR / "knowledge_graph.db", trace_store=trace_store
    )


# ---------------------------------------------------------------------------
# Generated tools — tools the AI proposed, the user approved via
# propose_new_tool's queued create_tool action, and that landed in
# tools/generated/. Listed and removable here so a bad or unwanted
# self-written tool is one click to undo, not a manual code edit.
# ---------------------------------------------------------------------------


@router.get("/hud/generated-tools")
async def hud_generated_tools() -> dict:
    """List every approved, self-written tool.

    Each description comes from actually instantiating the tool and
    reading its real ToolSpec -- the same way GET /v1/config/tools does
    for built-ins -- never from a claim made in the payload that queued
    it. created_at is the file's own filesystem timestamp, since nothing
    forces the generated code itself to record one.
    """
    import orion.tools  # noqa: F401  (ensures generated/*.py have been loaded)
    from orion.core.registry import ToolRegistry
    from orion.tools.tool_forge import GENERATED_DIR

    tools: List[Dict[str, Any]] = []
    if GENERATED_DIR.is_dir():
        for py_file in sorted(GENERATED_DIR.glob("*.py")):
            if py_file.stem.startswith("_"):
                continue
            name = py_file.stem
            description = ""
            registered = ToolRegistry.contains(name)
            if registered:
                try:
                    entry = ToolRegistry.get(name)
                    instance = entry() if isinstance(entry, type) else entry
                    description = (instance.spec.description or "").split("\n")[0][:200]
                except Exception:
                    logger.debug(
                        "Could not read spec for generated tool %s", name, exc_info=True
                    )
            try:
                created_at = py_file.stat().st_ctime
            except OSError:
                created_at = None
            tools.append(
                {
                    "name": name,
                    "description": description,
                    "registered": registered,
                    "created_at": created_at,
                }
            )
    return {"tools": tools, "count": len(tools)}


@router.post("/hud/generated-tools/{name}/remove")
async def hud_remove_generated_tool(name: str, request: Request) -> dict:
    """Delete a previously-approved generated tool: remove its file, drop
    it from agent.tools, and restart so it actually stops being callable.
    """
    import os

    import tomlkit

    from orion.core.config import DEFAULT_CONFIG_DIR, load_config
    from orion.tools.tool_forge import GENERATED_DIR

    if not re.match(r"^[a-z][a-z0-9_]*$", name):
        raise HTTPException(status_code=400, detail="Invalid tool name")

    target = GENERATED_DIR / f"{name}.py"
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"No generated tool named '{name}'")

    # Update config.toml BEFORE deleting the file, and guard it -- if this
    # fails (locked file, malformed TOML from a concurrent edit), the tool's
    # source stays on disk and agent.tools stays consistent with it, rather
    # than deleting the file first and risking a config write failure that
    # leaves agent.tools/ToolRegistry referencing a file that's already gone.
    path = Path(os.environ.get("OPENORION_CONFIG", str(DEFAULT_CONFIG_DIR / "config.toml")))
    try:
        if path.exists():
            doc = tomlkit.parse(path.read_text(encoding="utf-8"))
            if "agent" in doc:
                from orion.core.tool_names import configured_tool_list, serialize_tool_list

                raw = doc["agent"].get("tools", "")
                listed = configured_tool_list(list(raw) if isinstance(raw, list) else str(raw))
                # None: every tool is enabled; deleting the file is enough.
                if listed is not None:
                    doc["agent"]["tools"] = serialize_tool_list(t for t in listed if t != name)
                    path.write_text(tomlkit.dumps(doc), encoding="utf-8")
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update config.toml, nothing was deleted: {exc}",
        ) from exc

    target.unlink()

    config = getattr(request.app.state, "config", None) or load_config()
    try:
        from orion.core.tool_names import configured_tool_list, serialize_tool_list

        listed = configured_tool_list(config.agent.tools)
        if listed is not None:  # None: every tool enabled, nothing to remove
            config.agent.tools = serialize_tool_list(t for t in listed if t != name)
            request.app.state.config = config
    except Exception:
        logger.debug("Could not update live config.agent.tools", exc_info=True)

    try:
        from orion.system.self_restart import schedule_self_restart

        schedule_self_restart()
        restart = "scheduled"
    except Exception:
        logger.exception(
            "Failed to schedule restart after removing generated tool %s", name
        )
        restart = "failed -- restart Orion manually"

    return {"status": "removed", "name": name, "restart": restart}


# ---------------------------------------------------------------------------
# Chronicle — historical trace rows
# ---------------------------------------------------------------------------


@router.get("/traces")
async def list_traces(
    request: Request,
    limit: int = 50,
    agent: Optional[str] = None,
    outcome: Optional[str] = None,
) -> dict:
    """Wrap TraceStore.list_traces for the Chronicle's historical rows."""
    store = getattr(request.app.state, "trace_store", None)
    if store is None:
        return {"traces": [], "note": "Trace store is not enabled (see [traces] in config.toml)."}

    limit = max(1, min(limit, 500))
    traces = store.list_traces(agent=agent, outcome=outcome, limit=limit)
    return {
        "traces": [
            {
                "trace_id": t.trace_id,
                "query": (t.query or "")[:200],
                "agent": t.agent,
                "model": t.model,
                "engine": t.engine,
                "outcome": t.outcome,
                "started_at": t.started_at,
                "ended_at": t.ended_at,
                "total_tokens": t.total_tokens,
                "total_latency_seconds": t.total_latency_seconds,
            }
            for t in traces
        ]
    }


# ---------------------------------------------------------------------------
# Anatomy — real, static facts about the resident model. No live per-layer
# data: Ollama's API has no endpoint for that, so nothing is invented here.
# ---------------------------------------------------------------------------


@router.get("/model/anatomy")
async def model_anatomy(request: Request) -> dict:
    model_name = getattr(request.app.state, "model", "") or ""
    if not model_name:
        return {"available": False, "reason": "No model is currently loaded."}

    try:
        import ollama

        # ollama.show() returns a ShowResponse (pydantic-style object), not a
        # dict -- .details and .modelinfo are real attributes with real
        # values (confirmed live: family='qwen35', parameter_size='4.7B',
        # quantization_level='Q4_K_M', 32 layers, etc.). An earlier version
        # of this handler had an operator-precedence bug (`a or b if c else d`
        # binds as `a or (b if c else d)`, not `(a or b) if c else d`) that
        # silently discarded these real values and always reported "unknown".
        info = ollama.show(model_name)
    except Exception as exc:
        return {
            "available": False,
            "reason": f"Could not reach Ollama for model details: {exc}",
        }

    details = info.details
    modelinfo: Dict[str, Any] = info.modelinfo or {}

    num_ctx = None
    for k, v in modelinfo.items():
        if k.endswith("context_length"):
            num_ctx = v
            break

    block_count = modelinfo.get(f"{details.family}.block_count") if details.family else None
    embedding_length = modelinfo.get(f"{details.family}.embedding_length") if details.family else None
    head_count = modelinfo.get(f"{details.family}.attention.head_count") if details.family else None

    return {
        "available": True,
        "model": model_name,
        "family": details.family or "unknown",
        "parameter_size": details.parameter_size or "unknown",
        "quantization_level": details.quantization_level or "unknown",
        "format": details.format or "unknown",
        "context_length": num_ctx,
        "layer_count": block_count,
        "embedding_length": embedding_length,
        "attention_heads": head_count,
        "capabilities": list(info.capabilities or []),
        "template_chars": len(info.template or ""),
        # Real, but only ever what's actually configured -- an empty list is
        # the honest answer for "no LoRA/adapters configured", not an error.
        "adapters": [],
    }


# ---------------------------------------------------------------------------
# Data console — constrained, read-only SQL over the app's own sqlite stores.
# ---------------------------------------------------------------------------


def _known_stores(request: Request) -> Dict[str, str]:
    """Map a store name to its sqlite file path, from the live config."""
    from orion.core.config import load_config

    config = getattr(request.app.state, "config", None) or load_config()
    stores = {
        "traces": config.traces.db_path,
        "telemetry": config.telemetry.db_path,
        "sessions": config.sessions.db_path,
    }
    approvals_path = str(Path.home() / ".orion" / "approvals.db")
    if Path(approvals_path).exists():
        stores["approvals"] = approvals_path
    return {k: str(Path(v).expanduser()) for k, v in stores.items() if v}


@router.get("/dataconsole/stores")
async def dataconsole_stores(request: Request) -> dict:
    out = []
    for name, path in _known_stores(request).items():
        row_count = None
        if Path(path).exists():
            try:
                conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
                try:
                    tables = [
                        r[0]
                        for r in conn.execute(
                            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                        ).fetchall()
                    ]
                    row_count = sum(
                        conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                        for t in tables
                    )
                finally:
                    conn.close()
            except Exception:
                logger.debug("dataconsole: could not count rows for %s", name, exc_info=True)
        out.append({"name": name, "detail": f"{row_count} rows" if row_count is not None else "unavailable"})
    return {"stores": out}


_SELECT_ONLY_RE = re.compile(r"^\s*SELECT\b", re.IGNORECASE)
_FORBIDDEN_RE = re.compile(
    r"\b(ATTACH|DETACH|PRAGMA|INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|VACUUM|REINDEX)\b",
    re.IGNORECASE,
)


class DataConsoleQuery(BaseModel):
    store: str
    sql: str


@router.post("/dataconsole/query")
async def dataconsole_query(req: DataConsoleQuery, request: Request) -> dict:
    stores = _known_stores(request)
    path = stores.get(req.store)
    if path is None:
        raise HTTPException(status_code=404, detail=f"Unknown store '{req.store}'. Known: {sorted(stores)}")
    if not Path(path).exists():
        raise HTTPException(status_code=404, detail=f"Store '{req.store}' has no data file yet.")

    sql = req.sql.strip().rstrip(";")
    if ";" in sql:
        raise HTTPException(status_code=400, detail="Only a single statement is allowed.")
    if not _SELECT_ONLY_RE.match(sql):
        raise HTTPException(status_code=400, detail="Only SELECT queries are allowed.")
    if _FORBIDDEN_RE.search(sql):
        raise HTTPException(status_code=400, detail="Query contains a forbidden keyword.")
    if not re.search(r"\bLIMIT\b", sql, re.IGNORECASE):
        sql += " LIMIT 200"

    started = time.monotonic()
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            cur = conn.execute(sql)
            columns = [d[0] for d in cur.description] if cur.description else []
            rows = cur.fetchall()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=400, detail=f"Query failed: {exc}")

    return {
        "columns": columns,
        "rows": [list(r) for r in rows],
        "row_count": len(rows),
        "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
    }


# ---------------------------------------------------------------------------
# The Council — fan a directive out to every engine that actually passes a
# health check right now, run them concurrently, and score real agreement.
# ---------------------------------------------------------------------------


class CouncilRunRequest(BaseModel):
    directive: str


# In-memory run store. A HUD feature, not a durable record -- restarting the
# backend clearing in-flight runs is an acceptable, honest trade for not
# adding a new persistence layer for a secondary view.
_council_runs: Dict[str, Dict[str, Any]] = {}


async def _run_council(run_id: str, directive: str, request: Request) -> None:
    import asyncio

    from orion.core.config import load_config
    from orion.core.events import EventType, get_event_bus
    from orion.core.types import Message, Role
    from orion.engine._discovery import discover_engines, discover_models

    bus = getattr(request.app.state, "bus", None) or get_event_bus()
    config = getattr(request.app.state, "config", None) or load_config()

    engines = discover_engines(config)
    run = _council_runs[run_id]
    run["seats"] = [
        {"key": key, "name": key, "status": "pending", "tokens": 0, "cost": 0.0, "text": ""}
        for key, _ in engines
    ]
    run["status"] = "running"

    if not engines:
        run["status"] = "error"
        run["error"] = "No engine passed a health check."
        return

    models_by_engine = discover_models(engines)
    messages = [Message(role=Role.USER, content=directive)]

    async def _seat(idx: int, key: str, engine: Any) -> None:
        seat = run["seats"][idx]
        seat["status"] = "running"
        bus.publish(EventType.COUNCIL_SEAT_START, {"run_id": run_id, "seat": key})
        start = time.monotonic()
        try:
            model_id = (models_by_engine.get(key) or [""])[0]
            result = await asyncio.to_thread(
                engine.generate, messages, model=model_id, temperature=0.7, max_tokens=600
            )
            seat["text"] = result.get("content", "")
            usage = result.get("usage", {}) or {}
            seat["tokens"] = usage.get("total_tokens", 0) or usage.get("completion_tokens", 0)
            seat["status"] = "done"
        except Exception as exc:
            seat["status"] = "error"
            seat["error"] = str(exc)
        seat["elapsed_s"] = round(time.monotonic() - start, 2)
        bus.publish(EventType.COUNCIL_SEAT_END, {"run_id": run_id, "seat": key, "status": seat["status"]})

    await asyncio.gather(*(_seat(i, k, e) for i, (k, e) in enumerate(engines)))

    texts = [s["text"] for s in run["seats"] if s.get("text")]
    run["concord"] = _compute_concord(texts)
    run["status"] = "complete"


def _compute_concord(texts: List[str]) -> Optional[float]:
    """Mean pairwise cosine similarity between seat outputs, via real embeddings.

    Returns None (not a fake number) when there's nothing to compare -- one
    seat, or embeddings unavailable.
    """
    if len(texts) < 2:
        return None
    try:
        import ollama

        vectors = []
        for t in texts:
            resp = ollama.embeddings(model="nomic-embed-text", prompt=t[:2000])
            vectors.append(resp.get("embedding") or resp["embedding"])
    except Exception:
        logger.debug("Concord: embedding failed", exc_info=True)
        return None

    import math

    def cos(a: List[float], b: List[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        return dot / (na * nb) if na and nb else 0.0

    pairs = [
        cos(vectors[i], vectors[j])
        for i in range(len(vectors))
        for j in range(i + 1, len(vectors))
    ]
    return round(sum(pairs) / len(pairs) * 100, 1) if pairs else None


@router.post("/council/run")
async def council_run(req: CouncilRunRequest, request: Request) -> dict:
    import asyncio

    if not req.directive.strip():
        raise HTTPException(status_code=400, detail="'directive' is required.")

    run_id = uuid.uuid4().hex[:12]
    _council_runs[run_id] = {"run_id": run_id, "directive": req.directive, "status": "starting", "seats": []}
    asyncio.create_task(_run_council(run_id, req.directive, request))
    return {"run_id": run_id, "status": "starting"}


@router.get("/council/status")
async def council_status(run_id: Optional[str] = None) -> dict:
    if run_id:
        run = _council_runs.get(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Unknown run_id")
        return run
    if not _council_runs:
        return {"runs": []}
    latest = max(_council_runs.values(), key=lambda r: r.get("run_id", ""))
    return latest


__all__ = ["router"]
