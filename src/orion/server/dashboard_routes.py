import logging
import re
from pathlib import Path

from fastapi import APIRouter, Request

logger = logging.getLogger(__name__)

dashboard_router = APIRouter(prefix="/v1", tags=["dashboard"])

def _get_app_config(request: Request):
    config = getattr(request.app.state, "config", None)
    if not config:
        from orion.core.config import load_config
        config = load_config()
    return config

@dashboard_router.get("/obsidian/graph")
async def get_obsidian_graph(request: Request):
    """Return nodes and edges from Obsidian Vault."""
    try:
        config = _get_app_config(request)
        obsidian_dir = config.memory.obsidian_dir
        if not obsidian_dir:
            return {"nodes": [], "edges": []}

        vault_path = Path(obsidian_dir).expanduser().resolve()
        if not vault_path.exists() or not vault_path.is_dir():
            return {"nodes": [], "edges": []}

        nodes = []
        edges = []
        node_indices = {}
        idx = 0

        # Simple markdown file scanner
        for file in vault_path.rglob("*.md"):
            if ".obsidian" in file.parts or ".trash" in file.parts:
                continue

            name = file.stem
            if name not in node_indices:
                node_indices[name] = idx
                nodes.append({"id": str(idx), "label": name, "path": str(file)})
                idx += 1

        # Extract links [[Link]]
        link_pattern = re.compile(r"\[\[(.*?)\]\]")
        for node in nodes:
            file_path = Path(node["path"])
            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                links = link_pattern.findall(content)
                for link in links:
                    # Obsidian links can have aliases [[Link|Alias]]
                    target = link.split("|")[0].strip()
                    if target in node_indices:
                        edges.append({"source": node["id"], "target": str(node_indices[target])})
            except Exception:
                pass

        return {"nodes": nodes, "edges": edges}
    except Exception as exc:
        logger.error(f"Error getting obsidian graph: {exc}")
        return {"nodes": [], "edges": []}

@dashboard_router.get("/tasks")
async def get_active_tasks(request: Request):
    """Return active tasks."""
    try:
        manager = getattr(request.app.state, "agent_manager", None)
        tasks = []
        if manager:
            try:
                raw_tasks = manager.list_tasks("default", status=None)
                if isinstance(raw_tasks, dict) and "tasks" in raw_tasks:
                    tasks = raw_tasks["tasks"]
                elif isinstance(raw_tasks, list):
                    tasks = raw_tasks
            except Exception:
                pass

        # Format for frontend
        formatted = []
        for t in tasks:
            formatted.append({
                "id": str(t.get("id", "")),
                "title": t.get("prompt", "Task")[:50],
                "context": t.get("agent", "System"),
                "status": "done" if t.get("status") == "completed" else "todo",
                "time": t.get("created_at", "Just now"),
                "priority": "normal"
            })

        return {"tasks": formatted}
    except Exception as exc:
        logger.error(f"Error getting tasks: {exc}")
        return {"tasks": []}

@dashboard_router.get("/telemetry/activities")
async def get_activities(request: Request):
    """Return recent AI operations/activities."""
    try:
        activities = []
        manager = getattr(request.app.state, "agent_manager", None)

        activities.append({
            "id": "1",
            "title": "System Active",
            "description": "Orion Dashboard initialized and connected.",
            "time": "Just now",
            "type": "system"
        })

        if manager:
            try:
                raw_tasks = manager.list_tasks("default", status="completed")
                task_list = raw_tasks["tasks"] if isinstance(raw_tasks, dict) and "tasks" in raw_tasks else (raw_tasks if isinstance(raw_tasks, list) else [])
                for idx, t in enumerate(task_list[-3:]):
                    activities.append({
                        "id": str(t.get("id", f"t_{idx}")),
                        "title": "Task Completed",
                        "description": t.get("prompt", "")[:100],
                        "time": "Recently",
                        "type": "task"
                    })
            except Exception:
                pass

        activities.reverse()
        return {"activities": activities[:10]}
    except Exception as exc:
        logger.error(f"Error getting activities: {exc}")
        return {"activities": []}
