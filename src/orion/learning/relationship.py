"""A real, plain-language summary of interaction patterns.

Not a new store -- reads straight from the memory graph
(`tools/storage/knowledge_graph.py`, real and persistent) and the trace
store (`traces/store.py`, real and populated since the memory/learning
work this session). Every number here is counted from what's actually
there; nothing is invented to make the summary feel richer than the real
history supports.
"""

from __future__ import annotations

import logging
import time
from collections import Counter
from typing import Any, Dict

logger = logging.getLogger(__name__)

_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "to", "of", "in", "on",
    "for", "and", "or", "what", "how", "why", "do", "does", "did", "can",
    "i", "you", "me", "my", "it", "this", "that", "with", "about", "user",
    "orion",
}


def _extract_keywords(text: str, limit: int = 3) -> list[str]:
    words = [w.strip(".,!?:;\"'").lower() for w in text.split()]
    words = [w for w in words if len(w) > 3 and w not in _STOPWORDS]
    return words[:limit]


def compute_relationship_summary(*, kg_path, trace_store=None) -> Dict[str, Any]:
    """Real counts and a plain-language line built from them. Returns an
    honest "not enough history yet" summary rather than padding with
    invented detail when there's little to go on.
    """
    summary: Dict[str, Any] = {
        "total_memories": 0,
        "days_active": 0,
        "recurring_topics": [],
        "acceptance_rate": None,
        "text": "",
    }

    if not kg_path.exists():
        summary["text"] = "No history yet — this fills in as you talk to Orion."
        return summary

    try:
        from orion.tools.storage.knowledge_graph import KnowledgeGraphMemory

        kg = KnowledgeGraphMemory(db_path=kg_path)
        try:
            rows = kg._conn.execute(
                "SELECT name, created_at FROM entities WHERE entity_type = 'memory'"
            ).fetchall()
        finally:
            kg.close()
    except Exception:
        logger.debug("Relationship summary: graph read failed", exc_info=True)
        rows = []

    summary["total_memories"] = len(rows)
    if rows:
        days = {time.strftime("%Y-%m-%d", time.localtime(r[1])) for r in rows if r[1]}
        summary["days_active"] = len(days)

        word_counts: Counter[str] = Counter()
        for name, _ in rows:
            word_counts.update(_extract_keywords(name or ""))
        summary["recurring_topics"] = [w for w, _ in word_counts.most_common(3)]

    if trace_store is not None:
        try:
            recent = trace_store.list_traces(limit=50)
            scored = [t for t in recent if t.outcome in ("success", "error")]
            if scored:
                summary["acceptance_rate"] = sum(
                    1 for t in scored if t.outcome == "success"
                ) / len(scored)
        except Exception:
            logger.debug("Relationship summary: trace read failed", exc_info=True)

    summary["text"] = _render_text(summary)
    return summary


def _render_text(summary: Dict[str, Any]) -> str:
    if summary["total_memories"] == 0:
        return "No history yet — this fills in as you talk to Orion."

    parts = [
        f"{summary['total_memories']} "
        f"{'memory' if summary['total_memories'] == 1 else 'memories'} "
        f"across {summary['days_active']} "
        f"{'day' if summary['days_active'] == 1 else 'days'}"
    ]
    if summary["recurring_topics"]:
        parts.append("mostly about " + ", ".join(summary["recurring_topics"]))
    if summary["acceptance_rate"] is not None:
        parts.append(f"{summary['acceptance_rate'] * 100:.0f}% of recent tasks landed cleanly")
    return " — ".join(parts) + "."


__all__ = ["compute_relationship_summary"]
