"""Turn a completed chat exchange into a durable, connected memory.

Before this module existed, ``context_from_memory`` only ever *read* from
the memory backend -- nothing in the normal chat path ever wrote a new
memory back after a conversation, so nothing accumulated over time no
matter how long the user talked to Orion. This closes that loop: after each
real exchange, the turn is stored (persistently, via the now-persistent
:class:`~orion.tools.storage.dense.DenseMemory`) and also recorded as a
connected node in the knowledge graph, linked by real embedding-similarity
to whatever it's actually related to -- not a flat, disconnected list.
"""

from __future__ import annotations

import logging
import time
import uuid

logger = logging.getLogger(__name__)

# Skip capturing trivial exchanges (greetings, acks) -- not a real memory,
# and storing them would just dilute retrieval and clutter the graph.
_MIN_CAPTURE_CHARS = 20

# Only link to genuinely related prior memories, not everything. In
# practice nomic-embed-text similarity for two independently-phrased but
# topically related exchanges lands around 0.4-0.6, and unrelated content
# well below that -- tuned against real captured memories, not a guess.
_RELATION_MIN_SCORE = 0.4
_MAX_RELATIONS = 5


def capture_turn(
    *,
    user_text: str,
    assistant_text: str,
    memory_backend,
    channel: str = "chat",
) -> None:
    """Store one real exchange as a memory, connected to related prior ones.

    Safe to call from a background thread; swallows its own errors so a
    memory-capture failure never affects the chat response that already
    went out to the user.
    """
    try:
        user_text = (user_text or "").strip()
        assistant_text = (assistant_text or "").strip()
        if len(user_text) < _MIN_CAPTURE_CHARS or not assistant_text:
            return
        if memory_backend is None:
            return

        # Find genuinely related prior memories BEFORE storing this one, so
        # the new memory doesn't just match itself.
        related: list[tuple[str, float]] = []
        try:
            prior = memory_backend.retrieve(user_text, top_k=_MAX_RELATIONS)
            for r in prior:
                score = getattr(r, "score", None)
                doc_id = (getattr(r, "metadata", None) or {}).get("doc_id")
                if score is not None and doc_id and score >= _RELATION_MIN_SCORE:
                    related.append((doc_id, float(score)))
        except Exception:
            logger.debug("Related-memory lookup failed", exc_info=True)

        content = f"User: {user_text}\nOrion: {assistant_text[:800]}"
        new_id = str(uuid.uuid4().hex)
        try:
            stored_ids = memory_backend.store_many(
                [content],
                sources=[channel],
                metadatas=[{"kind": "conversation", "channel": channel, "timestamp": time.time()}],
            )
            if stored_ids:
                new_id = stored_ids[0]
        except Exception:
            logger.warning("Failed to persist conversation memory", exc_info=True)
            return

        _record_in_graph(new_id, user_text, content, related)
    except Exception:
        logger.warning("Memory capture failed", exc_info=True)


def _record_in_graph(
    new_id: str,
    label: str,
    content: str,
    related: list[tuple[str, float]],
) -> None:
    """Mirror the new memory into the knowledge graph as a connected node.

    The dense backend gives fast similarity search but no durable graph
    structure; the knowledge graph gives real, browsable nodes+edges. Both
    are kept in sync from the same real data rather than one faking the
    other.
    """
    try:
        from orion.core.config import DEFAULT_CONFIG_DIR
        from orion.tools.storage.knowledge_graph import (
            Entity,
            KnowledgeGraphMemory,
            Relation,
        )

        kg = KnowledgeGraphMemory(db_path=DEFAULT_CONFIG_DIR / "knowledge_graph.db")
        try:
            kg.add_entity(
                Entity(
                    entity_id=new_id,
                    entity_type="memory",
                    name=label[:80],
                    properties={"content": content},
                )
            )
            for target_id, score in related:
                # The target may not exist as a graph entity yet (e.g. it
                # was only ever in the dense index from before this module
                # existed) -- skip silently rather than create a dangling edge.
                if kg.get_entity(target_id) is None:
                    continue
                kg.add_relation(
                    Relation(
                        source_id=new_id,
                        target_id=target_id,
                        relation_type="related_to",
                        weight=score,
                    )
                )
        finally:
            kg.close()
    except Exception:
        logger.debug("Knowledge graph mirror failed", exc_info=True)


__all__ = ["capture_turn"]
